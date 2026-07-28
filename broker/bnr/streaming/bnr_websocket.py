"""
Bnr WebSocket Client Implementation
Handles connection to Bnr's market data streaming API
Based on Noren WebSocket API (same as Flattrade)
"""

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Dict, Optional

import websocket


class BnrWebSocket:
    """Bnr WebSocket client for real-time market data"""

    # Connection constants
    # Verified 2026-07-17 by probing prime.bnrsecurities.com directly:
    # - wss://prime.bnrsecurities.com/NorenStream/NorenWS (the URL documented
    #   for the generic OAuth Noren Mobile Client API) returns a hard nginx
    #   404 -- that route simply isn't mounted on BNR's server.
    # - wss://prime.bnrsecurities.com/NorenWSAPI/ (the classic Noren path,
    #   same family as Zebu/Shoonya) accepts the connection AND, when sent
    #   the OAuth-style connect payload (t:"a"/accesstoken -- BNR's REST auth
    #   is OAuth-based per broker/bnr/api/auth_api.py), returns
    #   {"t":"ak","s":"OK"}. The classic connect payload (t:"c"/susertoken)
    #   on this same path was rejected with {"t":"ck","s":"NOT_OK"}. So BNR
    #   mounts OAuth-style auth semantics on the classic URL path -- a
    #   hybrid not covered by either generic Noren doc set.
    WS_URL = "wss://prime.bnrsecurities.com/NorenWSAPI/"
    CONNECTION_TIMEOUT = 15
    THREAD_JOIN_TIMEOUT = 5

    # Heartbeat constants
    HEARTBEAT_INTERVAL = 30
    HEARTBEAT_TIMEOUT = 120
    PING_INTERVAL = 30
    PING_TIMEOUT = 10
    HEARTBEAT_JOIN_TIMEOUT = 3

    # Message types (OAuth WebSocket API)
    MSG_TYPE_CONNECT = "a"
    MSG_TYPE_HEARTBEAT = "h"
    MSG_TYPE_AUTH_ACK = "ak"
    MSG_TYPE_TOUCHLINE_SUB = "t"
    MSG_TYPE_TOUCHLINE_UNSUB = "u"
    MSG_TYPE_DEPTH_SUB = "d"
    MSG_TYPE_DEPTH_UNSUB = "ud"

    # Authentication response
    AUTH_SUCCESS = "OK"

    MAX_SCRIPS_PER_BATCH = 100
    SUBSCRIPTION_DELAY = 0.05
    SUBSCRIPTION_RETRY_DELAY = 0.5

    def __init__(
        self,
        user_id: str,
        actid: str,
        susertoken: str,
        on_message: Callable | None = None,
        on_error: Callable | None = None,
        on_close: Callable | None = None,
        on_open: Callable | None = None,
    ):
        """
        Initialize Bnr WebSocket client

        Args:
            user_id: User ID for authentication
            actid: Account ID for authentication
            susertoken: Session token for authentication
            on_message: Callback for incoming messages
            on_error: Callback for connection errors
            on_close: Callback for connection close
            on_open: Callback for connection open
        """
        # Authentication credentials
        self.user_id = user_id
        self.actid = actid
        self.susertoken = susertoken

        # Connection state
        self.ws = None
        self.ws_thread = None
        self.running = False
        self.connected = False

        # Callbacks
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.on_open = on_open

        # Heartbeat management
        self._heartbeat_thread = None
        self._last_message_time = None
        self._heartbeat_lock = threading.Lock()

        # Serializes every ws.send() call against every other one. Without
        # this, the app-level heartbeat thread (_send_heartbeat, every 30s)
        # and the subscribe/unsubscribe/auth callers (main adapter thread)
        # can both write to the same underlying socket concurrently -- two
        # heartbeat mechanisms plus arbitrary app writes, unsynchronized on
        # one socket. That race corrupts the outgoing frame stream, which
        # the broker's Noren server responds to by dropping the raw TCP
        # connection ("WebSocket closed: None - None" -- no status/message,
        # i.e. not a graceful close) roughly every 30-60s, wiping the tick
        # cache and subscriptions on every cycle. Plain thread-safety bug in
        # websocket-client usage (see broker/zebu/streaming/zebu_websocket.py
        # for the same fix and full analysis), not a broker API limit.
        self._send_lock = threading.Lock()

        self._pending_subscriptions: list[tuple[str, str]] = []
        self._subscription_lock = threading.Lock()
        self._subscription_thread: threading.Thread | None = None

        # Logging
        self.logger = logging.getLogger("bnr_websocket")

    def connect(self) -> bool:
        """
        Establish WebSocket connection with authentication

        Returns:
            bool: True if connection successful, False otherwise
        """
        if self.running:
            self.logger.warning("Already connected or connecting")
            return True

        try:
            self._initialize_connection()
            return self._wait_for_connection()
        except Exception as e:
            self.logger.error(f"Connection error: {e}")
            self.stop()
            return False

    def _initialize_connection(self) -> None:
        """Initialize WebSocket connection and start thread"""
        self.running = True

        self.ws = websocket.WebSocketApp(
            self.WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        self.ws_thread = threading.Thread(target=self._run_websocket, daemon=True)
        self.ws_thread.start()

    def _wait_for_connection(self) -> bool:
        """
        Wait for WebSocket connection to be established

        Returns:
            bool: True if connected within timeout, False otherwise
        """
        start_time = time.time()

        while time.time() - start_time < self.CONNECTION_TIMEOUT:
            if self.connected:
                self.logger.info("WebSocket connected successfully")
                return True
            time.sleep(0.1)

        self.logger.error("Connection timeout")
        self.stop()
        return False

    def _run_websocket(self) -> None:
        """Run the WebSocket connection with proper error handling"""
        try:
            # ping_interval=0 disables websocket-client's own automatic
            # WebSocket-protocol ping -- we already run an app-level Noren
            # heartbeat that the broker's server actually expects/
            # acknowledges. Running both meant two unsynchronized writers
            # could hit the same socket at once. See _send_lock above.
            self.ws.run_forever(ping_interval=0)
        except Exception as e:
            self.logger.error(f"WebSocket run error: {e}")
        finally:
            self._cleanup_connection_state()

    def _cleanup_connection_state(self) -> None:
        """Clean up connection state"""
        self.connected = False
        self._stop_heartbeat()

    def stop(self) -> None:
        """Stop the WebSocket connection and cleanup resources"""
        self.logger.info("Stopping WebSocket connection")

        self.running = False
        self.connected = False

        self._close_websocket()
        self._wait_for_thread_completion()
        self._stop_heartbeat()

        subscription_thread = self._subscription_thread
        if subscription_thread and subscription_thread.is_alive():
            subscription_thread.join(timeout=self.THREAD_JOIN_TIMEOUT)
            if subscription_thread.is_alive():
                self.logger.warning("Subscription worker thread did not stop in time")
        self._subscription_thread = None

    def _close_websocket(self) -> None:
        """Close WebSocket connection"""
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                self.logger.error(f"Error closing WebSocket: {e}")
            finally:
                self.ws = None

    def _wait_for_thread_completion(self) -> None:
        """Wait for WebSocket thread to complete"""
        ws_thread = self.ws_thread
        if ws_thread and ws_thread.is_alive():
            ws_thread.join(timeout=self.THREAD_JOIN_TIMEOUT)
            if ws_thread.is_alive():
                self.logger.warning("WebSocket thread did not terminate within timeout")
        self.ws_thread = None

    # WebSocket Event Handlers
    def _on_open(self, ws) -> None:
        """Handle WebSocket connection open event"""
        self.connected = True
        self._update_last_message_time()

        self.logger.info("WebSocket connection opened, sending authentication")

        if self._send_authentication():
            self._start_heartbeat()
            self._call_external_callback(self.on_open, ws)

    def _send_authentication(self) -> bool:
        """
        Send authentication message to server

        Returns:
            bool: True if authentication sent successfully, False otherwise
        """
        auth_msg = {
            "t": self.MSG_TYPE_CONNECT,
            "uid": self.user_id,
            "actid": self.actid,
            "source": "API",
            "accesstoken": self.susertoken,
        }

        # Log the authentication message for debugging (mask the token)
        debug_msg = auth_msg.copy()
        token_val = debug_msg.get("accesstoken", "")
        if token_val:
            debug_msg["accesstoken"] = (
                token_val[:10] + "..." if len(token_val) > 10 else "***"
            )
        self.logger.info(f"Sending auth message: {debug_msg}")

        try:
            with self._send_lock:
                self.ws.send(json.dumps(auth_msg))
            self.logger.info("Authentication message sent")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send authentication: {e}")
            return False

    def _on_message(self, ws, message: str) -> None:
        """Handle incoming WebSocket messages"""
        self._update_last_message_time()

        if self._handle_internal_message(message):
            return

        self._call_external_callback(self.on_message, ws, message)

    def _handle_internal_message(self, message: str) -> bool:
        """
        Handle internal messages (auth, heartbeat)

        Args:
            message: Incoming message string

        Returns:
            bool: True if message was handled internally, False otherwise
        """
        try:
            data = json.loads(message)
            msg_type = data.get("t")

            if msg_type == self.MSG_TYPE_AUTH_ACK:
                return self._handle_auth_response(data)
            elif msg_type == self.MSG_TYPE_HEARTBEAT:
                self.logger.debug("Received heartbeat response")
                return True

        except (json.JSONDecodeError, KeyError):
            # Not a JSON message or doesn't have expected structure
            pass

        return False

    def _handle_auth_response(self, data: dict[str, Any]) -> bool:
        """
        Handle authentication response

        Args:
            data: Authentication response data

        Returns:
            bool: True (message handled)
        """
        if data.get("s", "").lower() == self.AUTH_SUCCESS.lower():
            self.logger.info("Authentication successful")
        else:
            self.logger.error(f"Authentication failed: {data}")

        return True

    def _on_error(self, ws, error) -> None:
        """Handle WebSocket connection errors"""
        self.logger.error(f"WebSocket error: {error}")
        self._call_external_callback(self.on_error, ws, error)

    def _on_close(self, ws, close_status_code: int | None, close_msg: str | None) -> None:
        """Handle WebSocket connection close event"""
        self.connected = False
        self.logger.info(f"WebSocket closed: {close_status_code} - {close_msg}")

        self._stop_heartbeat()
        self._call_external_callback(self.on_close, ws, close_status_code, close_msg)

    def _call_external_callback(self, callback: Callable | None, *args) -> None:
        """
        Safely call external callback with error handling

        Args:
            callback: Callback function to call
            *args: Arguments to pass to callback
        """
        if callback:
            try:
                callback(*args)
            except Exception as e:
                self.logger.error(f"Error in external callback: {e}")

    # Heartbeat Management
    def _update_last_message_time(self) -> None:
        """Update the timestamp of the last received message"""
        with self._heartbeat_lock:
            self._last_message_time = time.time()

    def _start_heartbeat(self) -> None:
        """Start heartbeat monitoring thread"""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        self._heartbeat_thread = threading.Thread(target=self._heartbeat_worker, daemon=True)
        self._heartbeat_thread.start()
        self.logger.debug("Heartbeat thread started")

    def _stop_heartbeat(self) -> None:
        """Stop heartbeat monitoring thread and wait for it to terminate"""
        hb_thread = self._heartbeat_thread
        if hb_thread and hb_thread.is_alive():
            self.logger.debug("Waiting for heartbeat thread to stop")
            hb_thread.join(timeout=self.HEARTBEAT_JOIN_TIMEOUT)
            if hb_thread.is_alive():
                self.logger.warning("Heartbeat thread did not terminate within timeout")
        self._heartbeat_thread = None

    def _heartbeat_worker(self) -> None:
        """Heartbeat worker thread - sends periodic heartbeats and monitors connection"""
        while self.running and self.connected:
            try:
                time.sleep(self.HEARTBEAT_INTERVAL)

                if self.running and self.connected:
                    if not self._send_heartbeat():
                        break

                    if not self._check_connection_health():
                        break

            except Exception as e:
                self.logger.error(f"Heartbeat worker error: {e}")
                break

    def _send_heartbeat(self) -> bool:
        """
        Send heartbeat message to server

        Returns:
            bool: True if heartbeat sent successfully, False otherwise
        """
        if not self.ws:
            return False

        try:
            heartbeat_msg = {"t": self.MSG_TYPE_HEARTBEAT}
            with self._send_lock:
                self.ws.send(json.dumps(heartbeat_msg))
            self.logger.debug("Sent heartbeat")
            return True
        except Exception as e:
            self.logger.error(f"Heartbeat send error: {e}")
            return False

    def _check_connection_health(self) -> bool:
        """
        Check connection health based on last message timestamp

        Returns:
            bool: True if connection is healthy, False if timed out
        """
        with self._heartbeat_lock:
            if self._last_message_time:
                time_since_message = time.time() - self._last_message_time
                if time_since_message > self.HEARTBEAT_TIMEOUT:
                    self.logger.error("Connection timeout - no messages received")
                    self._close_websocket()
                    return False

        return True

    # Subscription Management
    def subscribe_touchline(self, scrip_list: str) -> bool:
        """
        Subscribe to touchline data for complete quote information

        Args:
            scrip_list: Comma or hash-separated list of scrips

        Returns:
            bool: True if subscription sent successfully, False otherwise
        """
        return self._send_subscription_message(
            self.MSG_TYPE_TOUCHLINE_SUB, scrip_list, "touchline subscription"
        )

    def unsubscribe_touchline(self, scrip_list: str) -> bool:
        """
        Unsubscribe from touchline data

        Args:
            scrip_list: Comma or hash-separated list of scrips

        Returns:
            bool: True if unsubscription sent successfully, False otherwise
        """
        return self._send_subscription_message(
            self.MSG_TYPE_TOUCHLINE_UNSUB, scrip_list, "touchline unsubscription"
        )

    def subscribe_depth(self, scrip_list: str) -> bool:
        """
        Subscribe to market depth data

        Args:
            scrip_list: Comma or hash-separated list of scrips

        Returns:
            bool: True if subscription sent successfully, False otherwise
        """
        return self._send_subscription_message(
            self.MSG_TYPE_DEPTH_SUB, scrip_list, "depth subscription"
        )

    def unsubscribe_depth(self, scrip_list: str) -> bool:
        """
        Unsubscribe from market depth data

        Args:
            scrip_list: Comma or hash-separated list of scrips

        Returns:
            bool: True if unsubscription sent successfully, False otherwise
        """
        return self._send_subscription_message(
            self.MSG_TYPE_DEPTH_UNSUB, scrip_list, "depth unsubscription"
        )

    # Batched subscription API — accepts a list of scrips, queues them, and
    # drains the queue from a single worker thread that chunks large lists
    # into MAX_SCRIPS_PER_BATCH-sized '#'-separated messages with a small
    # SUBSCRIPTION_DELAY between sends. Mirrors
    # broker/shoonya/streaming/shoonya_websocket.py's batched API.
    def subscribe_touchline_scrips(self, scrips: list[str]) -> None:
        """Queue touchline subscriptions for batched sending"""
        self._enqueue_subscriptions(self.MSG_TYPE_TOUCHLINE_SUB, scrips)

    def unsubscribe_touchline_scrips(self, scrips: list[str]) -> None:
        """Queue touchline unsubscriptions for batched sending"""
        self._enqueue_subscriptions(self.MSG_TYPE_TOUCHLINE_UNSUB, scrips)

    def subscribe_depth_scrips(self, scrips: list[str]) -> None:
        """Queue depth subscriptions for batched sending"""
        self._enqueue_subscriptions(self.MSG_TYPE_DEPTH_SUB, scrips)

    def unsubscribe_depth_scrips(self, scrips: list[str]) -> None:
        """Queue depth unsubscriptions for batched sending"""
        self._enqueue_subscriptions(self.MSG_TYPE_DEPTH_UNSUB, scrips)

    def _enqueue_subscriptions(self, msg_type: str, scrips: list[str]) -> None:
        """Append (msg_type, scrip) entries to the pending queue and ensure
        the worker thread is running."""
        if not scrips:
            return

        with self._subscription_lock:
            for scrip in scrips:
                if scrip:
                    self._pending_subscriptions.append((msg_type, scrip))

            if self._subscription_thread and self._subscription_thread.is_alive():
                return

            self._subscription_thread = threading.Thread(
                target=self._process_pending_subscriptions,
                daemon=True,
                name="BnrWSSubWorker",
            )
            self._subscription_thread.start()

    def _process_pending_subscriptions(self) -> None:
        """Drain the pending queue, grouping consecutive same-type entries
        into batches of up to MAX_SCRIPS_PER_BATCH scrips, '#'-joined into
        a single WS message. Sleeps SUBSCRIPTION_DELAY between batches."""
        consecutive_failures = 0

        while self.running:
            if not self.connected:
                consecutive_failures += 1
                if consecutive_failures > 6:
                    self.logger.error(
                        "Subscription worker giving up — no connection after retries; "
                        "dropping pending subscription batch"
                    )
                    with self._subscription_lock:
                        self._pending_subscriptions.clear()
                        self._subscription_thread = None
                    return
                time.sleep(min(self.SUBSCRIPTION_RETRY_DELAY * consecutive_failures, 10))
                continue

            consecutive_failures = 0

            batch_msg_type: str | None = None
            batch_scrips: list[str] = []

            with self._subscription_lock:
                if not self._pending_subscriptions:
                    self._subscription_thread = None
                    return

                while (
                    self._pending_subscriptions
                    and len(batch_scrips) < self.MAX_SCRIPS_PER_BATCH
                ):
                    msg_type, scrip = self._pending_subscriptions[0]
                    if batch_msg_type is None:
                        batch_msg_type = msg_type
                    elif msg_type != batch_msg_type:
                        break
                    batch_scrips.append(scrip)
                    self._pending_subscriptions.pop(0)

            if batch_msg_type and batch_scrips:
                self._send_subscription_message(
                    batch_msg_type, "#".join(batch_scrips), f"batch({len(batch_scrips)})"
                )

            time.sleep(self.SUBSCRIPTION_DELAY)

    def _send_subscription_message(
        self, msg_type: str, scrip_list: str, operation_name: str
    ) -> bool:
        """
        Send subscription/unsubscription message

        Args:
            msg_type: Message type for the operation
            scrip_list: List of scrips to subscribe/unsubscribe
            operation_name: Human-readable operation name for logging

        Returns:
            bool: True if message sent successfully, False otherwise
        """
        message_dict = {"t": msg_type, "k": scrip_list}
        return self._send_message(message_dict, operation_name)

    def _send_message(self, message_dict: dict[str, Any], operation_name: str) -> bool:
        """
        Send message with comprehensive error handling and validation

        Args:
            message_dict: Message data to send
            operation_name: Human-readable operation name for logging

        Returns:
            bool: True if message sent successfully, False otherwise
        """
        if not self._validate_connection_state(operation_name):
            return False

        try:
            message_json = json.dumps(message_dict)
            with self._send_lock:
                self.ws.send(message_json)
            self.logger.debug(f"Sent {operation_name}: {message_dict}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to send {operation_name}: {e}")
            return False

    def _validate_connection_state(self, operation_name: str) -> bool:
        """
        Validate that connection is ready for sending messages

        Args:
            operation_name: Operation name for logging

        Returns:
            bool: True if connection is ready, False otherwise
        """
        if not self.ws:
            self.logger.warning(f"Cannot send {operation_name}: WebSocket not initialized")
            return False

        if not self.connected:
            self.logger.warning(f"Cannot send {operation_name}: not connected")
            return False

        return True

    # Utility Methods
    def is_connected(self) -> bool:
        """
        Check if WebSocket is currently connected

        Returns:
            bool: True if connected, False otherwise
        """
        return self.connected and self.running

    def get_connection_info(self) -> dict[str, Any]:
        """
        Get connection information for debugging

        Returns:
            Dict: Connection state information
        """
        return {
            "connected": self.connected,
            "running": self.running,
            "user_id": self.user_id,
            "actid": self.actid,
            "ws_url": self.WS_URL,
            "last_message_time": self._last_message_time,
            "heartbeat_thread_alive": self._heartbeat_thread.is_alive()
            if self._heartbeat_thread
            else False,
            "ws_thread_alive": self.ws_thread.is_alive() if self.ws_thread else False,
        }
