import copy
import hashlib
import importlib
import threading
import time
from typing import Any, Dict, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from events import AnalyzerErrorEvent, OrderFailedEvent, OrderPlacedEvent
from restx_api.schemas import OrderSchema
from utils.constants import (
    REQUIRED_ORDER_FIELDS,
    VALID_ACTIONS,
    VALID_EXCHANGES,
    VALID_PRICE_TYPES,
    VALID_PRODUCT_TYPES,
)
from utils.event_bus import bus
from utils.kill_switch import enforce_kill_switch
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Initialize schema
order_schema = OrderSchema()

# --- Duplicate webhook suppression ---
# Webhook platforms (TradingView, Chartink, GoCharting) retry on a slow or
# dropped response, re-delivering an identical payload a few hundred ms to a
# few seconds later. There is no idempotency key in the wire format they
# send, so dedup on a fingerprint of the fields that make an order identical
# and reject an exact repeat that arrives inside a short window. In-process
# dict is fine here for the same reason NullPool is fine for SQLite: this
# runs single-worker (see CLAUDE.md eventlet/-w 1 constraint).
DEDUP_WINDOW_SECONDS = 3.0
_recent_order_fingerprints: dict[str, float] = {}
_recent_order_fingerprints_lock = threading.Lock()


def _order_fingerprint(order_data: dict[str, Any], api_key: str | None) -> str:
    key_fields = (
        api_key or "",
        str(order_data.get("strategy", "")),
        str(order_data.get("symbol", "")),
        str(order_data.get("exchange", "")),
        str(order_data.get("action", "")).upper(),
        str(order_data.get("quantity", "")),
        str(order_data.get("pricetype", "")),
        str(order_data.get("product", "")),
        str(order_data.get("price", "")),
        str(order_data.get("trigger_price", "")),
    )
    return hashlib.sha256("|".join(key_fields).encode()).hexdigest()


def _is_duplicate_order(fingerprint: str) -> bool:
    """Return True and record the fingerprint if it's a fresh submission;
    return True without re-recording if it's a repeat within the window."""
    now = time.monotonic()
    with _recent_order_fingerprints_lock:
        # Opportunistic sweep so the dict doesn't grow unbounded over a long
        # single-worker process lifetime.
        expired = [fp for fp, ts in _recent_order_fingerprints.items()
                   if now - ts > DEDUP_WINDOW_SECONDS]
        for fp in expired:
            del _recent_order_fingerprints[fp]

        last_seen = _recent_order_fingerprints.get(fingerprint)
        if last_seen is not None and (now - last_seen) <= DEDUP_WINDOW_SECONDS:
            return True

        _recent_order_fingerprints[fingerprint] = now
        return False


def import_broker_module(broker_name: str) -> Any | None:
    """
    Dynamically import the broker-specific order API module.

    Args:
        broker_name: Name of the broker

    Returns:
        The imported module or None if import fails
    """
    try:
        module_path = f"broker.{broker_name}.api.order_api"
        broker_module = importlib.import_module(module_path)
        return broker_module
    except ImportError as error:
        logger.error(f"Error importing broker module '{module_path}': {error}")
        return None


def emit_analyzer_error(request_data: dict[str, Any], error_message: str) -> dict[str, Any]:
    """Publish an analyzer error event and return the error response dict."""
    error_response = {"mode": "analyze", "status": "error", "message": error_message}

    analyzer_request = request_data.copy()
    if "apikey" in analyzer_request:
        del analyzer_request["apikey"]
    analyzer_request["api_type"] = "placeorder"

    bus.publish(AnalyzerErrorEvent(
        mode="analyze",
        api_type="placeorder",
        request_data=analyzer_request,
        response_data=error_response,
        error_message=error_message,
    ))

    return error_response


