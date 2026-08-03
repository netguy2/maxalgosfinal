import copy
import importlib
from typing import Any, Dict, Optional, Tuple

from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode
from events import AnalyzerErrorEvent, GTTFailedEvent, GTTPlacedEvent
from utils.event_bus import bus
from utils.logging import get_logger

logger = get_logger(__name__)

API_TYPE = "placegttorder"


def emit_analyzer_error(request_data: dict[str, Any], error_message: str) -> dict[str, Any]:
    """Publish an analyzer error event and return the error response dict."""
    error_response = {"mode": "analyze", "status": "error", "message": error_message}

    analyzer_request = request_data.copy()
    if "apikey" in analyzer_request:
        del analyzer_request["apikey"]
    analyzer_request["api_type"] = API_TYPE

    bus.publish(AnalyzerErrorEvent(
        mode="analyze", api_type=API_TYPE,
        request_data=analyzer_request, response_data=error_response,
        error_message=error_message,
    ))

    return error_response


def import_broker_gtt_module(broker_name: str) -> Any | None:
    """Dynamically import the broker-specific GTT API module."""
    try:
        return importlib.import_module(f"broker.{broker_name}.api.gtt_api")
    except ImportError as error:
        logger.error(f"Error importing GTT module for broker '{broker_name}': {error}")
        return None


