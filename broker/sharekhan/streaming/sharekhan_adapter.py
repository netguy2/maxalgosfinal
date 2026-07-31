"""
Sharekhan WebSocket Adapter for Max Algos
Handles market data streaming from Sharekhan broker
"""

import json
import logging
import os
import random
import sys
import threading
import time
from typing import Any, Dict, Optional, Set, Tuple

# Add parent directory to path to allow imports FIRST
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

import utils.config  # This loads .env file at module level

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from database.auth_db import get_auth_token
from broker.sharekhan.database.master_contract_db import get_sharekhan_symbol_info
from SharekhanApi.sharekhanWebsocket import SharekhanWebSocket

logger = logging.getLogger("sharekhan_websocket")

# The vendored SharekhanApi SDK's internal SharekhanWebSocket._on_close(self,
# wsapp) is wired directly as websocket-client's on_close callback
# (SharekhanWebSocket.connect(), passed as on_close=self._on_close). Modern
# websocket-client (installed here: 1.9.0) invokes close callbacks as
# on_close(wsapp, close_status_code, close_msg) -- three positional args --
# but the SDK's method only accepts one, raising "takes 2 positional
# arguments but 4 were given" (2 = self+wsapp bound, 4 = the actual call)
# on every single connection close. Confirmed directly against the SDK
# source in production: `self.on_close(wsapp)` is the only line in the
# broken method, with no other side effects to preserve, so this patch
# reproduces that exact behavior while accepting (and ignoring) the extra
# close_status_code/close_msg args websocket-client now passes. Every
# reconnect (including the adapter's own watchdog-triggered close_connection()
# calls) was hitting this exception, which likely destabilized the SDK's
# internal reconnect state and contributed to connections cycling every few
# seconds instead of holding long enough to receive ticks.
def _patched_sdk_on_close(self, wsapp, close_status_code=None, close_msg=None):
    self.on_close(wsapp)


SharekhanWebSocket._on_close = _patched_sdk_on_close

class Config:
    MAX_RECONNECT_ATTEMPTS = 10
    BASE_RECONNECT_DELAY = 2
    MAX_RECONNECT_DELAY = 60
    HEARTBEAT_STALE_AFTER = 15.0  # seconds

    # Market data modes
    MODE_LTP = 1
    MODE_QUOTE = 2
    MODE_DEPTH = 3

class SharekhanWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Sharekhan WebSocket adapter with connection pooling and standard tick normalization"""

    def __init__(self):
        super().__init__()
        
        # Track active subscriptions and symbol lookup
        self.subscriptions: dict[Tuple[str, str, int], dict[str, Any]] = {}
        self.token_to_symbol: dict[str, Tuple[str, str]] = {}
        
        self.user_id = None
        self.broker_name = "sharekhan"
        self.ws_client = None
        self.running = False
        self.connected = False
        
        self.lock = threading.Lock()
        self.reconnect_attempts = 0
        self._thread = None
        self._last_msg_at = time.time()
        self._watchdog_thread = None

        logger.info(f"Sharekhan WebSocket adapter initialized on ZMQ port: {self.zmq_port}")

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None, force: bool = False
    ) -> None:
        """Initialize connection parameters for Sharekhan WebSocket API"""
        self.user_id = user_id
        self.broker_name = broker_name

        # Resolve access token specifically for user
        auth_token = get_auth_token(user_id, bypass_cache=True)
        if not auth_token or ":::" not in auth_token:
            logger.error(f"Missing Sharekhan credentials or active session for user {user_id}")
            raise ValueError(f"Missing Sharekhan credentials or active session for user {user_id}")

        self.access_token, self.customer_id = auth_token.split(":::", 1)
        self.running = True

    def connect(self) -> dict[str, Any]:
        """Establish connection to Sharekhan WebSocket endpoint in a background thread"""
        if not self.running:
            logger.error("Adapter not initialized. Call initialize() first.")
            return {"status": "error", "message": "Adapter not initialized"}

        with self.lock:
            if self.connected:
                return {"status": "success", "message": "Already connected"}

            # Initialize WebSocket client
            self.ws_client = SharekhanWebSocket(self.access_token)
            
            # Monkeypatch _parse_binary_data to decode bytes if received, or return as-is.
            # This bypasses the empty stub bug in the official SDK.
            def custom_parse(data):
                try:
                    if isinstance(data, (bytes, bytearray)):
                        return data.decode("utf-8")
                    return data
                except Exception as e:
                    logger.debug(f"Failed to decode WebSocket payload: {e}")
                    return data
            
            self.ws_client._parse_binary_data = custom_parse
            
            # Setup callbacks
            self.ws_client.on_open = self._on_open
            self.ws_client.on_message = self._on_message
            self.ws_client.on_data = self._on_message
            self.ws_client.on_error = self._on_error
            self.ws_client.on_close = self._on_close

            # Start watchdog
            if not self._watchdog_thread or not self._watchdog_thread.is_alive():
                self._watchdog_thread = threading.Thread(target=self._watchdog, daemon=True)
                self._watchdog_thread.start()

            # Run websocket loop off-thread
            self._thread = threading.Thread(target=self._ws_run_loop, daemon=True)
            self._thread.start()

        return {"status": "success", "message": "Connection initiated"}

    def _ws_run_loop(self):
        """Websocket connection loop with automatic reconnection"""
        while self.running:
            try:
                logger.info("Connecting to Sharekhan WebSocket...")
                self.ws_client.connect()
            except Exception as e:
                logger.error(f"Error in Sharekhan WebSocket connect loop: {e}")
            
            if self.running:
                self.connected = False
                self._handle_reconnect()

    def _handle_reconnect(self):
        """Exponential backoff reconnection logic"""
        self.reconnect_attempts += 1
        if self.reconnect_attempts > Config.MAX_RECONNECT_ATTEMPTS:
            logger.error("Maximum reconnection attempts reached. Stopping adapter.")
            self.running = False
            return

        delay = min(Config.MAX_RECONNECT_DELAY, Config.BASE_RECONNECT_DELAY * (2 ** self.reconnect_attempts))
        delay += random.uniform(0, 1)  # Jitter to avoid herd effect
        logger.info(f"Reconnecting to Sharekhan WebSocket in {delay:.2f} seconds (attempt {self.reconnect_attempts})...")
        
        # Sleep in small steps to allow fast exit on stop
        steps = int(delay * 10)
        for _ in range(steps):
            if not self.running:
                return
            time.sleep(0.1)

        # Refresh auth token before reconnecting to handle daily rollovers
        fresh_token = get_auth_token(self.user_id, bypass_cache=True)
        if fresh_token and ":::" in fresh_token:
            self.access_token, self.customer_id = fresh_token.split(":::", 1)
            self.ws_client = SharekhanWebSocket(self.access_token)
            self.ws_client._parse_binary_data = lambda d: d.decode("utf-8") if isinstance(d, (bytes, bytearray)) else d
            self.ws_client.on_open = self._on_open
            self.ws_client.on_message = self._on_message
            self.ws_client.on_data = self._on_message
            self.ws_client.on_error = self._on_error
            self.ws_client.on_close = self._on_close

    def disconnect(self) -> None:
        """Disconnect from Sharekhan WebSocket endpoint"""
        logger.info("Disconnecting from Sharekhan WebSocket...")
        self.running = False
        self.connected = False

        if self.ws_client:
            try:
                self.ws_client.close_connection()
            except Exception as e:
                logger.error(f"Error closing Sharekhan WebSocket: {e}")
            self.ws_client = None

        # Clean up local cache and ZMQ
        self.subscriptions.clear()
        self.token_to_symbol.clear()
        self.cleanup_zmq()
        logger.info("Disconnected from Sharekhan WebSocket successfully")

    def _on_open(self, wsapp):
        """WebSocket connection open callback"""
        self.connected = True
        self.reconnect_attempts = 0
        self._last_msg_at = time.time()
        logger.info("Sharekhan WebSocket connection established successfully")
        self._resubscribe_all()

    def _resubscribe_all(self):
        """Resubscribe to all active topics on connection/reconnection"""
        with self.lock:
            if not self.subscriptions:
                return
            
            # Group subscriptions by mode to optimize sub requests
            feed_tokens = []
            depth_tokens = []
            
            for sub in self.subscriptions.values():
                token = sub["token"]
                if sub["mode"] == Config.MODE_DEPTH:
                    depth_tokens.append(token)
                else:
                    feed_tokens.append(token)

            if feed_tokens:
                logger.info(f"Resubscribing to touchline feed: {feed_tokens}")
                self.ws_client.subscribe({"action": "subscribe", "key": ["feed"], "value": [",".join(feed_tokens)]})
            
            if depth_tokens:
                logger.info(f"Resubscribing to depth feed: {depth_tokens}")
                self.ws_client.subscribe({"action": "subscribe", "key": ["depth"], "value": [",".join(depth_tokens)]})

    def subscribe(self, symbol: str, exchange: str, mode: int = Config.MODE_QUOTE, depth_level: int = 5) -> dict[str, Any]:
        """Subscribe to a symbol's live data feed"""
        try:
            sym_info = get_sharekhan_symbol_info(symbol, exchange)
            if not sym_info:
                logger.warning(f"Symbol {symbol}:{exchange} not found in master contract DB")
                return {"status": "error", "code": "SYMBOL_NOT_FOUND", "message": f"Symbol {symbol} not found"}

            broker_token = f"{sym_info.brexchange}{sym_info.token}"
            
            with self.lock:
                self.token_to_symbol[broker_token] = (symbol, exchange)
                sub_key = (symbol, exchange, mode)
                self.subscriptions[sub_key] = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "mode": mode,
                    "token": broker_token,
                }

            if self.connected:
                key = "depth" if mode == Config.MODE_DEPTH else "feed"
                self.ws_client.subscribe({"action": "subscribe", "key": [key], "value": [broker_token]})
                logger.info(f"Subscription sent for {symbol} ({broker_token}) mode: {key}")

            return {"status": "success", "message": f"Subscription registered for {symbol}"}
        except Exception as e:
            logger.exception(f"Failed to subscribe to {symbol}: {e}")
            return {"status": "error", "message": str(e)}

    def unsubscribe(self, symbol: str, exchange: str, mode: int = Config.MODE_QUOTE) -> dict[str, Any]:
        """Unsubscribe from a symbol's live data feed"""
        try:
            sub_key = (symbol, exchange, mode)
            with self.lock:
                subscription = self.subscriptions.pop(sub_key, None)
                if not subscription:
                    return {"status": "success", "message": "Not subscribed"}

                broker_token = subscription["token"]
                # Determine if any other subscriptions are active for the same token
                still_subscribed = any(sub["token"] == broker_token for sub in self.subscriptions.values())
                if not still_subscribed:
                    self.token_to_symbol.pop(broker_token, None)

            if not still_subscribed and self.connected:
                key = "depth" if mode == Config.MODE_DEPTH else "feed"
                self.ws_client.unsubscribe({"action": "unsubscribe", "key": [key], "value": [broker_token]})
                logger.info(f"Unsubscription sent for {symbol} ({broker_token}) mode: {key}")

            return {"status": "success", "message": f"Unsubscribed from {symbol}"}
        except Exception as e:
            logger.exception(f"Failed to unsubscribe from {symbol}: {e}")
            return {"status": "error", "message": str(e)}

    def _on_message(self, ws, message):
        """Process incoming raw WebSocket packets"""
        self._last_msg_at = time.time()
        # "heartbeat" is Sharekhan's own non-JSON keepalive text (distinct
        # from the SDK's "ping"/"pong" constants) -- was falling through to
        # json.loads() below and logging a parse error on every heartbeat,
        # roughly every 30s, even though the connection was perfectly
        # healthy. Confirmed against production logs: "Error parsing
        # Sharekhan stream payload: Expecting value: line 1 column 1
        # (char 0), payload: heartbeat" repeating continuously.
        if not message or message in ("pong", "ping", "heartbeat"):
            return

        try:
            parsed = json.loads(message) if isinstance(message, str) else message
            if not parsed:
                return

            if isinstance(parsed, list):
                for tick in parsed:
                    self._process_tick(tick)
            else:
                self._process_tick(parsed)
        except Exception as e:
            logger.error(f"Error parsing Sharekhan stream payload: {e}, payload: {message}")

    def _process_tick(self, tick: dict):
        """Normalize the raw broker tick structure and publish to ZeroMQ"""
        exch = tick.get("exchange") or tick.get("exch")
        token = tick.get("scripCode") or tick.get("token") or tick.get("code")
        if not token:
            return

        # Map token back to symbol/exchange
        broker_token = f"{exch}{token}" if exch else str(token)
        sym_info = self.token_to_symbol.get(broker_token) or self.token_to_symbol.get(str(token))
        if not sym_info:
            return

        symbol, exchange = sym_info

        # Normalization and ZMQ publishing for all active subscription modes
        for mode in (Config.MODE_LTP, Config.MODE_QUOTE, Config.MODE_DEPTH):
            sub_key = (symbol, exchange, mode)
            if sub_key not in self.subscriptions:
                continue

            mode_str = {Config.MODE_LTP: "LTP", Config.MODE_QUOTE: "QUOTE", Config.MODE_DEPTH: "DEPTH"}[mode]
            topic = f"{exchange}_{symbol}_{mode_str}"

            normalized = {
                "symbol": symbol,
                "exchange": exchange,
                "mode": mode,
                "ltp": float(tick.get("lp", tick.get("ltp", 0)) or 0),
                "timestamp": int(time.time() * 1000),
            }

            if mode >= Config.MODE_QUOTE:
                normalized.update({
                    "open": float(tick.get("o", tick.get("open", 0)) or 0),
                    "high": float(tick.get("h", tick.get("high", 0)) or 0),
                    "low": float(tick.get("l", tick.get("low", 0)) or 0),
                    "close": float(tick.get("c", tick.get("close", 0)) or 0),
                    "volume": int(tick.get("v", tick.get("volume", 0)) or 0),
                    "average_price": float(tick.get("ap", tick.get("averagePrice", 0)) or 0),
                    "percent_change": float(tick.get("pc", tick.get("changePercent", 0)) or 0),
                    "last_quantity": int(tick.get("ltq", tick.get("lastTradedQty", 0)) or 0),
                    "last_trade_time": tick.get("ltt") or tick.get("lastTradeTime"),
                })

            if mode == Config.MODE_DEPTH:
                depth = tick.get("depth") or {}
                bids = depth.get("buy", []) or tick.get("bids", [])
                asks = depth.get("sell", []) or tick.get("asks", [])
                normalized.update({
                    "total_buy_quantity": int(tick.get("tbq", 0)),
                    "total_sell_quantity": int(tick.get("tsq", 0)),
                    "depth": {
                        "buy": bids,
                        "sell": asks,
                    }
                })

            self.publish_market_data(topic, normalized)

    def _on_error(self, ws, error):
        logger.error(f"Sharekhan WebSocket error: {error}")

    def _on_close(self, ws, *args):
        logger.info("Sharekhan WebSocket connection closed")
        self.connected = False

    def _watchdog(self):
        """Keepalive watchdog thread to restart connection if ticks freeze"""
        while self.running:
            time.sleep(5)
            if self.connected and (time.time() - self._last_msg_at) > Config.HEARTBEAT_STALE_AFTER:
                logger.warning("Sharekhan stream heartbeat silent, initiating reconnect")
                if self.ws_client:
                    try:
                        self.ws_client.close_connection()
                    except Exception:
                        pass
