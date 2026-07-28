"""
Shared Order Verification Helper.

Asynchronously verifies order fill vs rejection status from the broker's order
book ~1s after placement, ensuring that exchange rejections (e.g. RMS Margin
Exceeded, market order blocked, invalid strike) emit red error toasts and drawer
notifications to the user regardless of how the order was triggered (Webhooks,
Strategies, Visual Builder, Smart Orders, or manual REST API calls).
"""

import time
from utils.logging import get_logger
from utils.socket_scope import emit_to_user, resolve_current_username

logger = get_logger(__name__)


def async_verify_order_fill(
    auth_token: str,
    broker: str,
    orderid: str,
    symbol: str,
    action: str = "BUY",
    strategy: str = "",
    delay_seconds: float = 1.2,
    username: str | None = None,
) -> None:
    """
    Background task that checks true order status from the broker's order book.
    If the order is rejected by the exchange or broker, emits socket events for
    red error toasts and notification drawer updates.

    `username` scopes that rejection toast to the trader who actually placed
    the order. It defaults to whoever is resolvable AT CALL TIME -- which is
    the point: this function is invoked from the request/placement thread
    (where the Flask session or an active user_scope still applies), but the
    emit happens ~1.2s later on a detached worker thread with no context of
    its own. Resolving eagerly here and closing over the result is what keeps
    the attribution correct. Previously this emit was a bare broadcast, so an
    exchange rejection of one user's order (with symbol, strategy tag and
    rejection reason) popped a red error toast in every logged-in user's
    browser -- and, worse, looked like THEIR order had just been rejected.
    """
    if not auth_token or not broker or not orderid:
        return

    emit_username = username or resolve_current_username()

    def _worker():
        time.sleep(delay_seconds)
        try:
            from services.orderstatus_service import get_order_status_with_auth

            ok, res, _ = get_order_status_with_auth({"orderid": orderid}, auth_token, broker, {})
            if ok and isinstance(res.get("data"), dict):
                o_data = res["data"]
                st = str(o_data.get("order_status", "")).lower()
                if st == "rejected":
                    rej_msg = (
                        o_data.get("rejection_reason")
                        or o_data.get("emsg")
                        or o_data.get("message")
                        or o_data.get("text")
                        or "Order rejected by exchange"
                    )
                    order_symbol = o_data.get("symbol") or symbol
                    # Emit order_event only -- the frontend's order_event
                    # handler (useSocket.ts) already shows BOTH a red error
                    # toast AND adds a notification drawer entry for a
                    # rejected order in a single handler. A second
                    # order_notification emit here used to duplicate both of
                    # those (frontend order_notification handler does the
                    # exact same toast+addNotification pair again), producing
                    # 2 toasts/drawer entries for one rejection.
                    emit_to_user(
                        "order_event",
                        {
                            "symbol": order_symbol,
                            "action": action,
                            "orderid": str(orderid),
                            "status": "rejected",
                            "message": rej_msg,
                            "rejection_reason": rej_msg,
                            "strategy": strategy,
                            "mode": "live",
                        },
                        emit_username,
                    )
                    logger.warning(
                        f"[OrderVerification] Verified rejection for OrderID {orderid} ({order_symbol}): {rej_msg}"
                    )
        except Exception as e:
            logger.debug(f"[OrderVerification] Error verifying fill status for OrderID {orderid}: {e}")

    try:
        socketio.start_background_task(_worker)
    except Exception as err:
        logger.debug(f"[OrderVerification] Could not start background task: {err}")