def place_gtt_order_with_auth(
    order_data: dict[str, Any],
    auth_token: str,
    broker: str,
    original_data: dict[str, Any],
) -> tuple[bool, dict[str, Any], int]:
    """Place a GTT using the provided broker auth token."""
    order_request_data = copy.deepcopy(original_data)
    order_request_data.pop("apikey", None)
    api_key = original_data.get("apikey", "")

    # Analyze (sandbox) mode: not wired yet — clean 501 until Phase 3.
    if get_analyze_mode():
        error_response = {
            "mode": "analyze",
            "status": "error",
            "message": "Sandbox GTT support not yet implemented",
        }
        return False, error_response, 501

    # Kill-switch gate, after the analyze/sandbox branch above.
    # NOTE: this blocks PLACEMENT of new GTTs only. GTT orders already resting
    # at the broker are unaffected and can still trigger days later -- see the
    # "resting GTT orders survive the kill switch" backlog item.
    from services.order_gate import check_order_allowed

    allowed, gate_error, gate_status = check_order_allowed(
        "GTT order placement", api_key=api_key
    )
    if not allowed:
        bus.publish(GTTFailedEvent(
            mode="live", api_type=API_TYPE,
            symbol=order_data.get("symbol", ""), exchange=order_data.get("exchange", ""),
            trigger_type=order_data.get("trigger_type", ""),
            error_message=gate_error["message"],
            request_data=order_request_data, response_data=gate_error, api_key=api_key,
        ))
        return False, gate_error, gate_status

    # Pre-trade RMS gate (Annexure 4 items 1/2/3/5). Quantity/value checks
    # apply the same as any other order; the price-band check is a no-op
    # here in practice since GTT orders carry a trigger_price, not a LIMIT
    # `price` field meant to fire against current LTP -- see
    # services/risk_gate.py::_check_price_band's pricetype guard.
    from services.risk_gate import check_pre_trade_risk
    from utils.socket_scope import username_from_api_key

    risk_username = username_from_api_key(api_key)
    risk_allowed, risk_error, risk_status = check_pre_trade_risk(
        orders=[order_data], username=risk_username, context="GTT order placement"
    )
    if not risk_allowed:
        bus.publish(GTTFailedEvent(
            mode="live", api_type=API_TYPE,
            symbol=order_data.get("symbol", ""), exchange=order_data.get("exchange", ""),
            trigger_type=order_data.get("trigger_type", ""),
            error_message=risk_error["message"],
            request_data=order_request_data, response_data=risk_error, api_key=api_key,
        ))
        return False, risk_error, risk_status

    # Capability gate: if the broker does not ship a gtt_api module, 501.
    broker_module = import_broker_gtt_module(broker)
    if broker_module is None:
        message = f"GTT orders are not supported for broker '{broker}' yet"
        error_response = {"status": "error", "message": message}
        bus.publish(GTTFailedEvent(
            mode="live", api_type=API_TYPE,
            symbol=order_data.get("symbol", ""), exchange=order_data.get("exchange", ""),
            trigger_type=order_data.get("trigger_type", ""),
            error_message=message,
            request_data=order_request_data, response_data=error_response, api_key=api_key,
        ))
        return False, error_response, 501

    try:
        res, response_data, trigger_id = broker_module.place_gtt_order(order_data, auth_token)
    except Exception as e:
        logger.exception(f"Error in broker_module.place_gtt_order: {e}")
        error_response = {"status": "error", "message": "Failed to place GTT due to internal error"}
        bus.publish(GTTFailedEvent(
            mode="live", api_type=API_TYPE,
            symbol=order_data.get("symbol", ""), exchange=order_data.get("exchange", ""),
            trigger_type=order_data.get("trigger_type", ""),
            error_message=str(e),
            request_data=order_request_data, response_data=error_response, api_key=api_key,
        ))
        return False, error_response, 500

    if res.status == 200 and trigger_id:
        success_response = {"status": "success", "trigger_id": trigger_id}
        # Derive trigger_prices for the event from the flat fields.
        if (order_data.get("trigger_type") or "").upper() == "OCO":
            event_trigger_prices = [
                float(order_data.get("triggerprice_sl") or 0),
                float(order_data.get("triggerprice_tg") or 0),
            ]
        else:
            event_trigger_prices = [float(order_data.get("trigger_price") or 0)]
        bus.publish(GTTPlacedEvent(
            mode="live", api_type=API_TYPE,
            strategy=order_data.get("strategy", ""),
            symbol=order_data.get("symbol", ""), exchange=order_data.get("exchange", ""),
            trigger_type=order_data.get("trigger_type", ""),
            trigger_id=trigger_id,
            trigger_prices=event_trigger_prices,
            request_data=order_request_data, response_data=success_response, api_key=api_key,
        ))
        return True, success_response, 200

    # Broker error messages surface under different keys depending on the
    # broker's API: most use "message", Noren-family brokers (bnr, shoonya,
    # zebu, ...) use "emsg". Check both instead of assuming "message".
    message = "Failed to place GTT"
    if isinstance(response_data, dict):
        message = response_data.get("message") or response_data.get("emsg") or message
    error_response = {"status": "error", "message": message}
    bus.publish(GTTFailedEvent(
        mode="live", api_type=API_TYPE,
        symbol=order_data.get("symbol", ""), exchange=order_data.get("exchange", ""),
        trigger_type=order_data.get("trigger_type", ""),
        error_message=message,
        request_data=order_request_data, response_data=error_response, api_key=api_key,
    ))
    return False, error_response, res.status if res.status != 200 else 500


def place_gtt_order(
    order_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """Place a GTT trigger.

    Supports API-key-based auth (external callers) and direct auth_token+broker
    (internal callers, matches place_order_service pattern).
    """
    original_data = copy.deepcopy(order_data)
    if api_key:
        original_data["apikey"] = api_key
        order_data["apikey"] = api_key

    # Semi-auto / Action Center routing (place-side is queueable per Phase 0.3).
    if api_key and not (auth_token and broker):
        from services.order_router_service import queue_order, should_route_to_pending

        if should_route_to_pending(api_key, API_TYPE):
            return queue_order(api_key, original_data, API_TYPE)

    # API-based auth
    if api_key and not (auth_token and broker):
        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            return False, {"status": "error", "message": "Invalid maxalgos apikey"}, 403
        return place_gtt_order_with_auth(order_data, AUTH_TOKEN, broker_name, original_data)

    # Direct internal call
    if auth_token and broker:
        return place_gtt_order_with_auth(order_data, auth_token, broker, original_data)

    return (
        False,
        {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        },
        400,
    )
