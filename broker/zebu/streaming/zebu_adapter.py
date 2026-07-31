"""
Zebu WebSocket Adapter for Max Algos
Handles market data streaming from Zebu broker
"""

import json
import logging
import os
import sys
import threading
import time
from collections import Counter
from enum import IntEnum
from typing import Any, Dict, List, Optional

from database.auth_db import get_auth_token
from database.token_db import get_token

# Add parent directory to path to allow imports FIRST
sys.path.append(os.path.join(os.path.dirname(__file__), "../../../"))

from utils.config import get_zmq_port
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from websocket_proxy.mapping import SymbolMapper

from .zebu_mapping import ZebuCapabilityRegistry, ZebuExchangeMapper
from .zebu_websocket import ZebuWebSocket


# Configuration constants
class Config:
    MAX_RECONNECT_ATTEMPTS = 10
    BASE_RECONNECT_DELAY = 5
    MAX_RECONNECT_DELAY = 60
    CACHE_COMPLETENESS_THRESHOLD = 0.3
    WEBSOCKET_TIMEOUT = 30

    # Market data modes
    MODE_LTP = 1
    MODE_QUOTE = 2
    MODE_DEPTH = 3

    # Message types (same as Noren/Flattrade)
    MSG_AUTH = "ak"
    MSG_TOUCHLINE_FULL = "tf"
    MSG_TOUCHLINE_PARTIAL = "tk"
    MSG_DEPTH_FULL = "df"
    MSG_DEPTH_PARTIAL = "dk"


