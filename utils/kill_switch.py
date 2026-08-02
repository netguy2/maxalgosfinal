"""Kill switch enforcement decorator.

See docs/plans/2026-04-24-kill-switch-implementation-plan.md for the full
design. This module is deliberately tiny -- the actual state lives in
database/settings_db.py (is_kill_switch_active, cached) and the cleanup
orchestration lives in services/kill_switch_service.py. This module is just
the single reusable gate applied to every order-placing service function.
"""

import inspect
from functools import wraps

from database.settings_db import is_kill_switch_active

KILL_SWITCH_ERROR_MESSAGE = (
    "Kill switch is active -- new orders are blocked. Deactivate via the dashboard."
)

KILL_SWITCH_ERROR_CODE = "KILL_SWITCH_ACTIVE"


def _resolve_call_username(fn, args, kwargs) -> str | None:
    """Best-effort "whose order is this?" for the decorated call.

    The kill switch is per-user (see database/settings_db.py), so the gate
    needs an identity. Every order-placing service in this codebase takes
    an `api_key` parameter (positionally or by keyword), so bind the call's
    arguments against the real signature and read it from there -- that
    works uniformly across all ~10 decorated functions without changing any
    of their signatures.

    Falls back to the Flask session / active user_scope when no api_key was
    supplied (internal auth_token+broker calls). Returns None when neither
    is available, which the caller treats as fail-open.
    """
    api_key = kwargs.get("api_key")
    if not api_key:
        try:
            bound = inspect.signature(fn).bind_partial(*args, **kwargs)
            api_key = bound.arguments.get("api_key")
        except (TypeError, ValueError):
            api_key = None

    if api_key:
        from utils.socket_scope import username_from_api_key

        username = username_from_api_key(api_key)
        if username:
            return username

    from utils.socket_scope import resolve_current_username

    return resolve_current_username()


def enforce_kill_switch(op: str = "order"):
    """Decorator for order-placing service functions.

    op='order'  -- blocked when the ORDER OWNER's kill switch is active.
    op='cancel' -- always allowed; this is a documentation-only no-op so
                   `grep enforce_kill_switch` surfaces every touched file,
                   including the ones that must keep working during cleanup
                   (cancel_order, cancel_all_orders, close_position).

    The gate is per-user: it reads the switch belonging to whoever placed
    the order (resolved by _resolve_call_username above), not a single
    global flag. Previously one user activating their kill switch blocked
    live order placement for EVERY account on the instance.

    When the owner cannot be resolved the call is ALLOWED through, matching
    services/order_gate.py's fail-open posture -- an unattributable
    internal call must not be blocked by an unrelated user's emergency
    stop. Order-placing paths that CAN identify the user are additionally
    gated by check_order_allowed(), which receives the api_key explicitly.

    The wrapped function's own return-value SHAPE is preserved: every
    order-placing service in this codebase returns a
    (success: bool, response: dict, status_code: int) tuple, so the blocked
    case returns that same shape rather than raising, matching how these
    functions already report business-logic failures (e.g. insufficient
    margin) to their callers.
    """

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if op == "order":
                username = _resolve_call_username(fn, args, kwargs)
                if username and is_kill_switch_active(username):
                    return (
                        False,
                        {
                            "status": "error",
                            "code": KILL_SWITCH_ERROR_CODE,
                            "message": KILL_SWITCH_ERROR_MESSAGE,
                        },
                        403,
                    )
            return fn(*args, **kwargs)

        return wrapper

    return deco