def validate_order_data(
    data: dict[str, Any], require_apikey: bool = True
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """
    Validate order data against required fields and valid values

    Args:
        data: Order data to validate
        require_apikey: Whether "apikey" is a mandatory field. True for every
            external/API-key-authenticated call (the REST API contract).
            False for direct internal calls that already carry a resolved
            auth_token+broker (e.g. signal_engine.py's webhook/deployment
            order placement) -- those have no Max Algos API key to give and
            never had one; requiring it here just to satisfy this same
            shared validator was the root cause of "Missing mandatory
            field(s): apikey" on internally-triggered orders.

    Returns:
        Tuple containing:
        - Success status (bool)
        - Validated order data (dict) or None if validation failed
        - Error message (str) or None if validation succeeded
    """
    # Check for missing mandatory fields. A field that is present but blank
    # (None, "", or whitespace-only -- e.g. an unresolved Flow node variable
    # or a strategy-builder template that substituted an empty string) is
    # just as unusable to the broker as a genuinely absent key, so treat it
    # the same way instead of letting it fall through to the broker call.
    required_fields = REQUIRED_ORDER_FIELDS if require_apikey else [
        f for f in REQUIRED_ORDER_FIELDS if f != "apikey"
    ]
    missing_fields = [
        field for field in required_fields
        if field not in data
        or data[field] is None
        or (isinstance(data[field], str) and data[field].strip() == "")
    ]
    if missing_fields:
        return False, None, f"Missing mandatory field(s): {', '.join(missing_fields)}"

    # Validate exchange
    if "exchange" in data and data["exchange"] not in VALID_EXCHANGES:
        return False, None, f"Invalid exchange. Must be one of: {', '.join(VALID_EXCHANGES)}"

    # Convert action to uppercase and validate. "action" may still reach
    # here as None/blank if it isn't in REQUIRED_ORDER_FIELDS (it is -- this
    # guard is the fallback for callers that mutate required-field lists),
    # so guard the .upper() call rather than assume presence implies a string.
    if data.get("action"):
        data["action"] = data["action"].upper()
        if data["action"] not in VALID_ACTIONS:
            return (
                False,
                None,
                f"Invalid action. Must be one of: {', '.join(VALID_ACTIONS)} (case insensitive)",
            )

    # Validate price type if provided
    if "price_type" in data and data["price_type"] not in VALID_PRICE_TYPES:
        return False, None, f"Invalid price type. Must be one of: {', '.join(VALID_PRICE_TYPES)}"

    # Validate product type if provided
    if "product_type" in data and data["product_type"] not in VALID_PRODUCT_TYPES:
        return (
            False,
            None,
            f"Invalid product type. Must be one of: {', '.join(VALID_PRODUCT_TYPES)}",
        )

    # Validate and deserialize input. OrderSchema.apikey is required=True at
    # the schema level regardless of require_apikey above -- for the direct
    # internal-call path (no apikey to give), supply a schema-only sentinel
    # so .load() doesn't reject the order, then strip it back out so it never
    # reaches the broker call, an event payload, or a log line.
    schema_input = data
    injected_sentinel = False
    if not require_apikey and "apikey" not in data:
        schema_input = {**data, "apikey": "internal-call"}
        injected_sentinel = True

    try:
        order_data = order_schema.load(schema_input)
        if injected_sentinel:
            order_data.pop("apikey", None)
        return True, order_data, None
    except Exception as err:
        return False, None, str(err)


def place_order_with_auth(
    order_data: dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: dict[str, Any],
    emit_event: bool = True,
    prefetched_quote: dict[str, Any] | None = None,
    username: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Place an order using provided auth token.

    Args:
        order_data: Validated order data
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging
        emit_event: Whether to emit socket event (default True, set False for batch orders)
        prefetched_quote: Pre-fetched quote from batch call (optional, sandbox only)
        username: Owning username, for callers on the internal auth_token+broker
            path (e.g. signal_engine.py's webhook/deployment order placement)
            that have no Max Algos api_key to resolve a username from. Passed
            through to every published OrderEvent so socketio_subscriber.py
            can still scope the notification to this user instead of
            silently dropping it (api_key-based callers don't need this --
            api_key alone resolves the room).

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    order_request_data = copy.deepcopy(original_data)
    if "apikey" in order_request_data:
        order_request_data.pop("apikey", None)

    api_key = original_data.get("apikey", "")

    # If in analyze mode, route to sandbox for sandbox trading
    if get_analyze_mode():
        from services.sandbox_service import sandbox_place_order

        if not api_key:
            error_response = {
                "status": "error",
                "message": "API key required for sandbox mode",
                "mode": "analyze",
            }
            return False, error_response, 400

        success, response, status_code = sandbox_place_order(
            order_data, api_key, original_data, prefetched_quote=prefetched_quote
        )

        if emit_event:
            bus.publish(OrderPlacedEvent(
                mode="analyze",
                api_type="placeorder",
                strategy=order_data.get("strategy", ""),
                symbol=order_data.get("symbol", ""),
                exchange=order_data.get("exchange", ""),
                action=order_data.get("action", ""),
                quantity=int(order_data.get("quantity", 0)),
                pricetype=order_data.get("pricetype", ""),
                product=order_data.get("product", ""),
                orderid=response.get("orderid", ""),
                request_data=order_request_data,
                response_data=response,
                api_key=api_key,
                username=username or "",
            ))

        return success, response, status_code

    # Market hours check disabled for testing outside market hours (per user request)
    # exch = order_data.get("exchange", "NSE")
    # from database.market_calendar_db import is_market_open
    # if not is_market_open(exch):
    #     msg = f"Market closed for {exch} (Trading hours: 09:15 AM - 03:30 PM IST)."
    #     error_response = {"status": "error", "message": msg}
    #     return False, error_response, 400

    # Kill-switch gate. Placed after the analyze/sandbox branch above so
    # sandbox orders stay exempt -- the switch exists to stop real capital
    # moving, and blocking paper orders buys no safety. See
    # services/order_gate.py for why this lives in a shared module.
    from services.order_gate import check_order_allowed

    allowed, gate_error, gate_status = check_order_allowed("order placement", api_key=api_key)
    if not allowed:
        bus.publish(OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data=order_request_data,
            response_data=gate_error,
            api_key=api_key,
            strategy=order_data.get("strategy", ""),
            symbol=order_data.get("symbol", ""),
            exchange=order_data.get("exchange", ""),
            error_message=gate_error["message"],
            username=username or "",
        ))
        return False, gate_error, gate_status

    # Pre-trade RMS gate (Annexure 4 items 1/2/3/5) -- quantity/value/price-band
    # limits and the automated runaway/loop breaker. See services/risk_gate.py.
    from services.risk_gate import check_pre_trade_risk
    from utils.socket_scope import username_from_api_key

    risk_username = username or username_from_api_key(api_key)
    risk_allowed, risk_error, risk_status = check_pre_trade_risk(
        orders=[order_data], username=risk_username, context="order placement"
    )
    if not risk_allowed:
        bus.publish(OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data=order_request_data,
            response_data=risk_error,
            api_key=api_key,
            strategy=order_data.get("strategy", ""),
            symbol=order_data.get("symbol", ""),
            exchange=order_data.get("exchange", ""),
            error_message=risk_error["message"],
            username=username or "",
        ))
        return False, risk_error, risk_status

    broker_module = import_broker_module(broker)
    if broker_module is None:
        error_response = {"status": "error", "message": "Broker-specific module not found"}
        bus.publish(OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data=order_request_data,
            response_data=error_response,
            api_key=api_key,
            strategy=order_data.get("strategy", ""),
            symbol=order_data.get("symbol", ""),
            exchange=order_data.get("exchange", ""),
            error_message="Broker-specific module not found",
            username=username or "",
        ))
        return False, error_response, 404

    try:
        res, response_data, order_id = broker_module.place_order_api(order_data, auth_token)
    except Exception as e:
        logger.exception(f"Error in broker_module.place_order_api: {e}")
        error_response = {
            "status": "error",
            "message": "Failed to place order due to internal error",
        }
        bus.publish(OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data=order_request_data,
            response_data=error_response,
            api_key=api_key,
            strategy=order_data.get("strategy", ""),
            symbol=order_data.get("symbol", ""),
            exchange=order_data.get("exchange", ""),
            error_message=str(e),
            username=username or "",
        ))
        return False, error_response, 500

    # A broker module may return res=None deliberately (not a bug) when it
    # aborted BEFORE making any HTTP call -- e.g. broker/zebu and broker/bnr's
    # place_order_api both do this when the trading user ID (uid/actid)
    # can't be resolved, since sending the order without one would either
    # fail broker-side anyway or -- worse -- silently use a stale/wrong
    # cached value. res.status would otherwise raise AttributeError here
    # (None has no .status), turning a clean, already-logged error into an
    # unrelated crash.
    if res is None:
        message = "Failed to place order"
        if isinstance(response_data, dict):
            message = response_data.get("message") or response_data.get("emsg") or message
        error_response = {"status": "error", "message": message}
        bus.publish(OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data=order_request_data,
            response_data=error_response,
            api_key=api_key,
            strategy=order_data.get("strategy", ""),
            symbol=order_data.get("symbol", ""),
            exchange=order_data.get("exchange", ""),
            error_message=message,
            username=username or "",
        ))
        return False, error_response, 400

    # Some brokers (bnr, dhan, dhan_sandbox, flattrade, indmoney, zebu) always
    # return HTTP 200 regardless of whether the broker accepted the order - the
    # real outcome is only visible via order_id (None on failure).
    if res.status == 200 and order_id:
        order_response_data = {"status": "success", "orderid": order_id}

        if api_key:
            from database.auth_db import get_username_by_apikey, record_activity

            username = get_username_by_apikey(api_key)
            if username:
                record_activity(
                    username,
                    "order",
                    "Order Executed",
                    f"{order_data.get('action', '')} {order_data.get('quantity', '')} "
                    f"{order_data.get('symbol', '')} @ {order_data.get('exchange', '')}",
                )

        if emit_event:
            bus.publish(OrderPlacedEvent(
                mode="live",
                api_type="placeorder",
                strategy=order_data.get("strategy", ""),
                symbol=order_data.get("symbol", ""),
                exchange=order_data.get("exchange", ""),
                action=order_data.get("action", ""),
                quantity=int(order_data.get("quantity", 0)),
                pricetype=order_data.get("pricetype", ""),
                product=order_data.get("product", ""),
                orderid=str(order_id),
                request_data=order_request_data,
                response_data=order_response_data,
                api_key=api_key,
                username=username or "",
            ))

        # Asynchronously verify true order status from broker order book ~1s later.
        # If exchange rejected the order (e.g. RMS Margin Exceeded), this emits
        # red error toasts & drawer notifications to the user automatically.
        try:
            from services.order_verification_helper import async_verify_order_fill

            from utils.socket_scope import username_from_api_key

            # Prefer the caller-supplied username (internal auth_token+broker
            # path, e.g. signal_engine.py) over resolving from api_key --
            # that path has no api_key to resolve from at all.
            resolved_username = username or username_from_api_key(api_key)

            async_verify_order_fill(
                auth_token=auth_token,
                broker=broker,
                orderid=str(order_id),
                symbol=order_data.get("symbol", ""),
                action=order_data.get("action", "BUY"),
                strategy=order_data.get("strategy", ""),
                username=resolved_username,
            )
        except Exception as _ve:
            logger.debug(f"Could not queue order fill verification: {_ve}")

        return True, order_response_data, 200
    else:
        # Broker error messages surface under different keys depending on the
        # broker's API: most use "message", Noren-family brokers (bnr, shoonya,
        # zebu, ...) use "emsg". Check both instead of assuming "message".
        message = "Failed to place order"
        if isinstance(response_data, dict):
            message = response_data.get("message") or response_data.get("emsg") or message
        error_response = {"status": "error", "message": message}
        bus.publish(OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data=order_request_data,
            response_data=error_response,
            api_key=api_key,
            strategy=order_data.get("strategy", ""),
            symbol=order_data.get("symbol", ""),
            exchange=order_data.get("exchange", ""),
            error_message=message,
            username=username or "",
        ))
        return False, error_response, res.status if res.status != 200 else 500


