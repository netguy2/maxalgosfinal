"""
Sequential multi-broker order fan-out.

Fans a single order/basket-order request out to several CONNECTED brokers
(see database/auth_db.py's AuthBrokerSession), one at a time, reusing the
existing single-broker order services completely unmodified:

    - services/place_order_service.py::place_order(..., auth_token=, broker=)
    - services/basket_order_service.py::process_basket_order_with_auth(...)

"Sequential" is a hard requirement, not a performance choice: every broker
module reads credentials via os.getenv (patched in app.py to resolve
per-request), which is process-wide state, not per-broker. Two brokers'
credentials can never both be "active" at the same instant safely within
ONE request. utils.broker_context.broker_credential_context scopes the
override to this request's own contextvars.Context (see that module's
docstring - no process-wide lock is involved, so this never stalls other
concurrent requests), and this loop calls the existing order-placement
functions once per broker, one at a time.

Nothing about single-broker order placement changes: this module is purely
additive, called only from the new multi-broker order UI/endpoint.
"""

from typing import Any

from database.auth_db import get_broker_session, get_username_by_apikey
from utils.broker_context import broker_credential_context
from utils.logging import get_logger

logger = get_logger(__name__)


def place_order_multi(
    order_data: dict[str, Any], api_key: str, brokers: list[str]
) -> tuple[bool, dict[str, Any], int]:
    """Place the same order on each of `brokers`, one at a time.

    Returns (overall_success, {"status": ..., "results": [...]}, status_code).
    overall_success is True only if every broker succeeded; per-broker
    results are always returned so a partial failure is visible to the
    caller (mirrors basket_order_service's existing "partial success"
    result shape).
    """
    from services.place_order_service import place_order

    username = get_username_by_apikey(api_key)
    if not username:
        return False, {"status": "error", "message": "Invalid maxalgos apikey"}, 403

    if not brokers:
        return False, {"status": "error", "message": "At least one broker is required"}, 400

    results = []
    for broker in brokers:
        session = get_broker_session(username, broker)
        if not session:
            results.append(
                {"broker": broker, "status": "error", "message": f"Not connected to {broker}"}
            )
            continue

        auth_token, _feed_token, _user_id = session
        with broker_credential_context(username, broker):
            # emit_event=True: each broker's fill/reject still shows up in the
            # normal order-event stream (order book, socket events), same as
            # any single-broker order today.
            #
            # We have a real api_key here (this is a REST-API-triggered fan-out),
            # so it's kept on the request for logging/audit even though
            # place_order() no longer requires apikey on the auth_token+broker
            # direct-call path (see place_order_service.validate_order_data's
            # require_apikey parameter).
            success, response, _status = place_order(
                {**order_data, "apikey": api_key}, auth_token=auth_token, broker=broker
            )
        # response already carries its own "status" key from place_order();
        # spread first, then set broker/status explicitly so our computed
        # `success` (the authoritative signal) always wins, never silently
        # overridden by the spread.
        results.append({**response, "broker": broker, "status": "success" if success else "error"})

    overall_success = all(r["status"] == "success" for r in results)
    return overall_success, {"status": "success" if overall_success else "partial", "results": results}, 200


def place_basket_order_multi(
    basket_data: dict[str, Any], api_key: str, brokers: list[str]
) -> tuple[bool, dict[str, Any], int]:
    """Place the same basket of orders on each of `brokers`, one at a time.

    Each broker's basket is placed via the existing, unmodified
    process_basket_order_with_auth - only the credential resolution
    (which broker's token/env is active) is serialized across brokers.
    """
    from services.basket_order_service import process_basket_order_with_auth

    username = get_username_by_apikey(api_key)
    if not username:
        return False, {"status": "error", "message": "Invalid maxalgos apikey"}, 403

    if not brokers:
        return False, {"status": "error", "message": "At least one broker is required"}, 400

    per_broker_results = []
    for broker in brokers:
        session = get_broker_session(username, broker)
        if not session:
            per_broker_results.append(
                {"broker": broker, "status": "error", "message": f"Not connected to {broker}"}
            )
            continue

        auth_token, _feed_token, _user_id = session
        basket_with_key = {**basket_data, "apikey": api_key}
        with broker_credential_context(username, broker):
            success, response, _status = process_basket_order_with_auth(
                basket_with_key, auth_token, broker, basket_with_key
            )
        per_broker_results.append(
            {**response, "broker": broker, "status": "success" if success else "error"}
        )

    overall_success = all(r["status"] == "success" for r in per_broker_results)
    return (
        overall_success,
        {"status": "success" if overall_success else "partial", "results": per_broker_results},
        200,
    )
