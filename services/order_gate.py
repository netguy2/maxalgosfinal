"""Single definition of "is this order permitted to reach a broker".

Why this module exists
----------------------
Five separate code paths call a broker's order-placement API directly:

    services/place_order_service.py        broker_module.place_order_api
    services/basket_order_service.py       broker_module.place_order_api
    services/split_order_service.py        broker_module.place_order_api
    services/place_smart_order_service.py  broker_module.place_smartorder_api
    services/place_gtt_order_service.py    broker_module.place_gtt_order

Only the first routes through place_order_with_auth. The other four each
reimplement import_broker_module and call the broker themselves, which is how
they silently drifted out of every safety check that lives in
place_order_service. Before this module, the master kill switch stopped
Chartink and Python Strategy Host orders but NOT basket, split, smart, or GTT
orders from the REST API, the Flow no-code builder, or Action Center approvals.

Rather than duplicating the check five times (which is what caused the drift in
the first place), every one of those call sites calls check_order_allowed()
immediately before its broker call. New order paths must do the same.

Placement rule
--------------
Call this AFTER the analyze/sandbox branch, never before. The kill switch
exists to stop real capital from moving; sandbox orders touch no real money, so
blocking them buys no safety and only breaks testing workflows.

Failure semantics
-----------------
Fails OPEN. If the kill-switch flag cannot be read, the order proceeds. A
settings-table fault must not silently halt every strategy platform-wide --
but the resulting state (switch reads ACTIVE in the UI while not enforcing)
is dangerous enough that it must be loud, not just logged. See
services/signal_engine.py::_alert_safety_check_failed for the identical
pattern on the webhook path.
"""

from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


def _alert_gate_failed_open(context: str, error: Exception) -> None:
    """Raise a human-visible alarm when the kill-switch check fails open.

    Best-effort and never raises: alerting must not be able to break order
    placement. Currently just an ERROR-level log; the loud alert channel was
    removed along with the Telegram bot feature. If a replacement alert
    channel is added later, dispatch it here.
    """
    logger.error(
        f"ORDER SAFETY GATE FAILED OPEN for {context}: {error}. "
        "Order was allowed through unguarded -- verify kill switch state manually."
    )


def check_order_allowed(
    context: str = "order", api_key: str | None = None, username: str | None = None
) -> tuple[bool, dict[str, Any] | None, int]:
    """Check whether an order may be sent to a live broker.

    Must be called after the analyze/sandbox branch -- see module docstring.

    Args:
        context: Short description of the calling path (e.g. "basket order"),
            used in logs and alerts to identify which path was blocked.
        api_key: The Max Algos API key the order was placed with, used to
            resolve the owning user when `username` isn't already known.
        username: The order's owner, when the caller already has it.

    The kill switch is PER-USER (see database/settings_db.py). Passing the
    identity through is what keeps User A's emergency stop from blocking
    User B's orders -- previously this read a single global flag, so one
    activation halted live trading for every account on the instance.

    When neither identity can be resolved the order is ALLOWED through: an
    unattributable internal call must not be blocked by some other user's
    kill switch. That matches this module's existing fail-open posture on
    the exception path below.

    Returns:
        (allowed, error_response, status_code). When allowed is True the other
        two are (None, 0) and the caller proceeds. When False, the caller must
        return error_response with status_code and place no order.
    """
    try:
        from database.settings_db import is_kill_switch_active

        resolved = username
        if not resolved and api_key:
            from utils.socket_scope import username_from_api_key

            resolved = username_from_api_key(api_key)

        if not resolved or not is_kill_switch_active(resolved):
            return True, None, 0
    except Exception as exc:
        logger.exception(
            f"Order gate: kill-switch check failed for {context} -- "
            "allowing order through (fail-open)"
        )
        _alert_gate_failed_open(context, exc)
        return True, None, 0

    logger.warning(
        f"Order gate: kill switch is ACTIVE for user '{resolved}'. Blocking {context}."
    )
    return (
        False,
        {
            "status": "error",
            "message": (
                "Kill switch is active. All live order placement is halted. "
                "Deactivate the kill switch to resume trading."
            ),
            "code": "KILL_SWITCH_ACTIVE",
        },
        403,
    )
