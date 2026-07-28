"""
SocketIO subscriber — emits the correct socketio event for each order event.

Reproduces the exact event names and payload structures from the original code.
Called directly from the EventBus thread pool — socketio.emit() is thread-safe
with async_mode="threading" and avoids greenlet errors under eventlet.
"""

from extensions import socketio
from utils.logging import get_logger
from utils.socket_scope import emit_to_user

logger = get_logger(__name__)


def _room_for_event(event) -> str | None:
    """Resolve the per-user Socket.IO room ("user_<username>", joined on
    connect -- see app.py's `_join_user_room`) that this event's acting
    user should receive it in, or None if it can't be resolved.

    Every order/notification emit in this module used to be a bare
    `socketio.emit(...)` with no `room=`, which Flask-SocketIO broadcasts
    to EVERY connected client regardless of account -- so User A placing
    an order (including from a headless Python strategy, MaxHook webhook,
    or deployment) fired the "Order Sent to Broker" toast in every other
    logged-in user's browser too. This is the exact same class of bug
    app.py's own comment documents already having been fixed once for
    force_logout; it was just never applied here. `event.api_key` (present
    on every OrderEvent/GTTEvent subclass) resolves to the acting user via
    the same verify_api_key() lookup used everywhere else in the app.

    Returns None (broadcast intentionally skipped by the caller) for
    internal call paths that place an order via a raw auth_token+broker
    pair with no Max Algos api_key (e.g. signal_engine.py's webhook/
    deployment order placement) -- those don't populate event.api_key
    today, so there's no user to scope the room to. Better to drop that
    one user's own live-order-status notification than keep broadcasting
    it to everyone else.
    """
    api_key = getattr(event, "api_key", None)
    if not api_key:
        return None
    try:
        from database.auth_db import verify_api_key

        username = verify_api_key(api_key)
    except Exception:
        logger.debug("Could not resolve username from api_key for socketio room scoping")
        return None
    if not username:
        return None
    return f"user_{username}"


def _emit_scoped(event_name: str, payload: dict, event) -> None:
    """socketio.emit(...) scoped to the acting user's room when resolvable,
    otherwise skipped (see _room_for_event's docstring for why silently
    dropping is safer here than broadcasting to everyone)."""
    room = _room_for_event(event)
    if room is None:
        logger.debug(
            f"Skipping {event_name} emit -- could not resolve acting user's room "
            "(internal call path with no api_key)"
        )
        return
    socketio.emit(event_name, payload, room=room)