class MarketDataCache:
    """Manages market data caching with thread safety"""

    def __init__(self):
        self._cache = {}
        self._initialized_tokens = set()
        self._lock = threading.Lock()
        self.logger = logging.getLogger("market_cache")

    def get(self, token: str) -> dict[str, Any]:
        """Get cached data for a token"""
        with self._lock:
            return self._cache.get(token, {}).copy()

    def update(self, token: str, data: dict[str, Any]) -> dict[str, Any]:
        """Update cache with new data and return merged result"""
        with self._lock:
            cached_data = self._cache.get(token, {})
            merged_data = self._merge_data(cached_data, data, token)
            self._cache[token] = merged_data

            if token not in self._initialized_tokens:
                self._initialized_tokens.add(token)
                self._log_cache_initialization(token, data)

            return merged_data.copy()

    def clear(self, token: str = None) -> None:
        """Clear cache for specific token or all tokens"""
        with self._lock:
            if token:
                self._cache.pop(token, None)
                self._initialized_tokens.discard(token)
                self.logger.info(f"Cleared cache for token {token}")
            else:
                cache_size = len(self._cache)
                self._cache.clear()
                self._initialized_tokens.clear()
                self.logger.info(f"Cleared all cached market data ({cache_size} tokens)")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics"""
        with self._lock:
            return {
                "total_tokens": len(self._cache),
                "initialized_tokens": len(self._initialized_tokens),
                "tokens": list(self._cache.keys()),
            }

    def _merge_data(self, cached: dict, new: dict, token: str) -> dict:
        """Smart merge logic for market data"""
        merged = cached.copy()

        # Define field categories
        basic_fields = ["lp", "o", "h", "l", "c", "v", "ap", "pc", "ltq", "ltt", "tbq", "tsq"]
        depth_prices = ["bp1", "bp2", "bp3", "bp4", "bp5", "sp1", "sp2", "sp3", "sp4", "sp5"]
        depth_quantities = ["bq1", "bq2", "bq3", "bq4", "bq5", "sq1", "sq2", "sq3", "sq4", "sq5"]
        depth_orders = ["bo1", "bo2", "bo3", "bo4", "bo5", "so1", "so2", "so3", "so4", "so5"]

        for key, value in new.items():
            if self._should_preserve_cached_value(key, value, cached):
                continue
            merged[key] = value

        # Preserve cached values for missing fields
        self._preserve_missing_fields(merged, new, cached)
        return merged

    def _should_preserve_cached_value(self, key: str, new_value: Any, cached: dict) -> bool:
        """Determine if cached value should be preserved over new value"""
        # Preserve non-zero OHLC values when new value is zero
        if key in ["o", "h", "l", "c", "ap"] and self._is_zero_value(new_value):
            cached_value = cached.get(key)
            return cached_value is not None and not self._is_zero_value(cached_value)
        return False

    def _preserve_missing_fields(self, merged: dict, new: dict, cached: dict) -> None:
        """Preserve cached values for fields missing in new data"""
        for key, value in cached.items():
            if key not in new:
                merged[key] = value

    def _is_zero_value(self, value: Any) -> bool:
        """Check if value represents zero"""
        return value in [None, "", "0", 0, "0.0", 0.0]

    def _log_cache_initialization(self, token: str, data: dict) -> None:
        """Log cache initialization details"""
        basic_fields = ["lp", "o", "h", "l", "c", "v", "ap", "pc", "ltq", "ltt", "tbq", "tsq"]
        present_fields = sum(1 for field in basic_fields if field in data)
        completeness = present_fields / len(basic_fields)

        self.logger.info(
            f"Initializing cache for token {token} - "
            f"{present_fields}/{len(basic_fields)} fields present ({completeness:.1%})"
        )


class LTPNormalizer:
    """Handles LTP mode data normalization"""

    @staticmethod
    def normalize(data: dict[str, Any], msg_type: str) -> dict[str, Any]:
        ltp = safe_float(data.get("lp"))
        close = safe_float(data.get("c"))
        result = {
            "mode": Config.MODE_LTP,
            "ltp": ltp,
            "zebu_timestamp": safe_int(data.get("ft")),
        }
        # Same change/change_percent computation as QuoteNormalizer/
        # DepthNormalizer below -- "data" here is the MarketDataCache-merged
        # dict (see normalize_data() above), so "c" is present once any
        # message for this token has carried it, even if this specific tick
        # was a touchline-partial update. Consumers (MarketDataManager.ts,
        # MarketTicker.tsx) read change/change_percent regardless of mode,
        # and LTP mode is the default subscription mode -- omitting this
        # left every LTP-mode subscriber (the Dashboard ticker) stuck
        # showing "--" forever even though ltp itself ticks fine.
        if close:
            change = ltp - close
            result["change"] = round(change, 2)
            result["change_percent"] = round(change / close * 100, 2)
        return result


class QuoteNormalizer:
    """Handles Quote mode data normalization"""

    @staticmethod
    def normalize(data: dict[str, Any], msg_type: str) -> dict[str, Any]:
        ltp = safe_float(data.get("lp"))
        close = safe_float(data.get("c"))
        result = {
            "mode": Config.MODE_QUOTE,
            "ltp": ltp,
            "volume": safe_int(data.get("v")),
            "open": safe_float(data.get("o")),
            "high": safe_float(data.get("h")),
            "low": safe_float(data.get("l")),
            "close": close,
            "average_price": safe_float(data.get("ap")),
            "percent_change": safe_float(data.get("pc")),
            "last_quantity": safe_int(data.get("ltq")),
            "last_trade_time": data.get("ltt"),
            "zebu_timestamp": safe_int(data.get("ft")),
        }
        # Zebu only sends "pc" (percent change, its own field), not "change"
        # or a frontend-matching "change_percent" -- every consumer
        # (MarketDataManager.ts, the Dashboard index cards) reads those
        # exact key names, same as every other broker adapter's normalizer
        # (see broker/arrow/streaming/arrow_adapter.py's identical
        # ltp - close computation). Without this, NIFTY/BANKNIFTY (and
        # every other symbol) never populate change/change_percent even
        # though ltp itself is ticking fine.
        if close:
            change = ltp - close
            result["change"] = round(change, 2)
            result["change_percent"] = round(change / close * 100, 2)
        return result


class DepthNormalizer:
    """Handles Depth mode data normalization"""

    @staticmethod
    def normalize(data: dict[str, Any], msg_type: str) -> dict[str, Any]:
        ltp = safe_float(data.get("lp"))
        close = safe_float(data.get("c"))
        result = {
            "mode": Config.MODE_DEPTH,
            "ltp": ltp,
            "volume": safe_int(data.get("v")),
            "open": safe_float(data.get("o")),
            "high": safe_float(data.get("h")),
            "low": safe_float(data.get("l")),
            "close": close,
            "average_price": safe_float(data.get("ap")),
            "percent_change": safe_float(data.get("pc")),
            "last_quantity": safe_int(data.get("ltq")),
            "last_trade_time": data.get("ltt"),
            "total_buy_quantity": safe_int(data.get("tbq")),
            "total_sell_quantity": safe_int(data.get("tsq")),
            "zebu_timestamp": safe_int(data.get("ft")),
        }
        # Same change/change_percent computation as QuoteNormalizer above --
        # Depth mode carries the same underlying fields, and consumers read
        # these keys regardless of which mode the tick arrived in.
        if close:
            change = ltp - close
            result["change"] = round(change, 2)
            result["change_percent"] = round(change / close * 100, 2)

        # Add depth data
        if msg_type in (Config.MSG_DEPTH_FULL, Config.MSG_DEPTH_PARTIAL):
            result["depth"] = {
                "buy": [
                    {
                        "price": safe_float(data.get("bp1")),
                        "quantity": safe_int(data.get("bq1")),
                        "orders": safe_int(data.get("bo1")),
                    },
                    {
                        "price": safe_float(data.get("bp2")),
                        "quantity": safe_int(data.get("bq2")),
                        "orders": safe_int(data.get("bo2")),
                    },
                    {
                        "price": safe_float(data.get("bp3")),
                        "quantity": safe_int(data.get("bq3")),
                        "orders": safe_int(data.get("bo3")),
                    },
                    {
                        "price": safe_float(data.get("bp4")),
                        "quantity": safe_int(data.get("bq4")),
                        "orders": safe_int(data.get("bo4")),
                    },
                    {
                        "price": safe_float(data.get("bp5")),
                        "quantity": safe_int(data.get("bq5")),
                        "orders": safe_int(data.get("bo5")),
                    },
                ],
                "sell": [
                    {
                        "price": safe_float(data.get("sp1")),
                        "quantity": safe_int(data.get("sq1")),
                        "orders": safe_int(data.get("so1")),
                    },
                    {
                        "price": safe_float(data.get("sp2")),
                        "quantity": safe_int(data.get("sq2")),
                        "orders": safe_int(data.get("so2")),
                    },
                    {
                        "price": safe_float(data.get("sp3")),
                        "quantity": safe_int(data.get("sq3")),
                        "orders": safe_int(data.get("so3")),
                    },
                    {
                        "price": safe_float(data.get("sp4")),
                        "quantity": safe_int(data.get("sq4")),
                        "orders": safe_int(data.get("so4")),
                    },
                    {
                        "price": safe_float(data.get("sp5")),
                        "quantity": safe_int(data.get("sq5")),
                        "orders": safe_int(data.get("so5")),
                    },
                ],
            }
            result["depth_level"] = 5

            # Add circuit limits and additional data
            result.update(
                {
                    "upper_circuit": safe_float(data.get("uc")),
                    "lower_circuit": safe_float(data.get("lc")),
                    "52_week_high": safe_float(data.get("52h")),
                    "52_week_low": safe_float(data.get("52l")),
                    "total_traded_value": safe_int(data.get("toi")),
                }
            )

        return result


class ZebuWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Zebu WebSocket adapter with improved structure and error handling"""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("zebu_websocket")

        # Log the actual ZMQ port being used
        actual_zmq_port = get_zmq_port()
        self.logger.info(
            f"Zebu adapter initialized - Expected ZMQ port: {actual_zmq_port}, Actual bound port: {self.zmq_port}"
        )

        # Warn if there's a mismatch
        if str(self.zmq_port) != str(actual_zmq_port):
            self.logger.warning(
                f"ZMQ port mismatch! Server expects {actual_zmq_port} but adapter bound to {self.zmq_port}"
            )
            self.logger.warning("Data may not reach clients properly!")

        self._setup_adapter()
        self._setup_market_cache()
        self._setup_connection_management()
        self._setup_normalizers()

    def _setup_adapter(self):
        """Initialize adapter-specific settings"""
        self.user_id = None
        self.broker_name = "zebu"
        self.ws_client = None

    def _setup_market_cache(self):
        """Initialize market data caching system"""
        self.market_cache = MarketDataCache()
        self.subscriptions = {}
        self.token_to_symbol = {}
        self.ws_subscription_refs = {}  # Reference counting for WebSocket subscriptions

    def _setup_connection_management(self):
        """Initialize connection management"""
        self.running = False
        self.connected = False
        self.lock = threading.Lock()
        self.reconnect_attempts = 0
        self._reconnect_timer = None

        # Debounced subscribe/unsubscribe batching -- mirrors
        # broker/shoonya/streaming/shoonya_adapter.py. _sub_queue/_unsub_queue
        # hold (scrip, ws_call) tuples where ws_call is "touchline" or
        # "depth". Leading-edge debounce: the FIRST call after a quiet
        # period flushes immediately (no debounce wait), so a single-symbol
        # UI click pays ~0ms adapter overhead. Subsequent calls within
        # `_batch_delay` of the last flush wait it out so they coalesce --
        # that's how an option-chain-sized symbol burst still hits a single
        # WS frame instead of one frame per symbol.
        self._sub_queue: list[tuple[str, str]] = []
        self._unsub_queue: list[tuple[str, str]] = []
        self._sub_batch_timer: threading.Timer | None = None
        self._unsub_batch_timer: threading.Timer | None = None
        self._last_sub_flush_at: float = 0.0
        self._last_unsub_flush_at: float = 0.0
        self._batch_delay = 0.5

    def _setup_normalizers(self):
        """Initialize data normalizers"""
        self.normalizers = {
            Config.MODE_LTP: LTPNormalizer(),
            Config.MODE_QUOTE: QuoteNormalizer(),
            Config.MODE_DEPTH: DepthNormalizer(),
        }

    def initialize(
        self, broker_name: str, user_id: str, auth_data: dict[str, str] | None = None
    ) -> None:
        """Initialize connection with Zebu WebSocket API"""
        self.user_id = user_id
        self.broker_name = broker_name

        # Get Zebu credentials from environment
        # BROKER_API_KEY format: userid:::client_id (e.g., Z56004:::Z56004_U)
        # userid is used as both actid and uid in WebSocket authentication

        full_api_key = os.getenv("BROKER_API_KEY", "")

        if full_api_key and ":::" in full_api_key:
            # Extract trading user ID (before :::)
            self.actid = full_api_key.split(":::")[0]
            self.logger.info(f"Using Zebu user ID from BROKER_API_KEY: {self.actid}")
        elif full_api_key:
            # Legacy format without ::: separator
            self.actid = full_api_key
            self.logger.warning(f"BROKER_API_KEY missing ':::' separator, using as-is: {self.actid}")
        else:
            # Fallback to user_id if no API key is set
            self.actid = user_id
            self.logger.warning(f"No BROKER_API_KEY found. Using user_id '{user_id}' as actid.")

        # Get auth token from database
        self.susertoken = get_auth_token(user_id, bypass_cache=True)

        if not self.actid or not self.susertoken:
            self.logger.error(f"Missing Zebu credentials for user {user_id}")
            raise ValueError(f"Missing Zebu credentials for user {user_id}")

        self.logger.info(f"Using Zebu credentials - User ID: {self.actid}")

        # Initialize WebSocket client
        self.ws_client = ZebuWebSocket(
            user_id=self.actid,  # Both user_id and actid should be the Zebu account ID
            actid=self.actid,
            susertoken=self.susertoken,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )

        self.running = True

    def connect(self) -> None:
        """Establish connection to Zebu WebSocket endpoint"""
        if not self.ws_client:
            self.logger.error("WebSocket client not initialized. Call initialize() first.")
            return

        self.logger.info("Connecting to Zebu WebSocket...")
        connected = self.ws_client.connect()

        if connected:
            self.connected = True
            self.reconnect_attempts = 0
            self.logger.info("Connected to Zebu WebSocket successfully")
        else:
            raise ConnectionError("Failed to connect to Zebu WebSocket")

    def disconnect(self) -> None:
        """Disconnect from Zebu WebSocket endpoint"""
        # Capture ws_client ref and update state under lock,
        # but call stop() outside the lock to avoid deadlock
        # (stop() joins the WS thread whose callbacks acquire self.lock)
        ws_ref = None
        with self.lock:
            self.running = False
            self.connected = False

            # Cancel any pending reconnection timer
            if self._reconnect_timer:
                self._reconnect_timer.cancel()
                self._reconnect_timer = None

            # Cancel any pending subscribe/unsubscribe batch timers too --
            # an uncancelled threading.Timer left running after disconnect
            # is a thread leak (see broker/shoonya/streaming/shoonya_adapter.py
            # for the same cleanup on its disconnect path).
            if self._sub_batch_timer:
                self._sub_batch_timer.cancel()
                self._sub_batch_timer = None
            if self._unsub_batch_timer:
                self._unsub_batch_timer.cancel()
                self._unsub_batch_timer = None
            self._sub_queue.clear()
            self._unsub_queue.clear()

            ws_ref = self.ws_client
            self.ws_client = None

        if ws_ref:
            ws_ref.stop()

        # Clean up market data cache and subscriptions
        self.market_cache.clear()
        self.subscriptions.clear()
        self.token_to_symbol.clear()
        self.ws_subscription_refs.clear()

        # Clean up ZeroMQ resources
        self.cleanup_zmq()

        self.logger.info("Disconnected from Zebu WebSocket")

    def cleanup(self) -> None:
        """Clean up all resources — safety net for missed disconnect calls"""
        if getattr(self, "_cleaned_up", False):
            return
        self._cleaned_up = True

        try:
            self.running = False

            with self.lock:
                if self._reconnect_timer:
                    self._reconnect_timer.cancel()
                    self._reconnect_timer = None
                if self._sub_batch_timer:
                    self._sub_batch_timer.cancel()
                    self._sub_batch_timer = None
                if self._unsub_batch_timer:
                    self._unsub_batch_timer.cancel()
                    self._unsub_batch_timer = None
                self._sub_queue.clear()
                self._unsub_queue.clear()

            if self.ws_client:
                try:
                    self.ws_client.stop()
                except Exception as e:
                    self.logger.error(f"Error stopping WebSocket during cleanup: {e}")
                finally:
                    self.ws_client = None

            self.market_cache.clear()
            self.subscriptions.clear()
            self.token_to_symbol.clear()
            self.ws_subscription_refs.clear()
            self.cleanup_zmq()
            self.connected = False
            self.logger.info("Zebu adapter cleanup complete")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

    def __del__(self):
        """Destructor to ensure cleanup on garbage collection"""
        try:
            self.cleanup()
        except Exception:
            pass

    def subscribe(
        self, symbol: str, exchange: str, mode: int = Config.MODE_QUOTE, depth_level: int = 5
    ) -> dict[str, Any]:
        """Subscribe to market data with improved error handling"""
        try:
            self.logger.info(f"[SUBSCRIBE] Request for {symbol}.{exchange} mode={mode}")

            # Validate inputs
            if not self._validate_subscription_params(symbol, exchange, mode):
                return self._create_error_response(
                    "INVALID_PARAMS", "Invalid subscription parameters"
                )

            # Get token information
            token_info = self._get_token_info(symbol, exchange)
            if not token_info:
                return self._create_error_response("SYMBOL_NOT_FOUND", f"Symbol {symbol} not found")

            # Create subscription
            subscription = self._create_subscription(
                symbol, exchange, mode, depth_level, token_info
            )

            # Generate a unique correlation_id for each subscription
            # This allows multiple clients to subscribe to the same symbol
            import uuid

            unique_id = str(uuid.uuid4())[:8]
            correlation_id = f"{symbol}_{exchange}_{mode}_{unique_id}"

            # Check if we need to subscribe to WebSocket
            base_correlation_id = f"{symbol}_{exchange}_{mode}"
            already_ws_subscribed = any(
                cid.startswith(base_correlation_id) for cid in self.subscriptions.keys()
            )

            if already_ws_subscribed:
                self.logger.info(
                    f"[SUBSCRIBE] WebSocket already subscribed for {base_correlation_id}, adding client subscription {correlation_id}"
                )
            else:
                self.logger.info(
                    f"[SUBSCRIBE] New WebSocket subscription needed for {correlation_id}"
                )

            # Always store the subscription (each client gets their own entry)
            self._store_subscription(correlation_id, subscription)

            # Subscribe via WebSocket (reference counting will handle duplicates)
            if self.connected:
                self._websocket_subscribe(subscription)
                if not already_ws_subscribed:
                    self.logger.info(
                        f"[SUBSCRIBE] WebSocket subscription sent for {subscription['scrip']}"
                    )
            else:
                self.logger.warning(
                    f"[SUBSCRIBE] Not connected, cannot subscribe to {subscription['scrip']}"
                )

            # Log current ZMQ port and subscription state
            self.logger.info(f"[SUBSCRIBE] Publishing to ZMQ port: {self.zmq_port}")
            self.logger.info(f"[SUBSCRIBE] Total active subscriptions: {len(self.subscriptions)}")

            return self._create_success_response(
                f"Subscribed to {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
            )

        except Exception as e:
            self.logger.error(f"Subscription error for {symbol}.{exchange}: {e}")
            return self._create_error_response("SUBSCRIPTION_ERROR", str(e))

    def unsubscribe(
        self, symbol: str, exchange: str, mode: int = Config.MODE_QUOTE
    ) -> dict[str, Any]:
        """Unsubscribe from market data"""
        base_correlation_id = f"{symbol}_{exchange}_{mode}"

        with self.lock:
            # Find the first matching subscription for this client
            matching_subscriptions = [
                (cid, sub)
                for cid, sub in self.subscriptions.items()
                if cid.startswith(base_correlation_id)
            ]

            if not matching_subscriptions:
                return self._create_error_response(
                    "NOT_SUBSCRIBED", f"Not subscribed to {symbol}.{exchange}"
                )

            # Remove the first matching subscription
            correlation_id, subscription = matching_subscriptions[0]

            # Check if this is the last subscription for this symbol/exchange/mode
            is_last = len(matching_subscriptions) == 1

            # Remove the subscription
            del self.subscriptions[correlation_id]

            # Clean up token mapping if no other subscriptions use it
            token = subscription["token"]
            if not any(sub["token"] == token for sub in self.subscriptions.values()):
                self.token_to_symbol.pop(token, None)

            # Only unsubscribe from WebSocket if this was the last subscription
            if is_last:
                scrip = subscription["scrip"]
                if scrip in self.ws_subscription_refs:
                    if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
                        self.ws_subscription_refs[scrip]["touchline_count"] -= 1
                        if self.ws_subscription_refs[scrip]["touchline_count"] <= 0:
                            self._websocket_unsubscribe(subscription)
                    elif mode == Config.MODE_DEPTH:
                        self.ws_subscription_refs[scrip]["depth_count"] -= 1
                        if self.ws_subscription_refs[scrip]["depth_count"] <= 0:
                            self._websocket_unsubscribe(subscription)

        return self._create_success_response(
            f"Unsubscribed from {symbol}.{exchange}", symbol=symbol, exchange=exchange, mode=mode
        )

    def _validate_subscription_params(self, symbol: str, exchange: str, mode: int) -> bool:
        """Validate subscription parameters"""
        return (
            symbol and exchange and mode in [Config.MODE_LTP, Config.MODE_QUOTE, Config.MODE_DEPTH]
        )

    def _get_token_info(self, symbol: str, exchange: str) -> dict | None:
        """Get token information for symbol and exchange"""
        self.logger.info(f"Looking up token for {symbol}.{exchange}")
        token_info = SymbolMapper.get_token_from_symbol(symbol, exchange)
        if token_info:
            self.logger.info(
                f"Token found: {token_info['token']}, brexchange: {token_info['brexchange']}"
            )
        return token_info

    def _create_subscription(
        self, symbol: str, exchange: str, mode: int, depth_level: int, token_info: dict
    ) -> dict:
        """Create subscription object"""
        token = token_info["token"]
        brexchange = token_info["brexchange"]
        zebu_exchange = ZebuExchangeMapper.to_zebu_exchange(brexchange)
        scrip = f"{zebu_exchange}|{token}"

        return {
            "symbol": symbol,
            "exchange": exchange,
            "mode": mode,
            "depth_level": depth_level,
            "token": token,
            "scrip": scrip,
        }

    def _store_subscription(self, correlation_id: str, subscription: dict) -> None:
        """Store subscription and update mappings"""
        with self.lock:
            self.subscriptions[correlation_id] = subscription
            self.token_to_symbol[subscription["token"]] = (
                subscription["symbol"],
                subscription["exchange"],
            )

    def _websocket_subscribe(self, subscription: dict) -> None:
        """Handle WebSocket subscription with reference counting. The actual
        WS send is enqueued and debounce-batched (see _enqueue_sub_flush
        below) rather than sent synchronously here -- mirrors
        broker/shoonya/streaming/shoonya_adapter.py's _websocket_subscribe.
        Ref-count bookkeeping is unchanged from the original synchronous
        version; only the "first subscriber for this scrip" branch now
        enqueues instead of calling self.ws_client directly."""
        scrip = subscription["scrip"]
        mode = subscription["mode"]

        # Initialize reference count for this scrip if not exists
        if scrip not in self.ws_subscription_refs:
            self.ws_subscription_refs[scrip] = {"touchline_count": 0, "depth_count": 0}

        if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
            if self.ws_subscription_refs[scrip]["touchline_count"] == 0:
                self.logger.info(f"First touchline subscription for {scrip}")
                self._enqueue_sub_flush(scrip, "touchline")
                self.ws_subscription_refs[scrip]["touchline_count"] = 1
            else:
                # Already subscribed, just increment the count
                self.ws_subscription_refs[scrip]["touchline_count"] += 1
                self.logger.info(
                    f"Additional touchline subscription for {scrip}, count: {self.ws_subscription_refs[scrip]['touchline_count']}"
                )
        elif mode == Config.MODE_DEPTH:
            if self.ws_subscription_refs[scrip]["depth_count"] == 0:
                self.logger.info(f"First depth subscription for {scrip}")
                self._enqueue_sub_flush(scrip, "depth")
                self.ws_subscription_refs[scrip]["depth_count"] = 1
            else:
                # Already subscribed, just increment the count
                self.ws_subscription_refs[scrip]["depth_count"] += 1
                self.logger.info(
                    f"Additional depth subscription for {scrip}, count: {self.ws_subscription_refs[scrip]['depth_count']}"
                )

    def _websocket_unsubscribe(self, subscription: dict) -> None:
        """Handle WebSocket unsubscription with reference counting. Same
        enqueue/debounce change as _websocket_subscribe above. Only ever
        called from unsubscribe(), which already holds self.lock -- pass
        already_locked=True so the enqueue helper doesn't try to
        re-acquire it."""
        scrip = subscription["scrip"]
        mode = subscription["mode"]

        if scrip not in self.ws_subscription_refs:
            return

        if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
            self.ws_subscription_refs[scrip]["touchline_count"] -= 1
            if self.ws_subscription_refs[scrip]["touchline_count"] <= 0:
                self.logger.info(f"Last touchline subscription for {scrip}")
                self._enqueue_unsub_flush(scrip, "touchline", already_locked=True)
                self.ws_subscription_refs[scrip]["touchline_count"] = 0
        elif mode == Config.MODE_DEPTH:
            self.ws_subscription_refs[scrip]["depth_count"] -= 1
            if self.ws_subscription_refs[scrip]["depth_count"] <= 0:
                self.logger.info(f"Last depth subscription for {scrip}")
                self._enqueue_unsub_flush(scrip, "depth", already_locked=True)
                self.ws_subscription_refs[scrip]["depth_count"] = 0

    # --- Debounced subscribe/unsubscribe batching ---------------------------
    # Ported from broker/shoonya/streaming/shoonya_adapter.py, adapted for
    # Zebu's calling convention: subscribe() calls _websocket_subscribe
    # WITHOUT holding self.lock, but unsubscribe() calls
    # _websocket_unsubscribe from INSIDE its own `with self.lock:` block
    # (self.lock is a plain threading.Lock, non-reentrant) -- so the two
    # enqueue helpers below take an explicit `already_locked` flag instead
    # of assuming a single consistent calling context.

    def _enqueue_sub_flush(self, scrip: str, ws_call: str, already_locked: bool = False) -> None:
        """Enqueue one (scrip, ws_call) pair for the subscribe batch and
        flush immediately (leading edge) or schedule a debounce timer."""
        if already_locked:
            self._sub_queue.append((scrip, ws_call))
            flush_now = self._schedule_sub_flush_locked()
        else:
            with self.lock:
                self._sub_queue.append((scrip, ws_call))
                flush_now = self._schedule_sub_flush_locked()
        if flush_now:
            # Always flush on a separate thread: _flush_subscription_batch
            # re-acquires self.lock, which would deadlock if called
            # synchronously from an already-locked caller.
            threading.Thread(target=self._flush_subscription_batch, daemon=True).start()

    def _enqueue_unsub_flush(self, scrip: str, ws_call: str, already_locked: bool = False) -> None:
        """Mirror of _enqueue_sub_flush for the unsubscribe queue."""
        if already_locked:
            self._unsub_queue.append((scrip, ws_call))
            flush_now = self._schedule_unsub_flush_locked()
        else:
            with self.lock:
                self._unsub_queue.append((scrip, ws_call))
                flush_now = self._schedule_unsub_flush_locked()
        if flush_now:
            threading.Thread(target=self._flush_unsubscription_batch, daemon=True).start()

    def _schedule_sub_flush_locked(self) -> bool:
        """Decide whether to flush the subscribe queue now (leading edge) or
        schedule a timer for the end of the current debounce window. Caller
        must hold self.lock. Returns True if the caller should trigger
        _flush_subscription_batch (on a separate thread, since this function
        itself must not block or re-acquire the lock)."""
        elapsed = time.time() - self._last_sub_flush_at
        if elapsed >= self._batch_delay:
            self._last_sub_flush_at = time.time()
            if self._sub_batch_timer:
                self._sub_batch_timer.cancel()
                self._sub_batch_timer = None
            return True
        if self._sub_batch_timer is None:
            delay = max(0.0, self._batch_delay - elapsed)
            self._sub_batch_timer = threading.Timer(delay, self._flush_subscription_batch)
            self._sub_batch_timer.daemon = True
            self._sub_batch_timer.start()
        return False

    def _schedule_unsub_flush_locked(self) -> bool:
        """Mirror of _schedule_sub_flush_locked for the unsubscribe queue."""
        elapsed = time.time() - self._last_unsub_flush_at
        if elapsed >= self._batch_delay:
            self._last_unsub_flush_at = time.time()
            if self._unsub_batch_timer:
                self._unsub_batch_timer.cancel()
                self._unsub_batch_timer = None
            return True
        if self._unsub_batch_timer is None:
            delay = max(0.0, self._batch_delay - elapsed)
            self._unsub_batch_timer = threading.Timer(delay, self._flush_unsubscription_batch)
            self._unsub_batch_timer.daemon = True
            self._unsub_batch_timer.start()
        return False

    def _reconcile_queues_locked(self) -> None:
        """Cancel matching (scrip, ws_call) pairs that appear in both
        _sub_queue and _unsub_queue -- a subscribe immediately followed by
        an unsubscribe within the same debounce window has no net effect on
        the broker; sending both wastes a round trip. Caller must hold
        self.lock."""
        if not (self._sub_queue and self._unsub_queue):
            return
        cancel = Counter(self._sub_queue) & Counter(self._unsub_queue)
        if not cancel:
            return

        def filter_queue(
            queue: list[tuple[str, str]], to_cancel: Counter
        ) -> list[tuple[str, str]]:
            remaining = Counter(to_cancel)
            out: list[tuple[str, str]] = []
            for entry in queue:
                if remaining.get(entry, 0) > 0:
                    remaining[entry] -= 1
                    continue
                out.append(entry)
            return out

        self._sub_queue = filter_queue(self._sub_queue, cancel)
        self._unsub_queue = filter_queue(self._unsub_queue, cancel)

    def _flush_subscription_batch(self) -> None:
        """Drain _sub_queue, group by ws_call type, dedupe, and hand off to
        the WS layer's batched API (which chunks into MAX_SCRIPS_PER_BATCH
        '#'-joined sends)."""
        with self.lock:
            self._sub_batch_timer = None
            self._reconcile_queues_locked()
            if not self._sub_queue:
                return
            queue_snapshot = self._sub_queue
            self._sub_queue = []
            self._last_sub_flush_at = time.time()
            ws = self.ws_client

        if not ws:
            self.logger.warning(
                f"[BATCH_SUBSCRIBE] No WS client; dropping {len(queue_snapshot)} pending subs "
                f"(will be re-sent on reconnect via _resubscribe_all)"
            )
            return

        touchline_scrips: list[str] = []
        depth_scrips: list[str] = []
        seen_touchline: set[str] = set()
        seen_depth: set[str] = set()

        for scrip, ws_call in queue_snapshot:
            if ws_call == "touchline" and scrip not in seen_touchline:
                seen_touchline.add(scrip)
                touchline_scrips.append(scrip)
            elif ws_call == "depth" and scrip not in seen_depth:
                seen_depth.add(scrip)
                depth_scrips.append(scrip)

        try:
            if touchline_scrips:
                self.logger.info(
                    f"[BATCH_SUBSCRIBE] Sending {len(touchline_scrips)} touchline scrips"
                )
                ws.subscribe_touchline_scrips(touchline_scrips)
            if depth_scrips:
                self.logger.info(f"[BATCH_SUBSCRIBE] Sending {len(depth_scrips)} depth scrips")
                ws.subscribe_depth_scrips(depth_scrips)
        except Exception as e:
            self.logger.error(
                f"Error queueing batch subscription: {e}; subscriptions retained "
                f"in adapter and will be re-sent on reconnect"
            )

    def _flush_unsubscription_batch(self) -> None:
        """Drain _unsub_queue and hand off to the WS-layer batched API."""
        with self.lock:
            self._unsub_batch_timer = None
            self._reconcile_queues_locked()
            if not self._unsub_queue:
                return
            queue_snapshot = self._unsub_queue
            self._unsub_queue = []
            self._last_unsub_flush_at = time.time()
            ws = self.ws_client

        if not ws:
            return

        touchline_scrips: list[str] = []
        depth_scrips: list[str] = []
        seen_touchline: set[str] = set()
        seen_depth: set[str] = set()

        for scrip, ws_call in queue_snapshot:
            if ws_call == "touchline" and scrip not in seen_touchline:
                seen_touchline.add(scrip)
                touchline_scrips.append(scrip)
            elif ws_call == "depth" and scrip not in seen_depth:
                seen_depth.add(scrip)
                depth_scrips.append(scrip)

        try:
            if touchline_scrips:
                self.logger.info(
                    f"[BATCH_UNSUBSCRIBE] Sending {len(touchline_scrips)} touchline scrips"
                )
                ws.unsubscribe_touchline_scrips(touchline_scrips)
            if depth_scrips:
                self.logger.info(
                    f"[BATCH_UNSUBSCRIBE] Sending {len(depth_scrips)} depth scrips"
                )
                ws.unsubscribe_depth_scrips(depth_scrips)
        except Exception as e:
            self.logger.error(f"Error queueing batch unsubscription: {e}")

    def _remove_subscription(self, correlation_id: str, subscription: dict) -> None:
        """Remove subscription and clean up mappings"""
        token = subscription["token"]
        scrip = subscription["scrip"]
        mode = subscription["mode"]

        # Remove subscription
        del self.subscriptions[correlation_id]

        # Check if there are any other subscriptions for the same scrip and mode
        has_other_subscriptions = any(
            sub["scrip"] == scrip and sub["mode"] == mode for sub in self.subscriptions.values()
        )

        # Only decrement reference count if no other subscriptions exist
        if not has_other_subscriptions and scrip in self.ws_subscription_refs:
            if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
                self.ws_subscription_refs[scrip]["touchline_count"] -= 1
                if self.ws_subscription_refs[scrip]["touchline_count"] <= 0:
                    self.ws_subscription_refs[scrip]["touchline_count"] = 0
            elif mode == Config.MODE_DEPTH:
                self.ws_subscription_refs[scrip]["depth_count"] -= 1
                if self.ws_subscription_refs[scrip]["depth_count"] <= 0:
                    self.ws_subscription_refs[scrip]["depth_count"] = 0

            # Clean up reference count if both counts are 0
            if (
                self.ws_subscription_refs[scrip]["touchline_count"] <= 0
                and self.ws_subscription_refs[scrip]["depth_count"] <= 0
            ):
                del self.ws_subscription_refs[scrip]

        # Remove token mapping if no other subscriptions use it
        if not any(sub["token"] == token for sub in self.subscriptions.values()):
            self.token_to_symbol.pop(token, None)
            self.market_cache.clear(token)

    def _on_open(self, ws):
        """Handle WebSocket connection open"""
        self.logger.info("Connected to Zebu WebSocket")
        self.connected = True
        self._resubscribe_all()

    def _on_error(self, ws, error):
        """Handle WebSocket connection error"""
        self.logger.error(f"Zebu WebSocket error: {error}")
        self._handle_websocket_error(error)

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection close"""
        self.logger.info(f"Zebu WebSocket connection closed: {close_status_code} - {close_msg}")
        self.connected = False

        if self.running:
            self._schedule_reconnection()

    def _handle_websocket_error(self, error: Exception) -> None:
        """Centralized error handling for WebSocket operations"""
        self.logger.error(f"WebSocket error: {error}")

        if self.running:
            self._schedule_reconnection()

    def _schedule_reconnection(self) -> None:
        """Schedule reconnection with exponential backoff"""
        with self.lock:
            if self.reconnect_attempts >= Config.MAX_RECONNECT_ATTEMPTS:
                self.logger.error("Maximum reconnection attempts reached")
                self.running = False
                return

            delay = min(
                Config.BASE_RECONNECT_DELAY * (2**self.reconnect_attempts),
                Config.MAX_RECONNECT_DELAY,
            )

            self.logger.info(
                f"Reconnecting in {delay}s (attempt {self.reconnect_attempts + 1})"
            )

            # Cancel existing timer if present
            if self._reconnect_timer:
                self._reconnect_timer.cancel()

            self._reconnect_timer = threading.Timer(delay, self._attempt_reconnection)
            self._reconnect_timer.daemon = True
            self._reconnect_timer.start()

    def _attempt_reconnection(self) -> None:
        """Attempt to reconnect to WebSocket"""
        with self.lock:
            self._reconnect_timer = None

            if not self.running:
                self.logger.debug("Reconnection skipped - adapter no longer running")
                return

        self.reconnect_attempts += 1

        try:
            # Clean up old WebSocket client to prevent FD leaks
            if self.ws_client:
                self.logger.debug("Cleaning up old WebSocket client before reconnection")
                try:
                    self.ws_client.stop()
                except Exception as cleanup_err:
                    self.logger.warning(f"Error cleaning up old WebSocket: {cleanup_err}")

            # Re-read a fresh auth token from the database before recreating the client.
            # Indian broker tokens roll over daily at ~3 AM IST, so a reconnect after
            # rollover must not reuse the construction-time token.
            fresh_token = get_auth_token(self.user_id, bypass_cache=True)
            with self.lock:
                if fresh_token:
                    self.susertoken = fresh_token
                else:
                    self.logger.warning(
                        "Could not fetch fresh auth token from database; "
                        "reusing existing token for reconnection"
                    )

            # Recreate WebSocket client
            self.ws_client = ZebuWebSocket(
                user_id=self.actid,  # Both user_id and actid should be the Zebu account ID
                actid=self.actid,
                susertoken=self.susertoken,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=self._on_open,
            )

            if self.ws_client.connect():
                self.connected = True
                self.reconnect_attempts = 0
                self.logger.info("Reconnected successfully")
            else:
                self.logger.error("Reconnection failed")

        except Exception as e:
            self.logger.error(f"Reconnection error: {e}")

    def _resubscribe_all(self):
        """Resubscribe to all active subscriptions after reconnect"""
        with self.lock:
            # Reset reference counts
            self.ws_subscription_refs = {}

            # Collect unique scrips for each subscription type
            touchline_scrips = set()
            depth_scrips = set()

            for subscription in self.subscriptions.values():
                scrip = subscription["scrip"]
                mode = subscription["mode"]

                # Initialize reference count
                if scrip not in self.ws_subscription_refs:
                    self.ws_subscription_refs[scrip] = {"touchline_count": 0, "depth_count": 0}

                if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
                    if scrip not in touchline_scrips:
                        touchline_scrips.add(scrip)
                    self.ws_subscription_refs[scrip]["touchline_count"] += 1
                elif mode == Config.MODE_DEPTH:
                    if scrip not in depth_scrips:
                        depth_scrips.add(scrip)
                    self.ws_subscription_refs[scrip]["depth_count"] += 1

            # Resubscribe in batches
            if touchline_scrips:
                scrip_list = "#".join(touchline_scrips)
                self.ws_client.subscribe_touchline(scrip_list)
                self.logger.info(
                    f"Resubscribed to {len(touchline_scrips)} touchline scrips with total {sum(self.ws_subscription_refs[s]['touchline_count'] for s in touchline_scrips)} subscriptions"
                )

            if depth_scrips:
                scrip_list = "#".join(depth_scrips)
                self.ws_client.subscribe_depth(scrip_list)
                self.logger.info(
                    f"Resubscribed to {len(depth_scrips)} depth scrips with total {sum(self.ws_subscription_refs[s]['depth_count'] for s in depth_scrips)} subscriptions"
                )

    def unsubscribe_all(self) -> dict[str, Any]:
        """Unsubscribe from all active data streams without disconnecting
        the WebSocket. Mirrors broker/shoonya/streaming/shoonya_adapter.py's
        unsubscribe_all() -- same Noren-family reconnect cost problem: every
        full disconnect+reconnect re-runs the auth handshake, and pages that
        poll/re-subscribe repeatedly (Option Chain, Max Pain, IV Smile) were
        seeing the connection torn down and rebuilt on every brief gap
        between the last client unsubscribing and the next one subscribing
        (websocket_proxy/server.py's on-last-client-disconnect handler),
        which meant those pages effectively never got a clean run to finish
        rendering. Keeping the socket alive and just clearing subscriptions
        avoids that.
        """
        try:
            with self.lock:
                if not self.connected or not self.ws_client:
                    self.logger.warning("Cannot unsubscribe_all: WebSocket not connected")
                    return self._create_error_response("NOT_CONNECTED", "WebSocket not connected")

                touchline_scrips = set()
                depth_scrips = set()
                for subscription in self.subscriptions.values():
                    scrip = subscription["scrip"]
                    mode = subscription["mode"]
                    if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
                        touchline_scrips.add(scrip)
                    elif mode == Config.MODE_DEPTH:
                        depth_scrips.add(scrip)

                subscription_count = len(self.subscriptions)
                self.subscriptions.clear()
                self.token_to_symbol.clear()
                self.ws_subscription_refs.clear()

                ws = self.ws_client

            unsub_errors = []
            if ws and touchline_scrips:
                try:
                    self.logger.info(f"Unsubscribing from {len(touchline_scrips)} touchline scrips")
                    ws.unsubscribe_touchline("#".join(touchline_scrips))
                except Exception as e:
                    self.logger.error(f"Error unsubscribing touchline: {e}")
                    unsub_errors.append(f"touchline: {e}")

            if ws and depth_scrips:
                try:
                    self.logger.info(f"Unsubscribing from {len(depth_scrips)} depth scrips")
                    ws.unsubscribe_depth("#".join(depth_scrips))
                except Exception as e:
                    self.logger.error(f"Error unsubscribing depth: {e}")
                    unsub_errors.append(f"depth: {e}")

            if unsub_errors:
                self.logger.warning(f"Partial unsubscribe_all failure: {unsub_errors}")

            self.market_cache.clear()

            self.logger.info(
                f"Unsubscribed from all {subscription_count} subscriptions. "
                f"WebSocket connection remains active for fast reconnection."
            )

            response_msg = f"Unsubscribed from all {subscription_count} subscriptions. Connection kept alive."
            if unsub_errors:
                response_msg += f" Warnings: {unsub_errors}"

            return self._create_success_response(
                response_msg,
                unsubscribed_count=subscription_count,
                connection_status="active",
            )

        except Exception as e:
            self.logger.error(f"Error in unsubscribe_all: {e}")
            return self._create_error_response("UNSUBSCRIBE_ALL_ERROR", str(e))

    def _on_message(self, ws, message):
        """Handle incoming market data messages"""
        self.logger.debug(f"[RAW_MESSAGE] {message}")

        try:
            data = json.loads(message)
            msg_type = data.get("t")

            # Handle authentication acknowledgment
            if msg_type == Config.MSG_AUTH:
                self.logger.info(f"Authentication response: {data}")
                return

            # Process market data messages
            if msg_type in (
                Config.MSG_TOUCHLINE_FULL,
                Config.MSG_TOUCHLINE_PARTIAL,
                Config.MSG_DEPTH_FULL,
                Config.MSG_DEPTH_PARTIAL,
            ):
                self._process_market_message(data)
            else:
                self.logger.debug(f"Unknown message type {msg_type}: {data}")

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON decode error: {e}, message: {message}")
        except Exception as e:
            self.logger.error(f"Message processing error: {e}", exc_info=True)

    def _process_market_message(self, data: dict[str, Any]) -> None:
        """Process market data messages with better error handling"""
        try:
            msg_type = data.get("t")
            token = data.get("tk")

            if not self._is_valid_market_message(msg_type, token):
                return

            symbol, exchange = self._get_symbol_info(token)
            if not symbol:
                return

            matching_subscriptions = self._find_matching_subscriptions(token)

            for subscription in matching_subscriptions:
                if self._should_process_message(msg_type, subscription["mode"]):
                    self._process_subscription_message(data, subscription, symbol, exchange)

        except Exception as e:
            self.logger.error(f"Message processing error: {e}")

    def _is_valid_market_message(self, msg_type: str, token: str) -> bool:
        """Validate market message"""
        return msg_type and token and token in self.token_to_symbol

    def _get_symbol_info(self, token: str) -> tuple:
        """Get symbol and exchange from token"""
        return self.token_to_symbol.get(token, (None, None))

    def _find_matching_subscriptions(self, token: str) -> list[dict]:
        """Find all subscriptions matching the token"""
        with self.lock:
            return [sub for sub in self.subscriptions.values() if sub["token"] == token]

    def _should_process_message(self, msg_type: str, mode: int) -> bool:
        """Determine if message should be processed for given mode"""
        touchline_messages = {Config.MSG_TOUCHLINE_FULL, Config.MSG_TOUCHLINE_PARTIAL}
        depth_messages = {Config.MSG_DEPTH_FULL, Config.MSG_DEPTH_PARTIAL}

        if mode in [Config.MODE_LTP, Config.MODE_QUOTE]:
            return msg_type in touchline_messages
        elif mode == Config.MODE_DEPTH:
            return msg_type in depth_messages

        return False

    def _process_subscription_message(
        self, data: dict, subscription: dict, symbol: str, exchange: str
    ) -> None:
        """Process message for a specific subscription"""
        mode = subscription["mode"]
        msg_type = data.get("t")

        # Normalize data
        normalized_data = self._normalize_market_data(data, msg_type, mode)
        normalized_data.update(
            {"symbol": symbol, "exchange": exchange, "timestamp": int(time.time() * 1000)}
        )

        # Create topic and publish
        mode_str = {Config.MODE_LTP: "LTP", Config.MODE_QUOTE: "QUOTE", Config.MODE_DEPTH: "DEPTH"}[
            mode
        ]
        topic = f"{exchange}_{symbol}_{mode_str}"

        # Get client count for this subscription
        client_count = subscription.get("client_count", 1)

        self.logger.debug(
            f"[PUBLISH] Publishing {mode_str} data for {symbol} on topic: {topic}, ZMQ port: {self.zmq_port}, client_count: {client_count}"
        )

        # Debug: Check if data is actually being sent
        try:
            # Track published topics
            if not hasattr(self, "_published_topics"):
                self._published_topics = set()

            if topic not in self._published_topics:
                self.logger.info(f"[PUBLISH] First publish for topic: {topic}")
                self._published_topics.add(topic)

            # Publish once - the ZMQ PUB/SUB pattern will deliver to all subscribers
            # The issue is not here but in how subscriptions are found
            self.publish_market_data(topic, normalized_data)

            # Log client count for debugging
            if client_count > 1:
                self.logger.debug(
                    f"[PUBLISH] Published to topic {topic} for {client_count} clients"
                )
        except Exception as e:
            self.logger.error(f"[PUBLISH] Failed to publish data: {e}")

    def _normalize_market_data(
        self, data: dict[str, Any], msg_type: str, mode: int
    ) -> dict[str, Any]:
        """Normalize market data based on mode with improved structure"""
        token = data.get("tk")
        if token:
            # Use cache to handle partial updates
            data = self.market_cache.update(token, data)

        # Get mode-specific normalizer
        normalizer = self.normalizers.get(mode)
        if not normalizer:
            self.logger.error(f"No normalizer found for mode {mode}")
            return {}

        return normalizer.normalize(data, msg_type)

    def get_market_data_cache_stats(self) -> dict[str, Any]:
        """Get market data cache statistics"""
        return self.market_cache.get_stats()

    def clear_market_data_cache(self, token: str = None) -> None:
        """Clear market data cache"""
        self.market_cache.clear(token)


# Utility functions
def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float with default"""
    if value is None or value == "" or value == "-":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int with default"""
    if value is None or value == "" or value == "-":
        return default
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return default
