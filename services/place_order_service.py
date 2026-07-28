import copy
import importlib
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
    # Check for missing mandatory fields
    required_fields = REQUIRED_ORDER_FIELDS if require_apikey else [
        f for f in REQUIRED_ORDER_FIELDS if f != "apikey"
    ]
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        return False, None, f"Missing mandatory field(s): {', '.join(missing_fields)}"

    # Validate exchange
    if "exchange" in data and data["exchange"] not in VALID_EXCHANGES:
        return False, None, f"Invalid exchange. Must be one of: {', '.join(VALID_EXCHANGES)}"

    # Convert action to uppercase and validate
    if "action" in data:
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
        ))
        return False, gate_error, gate_status

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
        ))
        return False, error_response, 500

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
            ))

        # Asynchronously verify true order status from broker order book ~1s later.
        # If exchange rejected the order (e.g. RMS Margin Exceeded), this emits
        # red error toasts & drawer notifications to the user automatically.
        try:
            from services.order_verification_helper import async_verify_order_fill

            from utils.socket_scope import username_from_api_key

            async_verify_order_fill(
                auth_token=auth_token,
                broker=broker,
                orderid=str(order_id),
                symbol=order_data.get("symbol", ""),
                action=order_data.get("action", "BUY"),
                strategy=order_data.get("strategy", ""),
                # Resolve explicitly: this order may have come from a
                # headless path (webhook/strategy) with no Flask session,
                # so the api_key is the only reliable owner signal.
                username=username_from_api_key(api_key),
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
        else:
            AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
            if AUTH_TOKEN is None:
                error_response = {"status": "error", "message": "Invalid maxalgos apikey"}
                # Skip logging for invalid API keys to prevent database flooding
                return False, error_response, 403

        return place_order_with_auth(order_data, AUTH_TOKEN, broker_name, original_data, emit_event, prefetched_quote)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return place_order_with_auth(order_data, auth_token, broker, original_data, emit_event, prefetched_quote)

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