def on_order_placed(event):
    """Emit order_event (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        _emit_scoped(
            "order_event",
            {
                "symbol": event.symbol,
                "action": event.action,
                "orderid": event.orderid,
                "exchange": event.exchange,
                "price_type": event.pricetype,
                "product_type": event.product,
                "strategy": event.strategy,
                "mode": "live",
            },
            event,
        )


def on_order_failed(event):
    """Emit order_event (live) or analyzer_update (analyze).

    Only order_event is emitted, not also order_notification -- the
    frontend's order_event handler (useSocket.ts) already shows both a red
    error toast AND adds a notification drawer entry for a rejected order in
    a single handler. Emitting order_notification too used to duplicate both
    of those (its own handler does the same toast+addNotification pair
    again), producing 2 toasts/drawer entries for one rejection.
    """
    if getattr(event, "mode", "live") == "analyze":
        _emit_analyzer_update(event)
    else:
        err_msg = (
            getattr(event, "error_message", None)
            or getattr(event, "reason", None)
            or getattr(event, "message", None)
            or "Order rejected by broker"
        )
        symbol = getattr(event, "symbol", "")
        action = getattr(event, "action", "")
        orderid = getattr(event, "orderid", "")
        strategy = getattr(event, "strategy", "")
        _emit_scoped(
            "order_event",
            {
                "symbol": symbol,
                "action": action,
                "orderid": orderid,
                "status": "rejected",
                "message": err_msg,
                "rejection_reason": err_msg,
                "strategy": strategy,
                "mode": "live",
            },
            event,
        )


def on_smart_order_no_action(event):
    """Emit order_notification (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        _emit_scoped(
            "order_notification",
            {
                "symbol": event.symbol,
                "status": "info",
                "message": event.message,
            },
            event,
        )


def on_order_modified(event):
    """Emit modify_order_event (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        _emit_scoped(
            "modify_order_event",
            {
                "status": "success",
                "orderid": event.orderid,
                "mode": "live",
            },
            event,
        )


def on_order_modify_failed(event):
    """Emit order_notification (live) or analyzer_update (analyze)."""
    if getattr(event, "mode", "live") == "analyze":
        _emit_analyzer_update(event)
    else:
        err_msg = (
            getattr(event, "error_message", None)
            or getattr(event, "reason", None)
            or getattr(event, "message", None)
            or "Order modification failed"
        )
        symbol = getattr(event, "symbol", "")
        _emit_scoped(
            "order_notification",
            {
                "symbol": symbol,
                "status": "error",
                "message": f"Order Modify Failed ({symbol}): {err_msg}",
            },
            event,
        )


def on_order_cancelled(event):
    """Emit cancel_order_event (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        _emit_scoped(
            "cancel_order_event",
            {
                "status": event.status,
                "orderid": event.orderid,
                "mode": "live",
            },
            event,
        )


def on_order_cancel_failed(event):
    """Emit order_notification (live) or analyzer_update (analyze)."""
    if getattr(event, "mode", "live") == "analyze":
        _emit_analyzer_update(event)
    else:
        err_msg = (
            getattr(event, "error_message", None)
            or getattr(event, "reason", None)
            or getattr(event, "message", None)
            or "Order cancellation failed"
        )
        symbol = getattr(event, "symbol", "")
        _emit_scoped(
            "order_notification",
            {
                "symbol": symbol,
                "status": "error",
                "message": f"Order Cancel Failed ({symbol}): {err_msg}",
            },
            event,
        )


def on_all_orders_cancelled(event):
    """Emit cancel_order_event batch (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        _emit_scoped(
            "cancel_order_event",
            {
                "status": "success",
                "orderid": f"{event.canceled_count} orders canceled",
                "mode": "live",
                "batch_order": True,
                "is_last_order": True,
                "canceled_count": event.canceled_count,
                "failed_count": event.failed_count,
            },
            event,
        )


def on_position_closed(event):
    """Emit close_position_event (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        _emit_scoped(
            "close_position_event",
            {
                "status": "success",
                "message": event.message or "All Open Positions Squared Off",
                "mode": "live",
            },
            event,
        )


def on_basket_completed(event):
    """Emit order_event batch summary (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        _emit_scoped(
            "order_event",
            {
                "symbol": event.strategy or "Basket",
                "action": f"{event.successful}/{event.total} orders",
                "orderid": f"basket_{event.successful}",
                "exchange": "MULTI",
                "price_type": "BASKET",
                "product_type": "BASKET",
                "mode": "live",
                "batch_order": True,
                "is_last_order": True,
            },
            event,
        )


def on_split_completed(event):
    """Emit order_event batch summary (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        _emit_scoped(
            "order_event",
            {
                "symbol": event.symbol or "Split",
                "action": event.action or "SPLIT",
                "orderid": f"{event.successful}/{event.total} orders",
                "exchange": event.exchange or "Unknown",
                "price_type": event.pricetype or "MARKET",
                "product_type": event.product or "MIS",
                "mode": "live",
                "batch_order": True,
                "is_last_order": True,
            },
            event,
        )


def on_options_completed(event):
    """Emit order_event batch summary (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        _emit_scoped(
            "order_event",
            {
                "symbol": event.symbol,
                "action": event.action,
                "orderid": f"{event.successful}/{event.total} orders",
                "exchange": event.exchange,
                "price_type": event.pricetype or "MARKET",
                "product_type": event.product or "MIS",
                "mode": "live",
                "batch_order": True,
                "is_last_order": True,
            },
            event,
        )


def on_multiorder_completed(event):
    """Emit order_event batch summary (live) or analyzer_update (analyze)."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)
    else:
        _emit_scoped(
            "order_event",
            {
                "symbol": event.underlying,
                "action": event.strategy or "Multi-Order",
                "orderid": f"{event.successful_legs}/{event.total} legs",
                "exchange": event.exchange,
                "price_type": "MULTI",
                "product_type": "OPTIONS",
                "mode": "live",
                "batch_order": True,
                "is_last_order": True,
                "multiorder_summary": True,
                "successful_legs": event.successful_legs,
                "failed_legs": event.failed_legs,
            },
            event,
        )


def on_analyzer_error(event):
    """Emit analyzer_update only for analyze-mode errors."""
    if event.mode == "analyze":
        _emit_analyzer_update(event)


def on_sandbox_order_filled(event):
    """Emit analyzer_update so OrderBook / TradeBook / Positions auto-refresh
    when a pending sandbox order fills via live LTP."""
    _emit_analyzer_update(event)


def on_sandbox_auto_squareoff(event):
    """Emit analyzer_update after the sandbox auto-square-off cycle so
    OrderBook (cancelled MIS orders) and Positions (closed MIS) refresh."""
    _emit_analyzer_update(event)


def on_sandbox_t1_settlement(event):
    """Emit analyzer_update after T+1 settlement so Positions and Holdings
    pages refresh."""
    _emit_analyzer_update(event)


def _emit_analyzer_update(event):
    """Helper to emit the analyzer_update socketio event, scoped to the
    acting user.

    Previously a bare broadcast, which is the same leak `_emit_scoped`
    above was introduced to fix -- it was just missed because the analyze/
    sandbox branch of every handler funnels through here instead of
    through _emit_scoped. The effect was that User A's sandbox and
    analyzer activity (every simulated order, every auto-square-off, every
    T+1 settlement) popped toasts in User B's browser and forced B's
    OrderBook/Positions/Holdings to refetch.

    Sandbox events (on_sandbox_order_filled / _auto_squareoff /
    _t1_settlement) reach here too; those carry the owning user on the
    event where available, so prefer an explicit `username` attribute and
    fall back to the api_key resolution used for order events.
    """
    username = getattr(event, "username", None) or getattr(event, "user_id", None)
    if username:
        emit_to_user(
            "analyzer_update",
            {"request": event.request_data, "response": event.response_data},
            username,
        )
        return

    room = _room_for_event(event)
    if room is None:
        logger.debug(
            "Skipping analyzer_update emit -- could not resolve acting user's room"
        )
        return
    socketio.emit(
        "analyzer_update",
        {"request": event.request_data, "response": event.response_data},
        room=room,
    )