@enforce_kill_switch("order")
def place_order(
    order_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
    emit_event: bool = True,
    prefetched_quote: dict[str, Any] | None = None,
    username: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Place an order with the broker.
    Supports both API-based authentication and direct internal calls.

    Args:
        order_data: Order data containing all required fields
        api_key: Max Algos API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)
        emit_event: Whether to emit socket event (default True, set False for batch orders)
        prefetched_quote: Pre-fetched quote from batch call (optional, sandbox only).
            Skips per-order REST API quote fetch when provided.
        username: Owning username for the auth_token+broker internal-call path
            (e.g. signal_engine.py), which has no api_key to resolve a
            notification room from otherwise. Ignored on the api_key path --
            api_key alone is sufficient there.

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(order_data)
    if api_key:
        original_data["apikey"] = api_key
        # Also add apikey to order_data for validation
        order_data["apikey"] = api_key

    # Suppress duplicate webhook deliveries (TradingView/Chartink/GoCharting
    # retry an identical payload on a slow or dropped response). Checked
    # before Action Center routing so a semi-auto duplicate doesn't queue
    # two pending approvals either. Internal calls (auth_token+broker,
    # e.g. signal_engine.py) are exempt -- those aren't webhook retries.
    if not (auth_token and broker):
        fingerprint = _order_fingerprint(order_data, api_key)
        if _is_duplicate_order(fingerprint):
            error_response = {
                "status": "error",
                "message": f"Duplicate order suppressed (identical order received "
                           f"within {DEDUP_WINDOW_SECONDS:.0f}s)",
            }
            logger.warning(
                f"Duplicate order suppressed for symbol={order_data.get('symbol')} "
                f"strategy={order_data.get('strategy')}"
            )
            return False, error_response, 429

    # Check if order should be routed to Action Center (semi-auto mode)
    # Only check for API-based calls, not internal calls
    if api_key and not (auth_token and broker):
        from services.order_router_service import queue_order, should_route_to_pending

        if should_route_to_pending(api_key, "placeorder"):
            return queue_order(api_key, original_data, "placeorder")

    # Validate the order data. apikey is only mandatory on the API-key path --
    # a direct internal call (auth_token+broker already resolved, e.g. from
    # signal_engine.py) has no Max Algos API key to give and never needs one.
    is_direct_internal_call = bool(auth_token and broker)
    is_valid, _, error_message = validate_order_data(
        order_data, require_apikey=not is_direct_internal_call
    )
    if not is_valid:
        if get_analyze_mode():
            return False, emit_analyzer_error(original_data, error_message), 400
        error_response = {"status": "error", "message": error_message}
        safe_request = {k: v for k, v in original_data.items() if k != "apikey"}
        bus.publish(OrderFailedEvent(
            mode="live",
            api_type="placeorder",
            request_data=safe_request,
            response_data=error_response,
            error_message=error_message,
            api_key=api_key or "",
        ))
        return False, error_response, 400

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        requested_broker = order_data.get("broker")
        if requested_broker:
            # Caller asked for a SPECIFIC one of their connected brokers
            # (e.g. a Python strategy passing broker= to place a trade on
            # a non-default account) rather than whichever broker happens
            # to be the primary Auth row for this api_key.
            from database.auth_db import get_broker_session, verify_api_key

            user_id = verify_api_key(api_key)
            session_info = get_broker_session(user_id, requested_broker) if user_id else None
            if not session_info:
                error_response = {
                    "status": "error",
                    "message": f"Broker '{requested_broker}' is not connected for this account",
                }
                return False, error_response, 400
            AUTH_TOKEN, _feed_token, _br_user_id = session_info
            broker_name = requested_broker
            # get_broker_session() already resolved this user's broker-side
            # client code/user_id with proper username+broker scoping. Some
            # broker order_api modules (bnr, zebu) otherwise have to
            # re-derive this by matching auth_token against every stored
            # session for that broker across ALL users -- ambiguous/wrong
            # for a multi-broker or multi-user deployment. Passing it
            # through in order_data lets those modules use it directly
            # instead of re-deriving it unreliably.
            if _br_user_id:
                order_data["_broker_user_id"] = _br_user_id
        else:
            AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                error_response = {"status": "error", "message": "Invalid maxalgos apikey"}
                # Skip logging for invalid API keys to prevent database flooding
                return False, error_response, 403

        return place_order_with_auth(order_data, AUTH_TOKEN, broker_name, original_data, emit_event, prefetched_quote)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return place_order_with_auth(
            order_data, auth_token, broker, original_data, emit_event, prefetched_quote, username=username
        )

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
