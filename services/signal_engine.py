import json
import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from database.deployment_db import Deployment, db_session, update_deployment_status
from database.strategy_db import get_strategy_by_webhook_id
from services.risk_engine import validate_risk
from utils.broker_context import broker_credential_context

logger = logging.getLogger(__name__)

# Thread-safe queue for signal events
signal_queue = queue.Queue()
_worker_thread = None
_reaper_thread = None
_worker_running = False

# Signals are dispatched onto this bounded pool rather than processed inline
# on the dequeue loop. Without this, one signal whose broker call hangs (dead
# credentials, unreachable host, slow API) blocks _worker_loop's single
# queue.get() cursor, which stalls every subsequent webhook signal for every
# strategy platform-wide until that one call times out. A small shared pool
# (module-level singleton, per CLAUDE.md FD-hygiene convention) lets a stuck
# broker call stay stuck without stopping the rest of the queue from draining.
_SIGNAL_DISPATCH_WORKERS = 8
_dispatch_executor = ThreadPoolExecutor(
    max_workers=_SIGNAL_DISPATCH_WORKERS, thread_name_prefix="signal-dispatch"
)

# Hard ceiling on a single signal's processing time (network calls to broker
# APIs included). Guards against a broker connection that never times out on
# its own; a stuck dispatch thread is abandoned (not killed -- Python threads
# can't be force-killed) but stops blocking anything else once this fires.
_SIGNAL_PROCESSING_TIMEOUT_SECONDS = 30


def _resolve_live_instrument(mapping, api_key: str) -> tuple[str, str] | None:
    """For a FUT/OPT StrategySymbolMapping, resolve the live tradable
    contract symbol+exchange fresh (never cached/frozen) -- strikes and
    expiries must always reflect the CURRENT ATM/OTM/ITM at signal time,
    not whatever was true when the mapping was added. Returns
    (symbol, exchange) on success, None on any resolution failure (with
    the reason already logged) so the caller can skip this one mapping
    without aborting the rest of the signal.
    """
    from services.expiry_service import resolve_expiry_type
    from services.option_symbol_service import (
        get_futures_symbol,
        get_option_symbol,
        get_option_symbol_by_metric,
    )

    expiry_date = resolve_expiry_type(mapping.underlying, mapping.exchange, mapping.expiry_type, api_key)
    if not expiry_date:
        logger.error(
            f"Signal Engine: Could not resolve expiry '{mapping.expiry_type}' for "
            f"{mapping.underlying} on {mapping.exchange} (mapping {mapping.id})"
        )
        return None

    if mapping.instrument_type == "OPT":
        strike_selection_mode = getattr(mapping, "strike_selection_mode", None) or "offset"
        if strike_selection_mode == "offset":
            success, resp, _status = get_option_symbol(
                mapping.underlying,
                mapping.exchange,
                expiry_date,
                None,
                mapping.strike_offset,
                mapping.option_type,
                api_key,
            )
            resolution_desc = f"{mapping.strike_offset} {mapping.option_type}"
        else:
            success, resp, _status = get_option_symbol_by_metric(
                mapping.underlying,
                mapping.exchange,
                expiry_date,
                mapping.option_type,
                strike_selection_mode,
                getattr(mapping, "strike_target_value", None),
                api_key,
            )
            resolution_desc = f"{mapping.option_type} by {strike_selection_mode}"
        if not success:
            logger.error(
                f"Signal Engine: Could not resolve option symbol for mapping {mapping.id} "
                f"({mapping.underlying} {resolution_desc} {expiry_date}): "
                f"{resp.get('message', 'unknown error')}"
            )
            return None
        if mapping.quantity and resp.get("lotsize") and mapping.quantity % resp["lotsize"] != 0:
            logger.warning(
                f"Signal Engine: mapping {mapping.id} quantity {mapping.quantity} is not a "
                f"multiple of lot size {resp['lotsize']} for {resp['symbol']}"
            )
        return resp["symbol"], resp["exchange"]

    # FUT
    futures_info = get_futures_symbol(mapping.underlying, mapping.exchange, expiry_date, api_key)
    if not futures_info:
        logger.error(
            f"Signal Engine: Could not resolve futures symbol for mapping {mapping.id} "
            f"({mapping.underlying} on {mapping.exchange}, expiry {expiry_date})"
        )
        return None
    return futures_info["symbol"], futures_info["exchange"]


def _emit_scoped(event_name: str, payload: dict, user_id) -> None:
    """socketio.emit(...) scoped to `user_id`'s room ("user_<username>",
    joined on connect -- see app.py's `_join_user_room`), or skipped if the
    room can't be resolved.

    Every emit in this module used to be a bare `socketio.emit(...)` with no
    `room=`, which Flask-SocketIO broadcasts to EVERY connected client
    regardless of account -- so a webhook signal or deployment fill for one
    user fired order toasts in every other logged-in user's browser too.
    Same bug class already fixed once for subscribers/socketio_subscriber.py
    (order-placement notifications) and, earlier still, for app.py's
    force_logout. `user_id` here is a username string (Strategy.user_id /
    Deployment.user_id), so no api_key/verify_api_key lookup is needed --
    unlike the subscriber fix, the acting user is already known directly.
    """
    from extensions import socketio

    if not user_id:
        logger.debug(f"Skipping {event_name} emit -- no user_id to scope the room to")
        return
    socketio.emit(event_name, payload, room=f"user_{user_id}")


def _filter_active_mappings(mappings, strategy_name: str) -> list:
    """Log a visible skip line for every paused mapping (per the explicit
    product requirement that pausing must leave a distinct trace, not a
    silent skip indistinguishable from 'nothing matched'), then return
    only the active ones."""
    active = []
    for m in mappings:
        if getattr(m, "is_active", True):
            active.append(m)
        else:
            label = m.underlying or m.instrument or m.symbol
            logger.info(
                f"Signal Engine: Skipping paused mapping {label} (id={m.id}) for strategy "
                f"'{strategy_name}'"
            )
    return active


class SignalEvent:
    def __init__(self, webhook_id, signal, timeframe=None, source=None, strategy_version=None,
                 timestamp=None, delivery_id=None):
        self.webhook_id = webhook_id
        self.signal = signal.upper()
        self.timeframe = timeframe
        self.source = source or "TradingView"
        self.strategy_version = strategy_version
        self.timestamp = timestamp or int(time.time())
        # Links this event back to its webhook_deliveries row so the async
        # worker can record the terminal outcome the HTTP response could not
        # (the route returns 200 before processing finishes). None for signals
        # that did not originate from a webhook.
        self.delivery_id = delivery_id


def enqueue_signal(event: SignalEvent):
    """
    Enqueues a new signal event to be processed asynchronously.
    """
    signal_queue.put(event)
    logger.info(f"Signal '{event.signal}' enqueued for Webhook ID: {event.webhook_id}")


def _record_delivery_outcome(event: SignalEvent, method: str, *args, **kwargs):
    """Report a terminal outcome for the webhook delivery behind this event.

    No-op for events with no delivery_id (non-webhook signals, or a webhook
    whose audit write failed). Never raises -- audit bookkeeping must not be
    able to break signal processing.
    """
    delivery_id = getattr(event, "delivery_id", None)
    if not delivery_id:
        return
    try:
        from database import webhook_delivery_db

        getattr(webhook_delivery_db, method)(delivery_id, *args, **kwargs)
    except Exception:
        logger.exception("Failed to record webhook delivery outcome")


def _alert_safety_check_failed(strategy, check_name: str, error: Exception) -> None:
    """Raise a human-visible alarm when a safety gate fails open.

    Both gates below fail open on error so a settings/calendar fault can't
    silently halt every strategy platform-wide. The cost of that choice is the
    worst-shaped failure in the system: the kill switch reads ACTIVE in the UI
    while not actually enforcing. A log line alone is not enough -- nobody is
    tailing logs at 2am -- so this also pushes a Telegram alert to the
    strategy's owner.

    Dispatched on the shared alert_executor (never inline) so a slow or
    unreachable Telegram API cannot add latency to the order path, and wrapped
    so an alerting failure can never propagate into signal processing.
    """
    logger.exception(
        f"Signal Engine: {check_name} check FAILED OPEN for strategy "
        f"'{strategy.name}' -- signal allowed through unguarded: {error}"
    )
    try:
        from database.telegram_db import get_telegram_user_by_username
        from services.telegram_alert_service import alert_executor, telegram_alert_service

        telegram_user = get_telegram_user_by_username(strategy.user_id)
        if not telegram_user or not telegram_user.get("notifications_enabled"):
            return

        message = (
            "⚠️ <b>SAFETY CHECK FAILED</b>\n\n"
            f"The <b>{check_name}</b> check could not be evaluated for strategy "
            f"<b>{strategy.name}</b> and the signal was allowed through "
            "<b>unguarded</b>.\n\n"
            f"Error: <code>{error}</code>\n\n"
            "If you believe trading is halted, it may NOT be. Verify manually."
        )
        alert_executor.submit(
            telegram_alert_service.send_alert_sync, telegram_user["telegram_id"], message
        )
    except Exception:
        # Alerting is best-effort: never let it break signal processing.
        logger.exception(
            f"Signal Engine: failed to dispatch fail-open alert for '{strategy.name}'"
        )


def _kill_switch_blocks_signal(strategy, event: SignalEvent) -> bool:
    """True if THIS STRATEGY'S OWNER has their kill switch active and this
    signal must not run.

    Scoped to `strategy.user_id`: the kill switch is per-user (see
    database/settings_db.py), so another account's emergency stop must not
    halt this user's strategies.

    Fails OPEN (returns False) if the flag can't be read: a settings-table
    fault should not silently halt every strategy on the platform. An operator
    who has actually flipped the switch gets a working block; an operator
    hitting a DB error gets today's behavior plus a logged exception.
    """
    try:
        from database.settings_db import is_kill_switch_active

        if not is_kill_switch_active(getattr(strategy, "user_id", None)):
            return False
    except Exception as exc:
        _alert_safety_check_failed(strategy, "kill switch", exc)
        return False

    logger.warning(
        f"Signal Engine: Kill switch is ACTIVE. Rejecting signal '{event.signal}' "
        f"for strategy '{strategy.name}'."
    )
    _record_delivery_outcome(
        event,
        "update_outcome",
        "rejected",
        reason_code="kill_switch_active",
        reason_detail="Master kill switch was active when the signal was processed",
    )
    return True


def _market_hours_blocks_signal(strategy, event: SignalEvent) -> bool:
    """True if this strategy enforces market hours and the market is closed.

    Opt-in per strategy via Strategy.enforce_market_hours (defaults False, so
    existing strategies are unaffected). Fails OPEN for the same reason as the
    kill-switch check above.
    """
    if not getattr(strategy, "enforce_market_hours", False):
        return False

    try:
        from database.market_calendar_db import is_market_open

        if is_market_open():
            return False
    except Exception as exc:
        _alert_safety_check_failed(strategy, "market hours", exc)
        return False

    logger.warning(
        f"Signal Engine: Market is closed and strategy '{strategy.name}' enforces "
        f"market hours. Rejecting signal '{event.signal}'."
    )
    _record_delivery_outcome(
        event,
        "update_outcome",
        "rejected",
        reason_code="market_closed",
        reason_detail="Market was closed and this strategy enforces market hours",
    )
    return True


def _process_signal_event(event: SignalEvent):
    """
    Core signal handler evaluating deployment state awareness and placing broker orders.
    """
    try:
        strategy = get_strategy_by_webhook_id(event.webhook_id)
        if not strategy:
            logger.error(f"Signal Engine: Strategy not found for webhook ID: {event.webhook_id}")
            _record_delivery_outcome(
                event,
                "update_outcome",
                "failed",
                reason_code="strategy_not_found",
                reason_detail="Strategy disappeared between enqueue and processing",
            )
            return

        if not strategy.is_active:
            logger.warning(f"Signal Engine: Strategy '{strategy.name}' is inactive. Ignoring signal.")
            _record_delivery_outcome(
                event,
                "update_outcome",
                "rejected",
                reason_code="strategy_inactive",
                reason_detail="Strategy was deactivated before the signal was processed",
            )
            return

        # Master kill switch. Checked here rather than inside each execution
        # model so it covers all four paths (legacy/unified/stateful webhook +
        # deployment) at the single point every signal passes through. Until
        # this existed, flipping the kill switch stopped Chartink and Python
        # Strategy Host orders (they check it at their own entry points) but
        # NOT MaxHook webhook orders, which reached the broker unguarded.
        # set_kill_switch() invalidates the cached flag on write, so a flip is
        # visible to this worker thread immediately.
        if _kill_switch_blocks_signal(strategy, event):
            return

        # Optional per-strategy market-hours gate. Off by default: the global
        # check in place_order_service.py is commented out deliberately so
        # out-of-hours testing works, and silently re-enabling it platform-wide
        # would break that. Strategies opt in individually instead.
        if _market_hours_blocks_signal(strategy, event):
            return

        # Check if it is a Webhook Strategy (platform != "strategy_builder")
        is_webhook_strategy = (strategy.platform != "strategy_builder")

        if is_webhook_strategy:
            # execution_model gates which pipeline handles this strategy's
            # signals: 'legacy' (default, every pre-existing strategy) is
            # the original 2-action BUY/SELL path. 'unified' opts into the
            # 4-action BUY/SELL/SHORT/EXIT engine with ExecutionProfile
            # support -- each mapping row reacts to a fixed action with a
            # static order_side. 'stateful' opts into LegGroup/Leg rotation
            # -- unlike 'unified', it tracks WHICH leg is currently open
            # (current_leg_id) so the same signal can mean "close whichever
            # leg is open, then open the other one" (a reversal/flip),
            # which a static per-mapping order_side cannot express. Every
            # strategy stays on the exact path it's always run on unless
            # explicitly switched.
            execution_model = _resolve_execution_model(strategy)
            if execution_model == "stateful":
                _process_leg_group_webhook_signal(strategy, event)
            elif execution_model == "unified":
                _process_unified_webhook_signal(strategy, event)
            else:
                _process_legacy_webhook_signal(strategy, event)
            _record_delivery_outcome(
                event,
                "update_outcome",
                "processed",
                reason_detail=f"Processed via {execution_model} engine",
            )
            return

        _process_deployment_signal_event(strategy, event)
        _record_delivery_outcome(event, "update_outcome", "processed")

    except Exception as e:
        logger.exception(f"Signal Engine: Error handling signal event: {e}")
        _record_delivery_outcome(
            event, "update_outcome", "failed", reason_code="processing_error", reason_detail=str(e)
        )


def _resolve_execution_model(strategy) -> str:
    """Which engine actually handles this strategy's signals.

    Execution model used to be a user-facing dropdown on the Configure
    Symbols page, which forced traders to understand three internal engine
    paths before adding a single symbol -- and picking the wrong one
    silently sent signals down a handler that ignored their config. It is
    now DERIVED from what the strategy actually contains:

      * has an active LegGroup  -> 'stateful' (rotation is the only engine
        that can track which leg is open)
      * otherwise               -> whatever the strategy is stored as

    The stored value is still honoured for everything else, so existing
    'legacy' strategies keep running on the exact 2-action path they always
    have. New strategies are created as 'unified' (see
    database/strategy_db.py's create_strategy default), which is a superset
    of legacy: BUY/SELL behave identically, and SHORT/EXIT additionally
    work instead of collapsing into SELL.

    Deriving here (rather than only at write time) means a strategy that
    gains its first leg group starts rotating immediately, without the user
    having to also remember to flip a mode dropdown.
    """
    stored = getattr(strategy, "execution_model", "legacy") or "legacy"

    try:
        from database.strategy_db import get_leg_groups

        groups = get_leg_groups(strategy.id) or []
        if any(getattr(g, "is_active", True) and getattr(g, "legs", None) for g in groups):
            if stored != "stateful":
                logger.info(
                    f"Signal Engine: Strategy '{strategy.name}' has active leg groups -- "
                    f"routing via 'stateful' engine (stored model: '{stored}')"
                )
            return "stateful"
    except Exception:
        # Never let model derivation break signal processing -- fall back to
        # the stored value, which is what ran before this function existed.
        logger.debug("Signal Engine: leg-group lookup failed during model derivation", exc_info=True)

    return stored


def _process_legacy_webhook_signal(strategy, event: SignalEvent):
    """Original 2-action (BUY/SELL) webhook signal handler. Unmodified
    behavior -- SHORT and EXIT both collapse into SELL, exactly as before
    this feature existed. See _process_unified_webhook_signal for the new
    4-action pipeline."""
    try:
        from database.auth_db import (
            get_api_key_for_tradingview,
            get_broker_session,
            list_broker_sessions,
        )
        from database.strategy_db import get_symbol_mappings
        from services.place_order_service import place_order

        logger.info(f"Signal Engine: Processing Webhook Strategy signal '{event.signal}' for '{strategy.name}'")

        # 1. Normalize trigger signal action
        signal_action = event.signal.upper()
        normalized_action = None
        if signal_action in ["BUY", "COVER"]:
            normalized_action = "BUY"
        elif signal_action in ["SELL", "SHORT", "EXIT"]:
            normalized_action = "SELL"

        if not normalized_action:
            logger.warning(f"Signal Engine: Unknown signal action '{signal_action}'. Ignoring.")
            return

        # 2. Get symbol mappings
        mappings = get_symbol_mappings(strategy.id)
        if not mappings:
            logger.warning(f"Signal Engine: No symbol mappings found for strategy '{strategy.name}'.")
            return

        # Filter mappings matching the action (the symbol column must be
        # "BUY", "SELL", or "BOTH"). `action` is the correctly-named column
        # (see StrategySymbolMapping's class docstring); fall back to the
        # legacy `symbol` column for any row created before the action
        # column existed and hasn't been backfilled yet (the startup
        # migration backfills existing rows, but this keeps the read path
        # correct even if that hasn't run). A mapping set to "BOTH" reacts
        # to either BUY or SELL signals; one set to a specific direction
        # only reacts to that direction and ignores the other.
        matching_mappings = [
            m for m in mappings
            if (m.action or m.symbol or "").upper() in (normalized_action, "BOTH")
        ]
        matching_mappings = _filter_active_mappings(matching_mappings, strategy.name)
        if not matching_mappings:
            logger.info(f"Signal Engine: No active mappings found matching trigger symbol '{normalized_action}' for strategy '{strategy.name}'.")
            return

        # Resolve the platform API key once per strategy if any mapping
        # needs live FUT/OPT resolution -- data-broker-agnostic quote
        # fetching needs this, not a broker auth token.
        needs_api_key = any(m.instrument_type in ("FUT", "OPT") for m in matching_mappings)
        api_key = get_api_key_for_tradingview(strategy.user_id) if needs_api_key else None
        if needs_api_key and not api_key:
            logger.error(
                f"Signal Engine: No API key found for user {strategy.user_id} -- cannot resolve "
                f"live Futures/Options mappings for strategy '{strategy.name}'. Generate one at "
                "/apikey."
            )

        # 3. Resolve brokers
        brokers = []
        if hasattr(strategy, "brokers") and strategy.brokers:
            brokers = [b.strip() for b in strategy.brokers.split(",") if b.strip()]

        # Fallback to user's active session broker if none configured
        if not brokers:
            active_sessions = list_broker_sessions(strategy.user_id)
            brokers = [s["broker"] for s in active_sessions if not s.get("is_revoked")]

        if not brokers:
            brokers = ["Paper Trading"]

        # 4. Process order placement for each broker and mapped instrument
        for broker in brokers:
            for mapping in matching_mappings:
                inst_exchange = mapping.exchange
                if mapping.instrument_type in ("FUT", "OPT"):
                    if not api_key:
                        continue  # already logged above -- can't resolve without an API key
                    resolved = _resolve_live_instrument(mapping, api_key)
                    if not resolved:
                        continue  # failure already logged inside _resolve_live_instrument
                    inst_symbol, inst_exchange = resolved
                else:
                    inst_symbol = mapping.instrument or mapping.symbol
                logger.info(f"Signal Engine Webhook: Executing mapping {inst_symbol} on broker {broker} for action {normalized_action}")

                # Emit order receipt notification
                _emit_scoped(
                    "order_notification",
                    {
                        "symbol": inst_symbol,
                        "status": "info",
                        "message": f"Webhook signal '{signal_action}' received for broker '{broker}'. Placing order..."
                    },
                    strategy.user_id,
                )

                if broker == "Paper Trading":
                    # Simulate paper trade
                    time.sleep(0.5)
                    import uuid
                    mock_order_id = f"MOCK-{uuid.uuid4().hex[:8].upper()}"

                    _emit_scoped(
                        "order_event",
                        {
                            "symbol": inst_symbol,
                            "action": normalized_action,
                            "orderid": mock_order_id,
                            "exchange": inst_exchange,
                            "price_type": "MARKET",
                            "product_type": mapping.product_type,
                            "mode": "live",
                        },
                        strategy.user_id,
                    )
                    _emit_scoped(
                        "order_notification",
                        {
                            "symbol": inst_symbol,
                            "status": "success",
                            "message": f"Paper Trade Order {mock_order_id} filled successfully on Paper Trading."
                        },
                        strategy.user_id,
                    )
                else:
                    # Place live order on broker
                    session_info = get_broker_session(strategy.user_id, broker)
                    if not session_info:
                        err_msg = f"No active connection found for broker '{broker}'"
                        logger.error(err_msg)
                        _emit_scoped(
                            "order_notification",
                            {
                                "symbol": inst_symbol,
                                "status": "error",
                                "message": f"Order failed on {broker}: {err_msg}"
                            },
                            strategy.user_id,
                        )
                        continue

                    auth_token, feed_token, br_user_id = session_info

                    order_data = {
                        "symbol": inst_symbol,
                        "exchange": inst_exchange,
                        "action": normalized_action,
                        "quantity": mapping.quantity,
                        # OrderSchema (restx_api/schemas.py) expects "pricetype"/
                        # "product" -- "price_type"/"product_type" are unknown
                        # fields to that schema and previously caused every
                        # live-broker order from this path to fail validation.
                        "pricetype": "MARKET",
                        "product": mapping.product_type,
                        "strategy": strategy.name,
                    }

                    # Some broker modules resolve their API key via
                    # os.getenv("BROKER_API_KEY") internally (Noren-family
                    # brokers like bnr/zebu/shoonya/flattrade do this in
                    # order_api.py), which app.py's os.getenv patch
                    # resolves from session["broker"] (the data broker) by
                    # default -- NOT from this loop's `broker` variable.
                    # Without this context, a strategy configured to
                    # trade on multiple brokers (or any broker other than
                    # the current data broker) would silently place every
                    # order using the DATA BROKER's API key. See
                    # utils/broker_context.py for the full explanation
                    # (this is the same fix already applied in
                    # multi_broker_order_service.py for the REST fan-out
                    # path).
                    with broker_credential_context(strategy.user_id, broker):
                        success, resp, status = place_order(
                            order_data=order_data,
                            auth_token=auth_token,
                            broker=broker,
                            username=strategy.user_id,
                        )

                    # No notification/verification code here -- place_order()
                    # (called above) routes through place_order_with_auth,
                    # which already publishes OrderPlacedEvent ("sent to
                    # broker") on success, OrderFailedEvent on broker
                    # rejection, and already calls async_verify_order_fill
                    # itself. Duplicating any of that here used to fire a
                    # second independent verification worker + a second
                    # "sent to broker" emit for the same order, producing
                    # duplicate toasts/notifications for one outcome (see
                    # MaxHook webhook orders showing 2x "Order REJECTED").
    except Exception as e:
        logger.exception(f"Signal Engine: Error handling legacy webhook signal event: {e}")


# Signals accepted by the unified (4-action) execution engine. Unlike the
# legacy path's normalize-to-2-actions behavior, each of these is matched
# and executed independently -- a mapping row's action must equal one of
# these exactly (COVER is not a distinct action here; map it to BUY at the
# TradingView alert level, or configure a BUY-action mapping for it).
_UNIFIED_ACTIONS = frozenset({"BUY", "SELL", "SHORT", "EXIT"})


def _process_unified_webhook_signal(strategy, event: SignalEvent):
    """4-action (BUY/SELL/SHORT/EXIT) webhook signal handler.

    Each StrategySymbolMapping row is matched on its real `action` value
    (no collapsing SHORT/EXIT into SELL, unlike the legacy path), and the
    effective quantity/product/order_type/broker for the matched action is
    resolved via StrategySymbolMapping.resolve_execution() -- the linked
    ExecutionProfile's defaults, with this action's override JSON applied
    on top. This is what makes "change one profile, every linked
    instrument updates" and per-action overrides (see database/strategy_db.py's
    ExecutionProfile/resolve_execution) actually take effect at signal time.

    Only reachable when strategy.execution_model == 'unified' -- see
    _process_signal_event's dispatch. Every existing strategy stays on
    _process_legacy_webhook_signal untouched.
    """
    try:
        from database.auth_db import (
            get_api_key_for_tradingview,
            get_broker_session,
            list_broker_sessions,
        )
        from database.strategy_db import get_symbol_mappings
        from services.place_order_service import place_order

        logger.info(f"Signal Engine: Processing Unified Strategy signal '{event.signal}' for '{strategy.name}'")

        signal_action = event.signal.upper()
        if signal_action not in _UNIFIED_ACTIONS:
            logger.warning(
                f"Signal Engine: Unknown action '{signal_action}' for unified strategy "
                f"'{strategy.name}' (expected one of {sorted(_UNIFIED_ACTIONS)}). Ignoring."
            )
            return

        mappings = get_symbol_mappings(strategy.id)
        if not mappings:
            logger.warning(f"Signal Engine: No symbol mappings found for strategy '{strategy.name}'.")
            return

        matching_mappings = [
            m for m in mappings
            if (m.action or "").upper() == signal_action
        ]
        matching_mappings = _filter_active_mappings(matching_mappings, strategy.name)
        if not matching_mappings:
            logger.info(
                f"Signal Engine: No active mappings configured for action '{signal_action}' "
                f"on strategy '{strategy.name}'."
            )
            return

        needs_api_key = any(m.instrument_type in ("FUT", "OPT") for m in matching_mappings)
        api_key = get_api_key_for_tradingview(strategy.user_id) if needs_api_key else None
        if needs_api_key and not api_key:
            logger.error(
                f"Signal Engine: No API key found for user {strategy.user_id} -- cannot resolve "
                f"live Futures/Options mappings for strategy '{strategy.name}'. Generate one at "
                "/apikey."
            )

        # Resolve brokers: a per-action override's "broker" key (if set)
        # takes priority per-mapping below; this strategy-level list is the
        # fallback when a mapping/profile doesn't specify one, mirroring
        # the legacy path's broker resolution exactly.
        strategy_brokers = []
        if strategy.brokers:
            strategy_brokers = [b.strip() for b in strategy.brokers.split(",") if b.strip()]
        if not strategy_brokers:
            active_sessions = list_broker_sessions(strategy.user_id)
            strategy_brokers = [s["broker"] for s in active_sessions if not s.get("is_revoked")]
        if not strategy_brokers:
            strategy_brokers = ["Paper Trading"]

        # Drop mappings the user has explicitly muted, then order the rest
        # so multi-leg baskets fire in a deterministic sequence. Exits are
        # sorted ahead of entries within a basket (see _mapping_sort_key) so
        # a spread that rolls one leg into another frees the margin before
        # trying to use it.
        matching_mappings = [
            m for m in matching_mappings if m.get_signal_action() != "IGNORE"
        ]

        # Per-rule gates (time window / indicator). NULL conditions always
        # pass, so rules created before this feature are unaffected. Blocked
        # rules are logged with the reason -- a silently skipped order is
        # indistinguishable from a broken strategy from the user's side.
        gated = []
        for m in matching_mappings:
            passed, reason = m.conditions_pass()
            if passed:
                gated.append(m)
            else:
                logger.info(
                    f"Signal Engine: rule {m.id} ({m.label or m.symbol}) skipped -- {reason}"
                )
        matching_mappings = gated
        if not matching_mappings:
            logger.info(
                f"Signal Engine: every rule matching '{signal_action}' on "
                f"'{strategy.name}' was blocked by its conditions."
            )
            return
        if not matching_mappings:
            logger.info(
                f"Signal Engine: All mappings for '{signal_action}' on strategy "
                f"'{strategy.name}' are set to IGNORE. Nothing to do."
            )
            return
        matching_mappings.sort(key=_mapping_sort_key)

        # Multi-leg baskets are all-or-nothing. A straddle with only one leg
        # filled is not a straddle -- it is a naked directional position the
        # trader never asked for, with unbounded risk on the missing side.
        # Pre-flight every leg in a basket BEFORE sending any of them, so a
        # basket that cannot be fully resolved is rejected as a unit instead
        # of leaving the account half-legged.
        basket_names = {m.leg_basket for m in matching_mappings if m.leg_basket}
        if basket_names:
            unresolvable = _preflight_baskets(matching_mappings, basket_names, api_key)
            if unresolvable:
                for basket in sorted(unresolvable):
                    logger.error(
                        f"Signal Engine: basket '{basket}' rejected -- one or more legs "
                        "could not be resolved. No legs were sent (a partially-filled "
                        "basket is a naked position)."
                    )
                    _emit_scoped(
                        "order_notification",
                        {
                            "symbol": basket,
                            "status": "error",
                            "message": (
                                f"Multi-leg basket '{basket}' was NOT placed: at least one "
                                "leg could not be resolved. All legs were skipped to avoid "
                                "leaving a one-sided position."
                            ),
                        },
                        strategy.user_id,
                    )
                matching_mappings = [
                    m for m in matching_mappings if m.leg_basket not in unresolvable
                ]
                if not matching_mappings:
                    return

        for mapping in matching_mappings:
            inst_exchange = mapping.exchange
            lot_size = None
            if mapping.instrument_type in ("FUT", "OPT"):
                if not api_key:
                    continue  # already logged above -- can't resolve without an API key
                resolved = _resolve_live_instrument(mapping, api_key)
                if not resolved:
                    continue  # failure already logged inside _resolve_live_instrument
                inst_symbol, inst_exchange = resolved
                lot_size = _lookup_lot_size(inst_symbol, inst_exchange)
            else:
                inst_symbol = mapping.instrument or mapping.symbol
            execution = mapping.resolve_execution(signal_action)

            # `lots` (when the user sized in lots rather than raw quantity)
            # is authoritative and resolves against the live contract's lot
            # size. resolve_quantity falls back to the raw quantity when
            # lots is unset, so nothing changes for existing mappings.
            if mapping.lots:
                execution["quantity"] = mapping.resolve_quantity(lot_size)

            brokers = [execution["broker"]] if execution.get("broker") else strategy_brokers

            for broker in brokers:
                logger.info(
                    f"Signal Engine Unified: Executing mapping {inst_symbol} on broker {broker} "
                    f"for action {signal_action} (qty={execution['quantity']}, "
                    f"product={execution['product']}, order_type={execution['order_type']})"
                )

                _emit_scoped(
                    "order_notification",
                    {
                        "symbol": inst_symbol,
                        "status": "info",
                        "message": f"Webhook signal '{signal_action}' received for broker '{broker}'. Placing order..."
                    },
                    strategy.user_id,
                )

                if broker == "Paper Trading":
                    time.sleep(0.5)
                    import uuid
                    mock_order_id = f"MOCK-{uuid.uuid4().hex[:8].upper()}"

                    _emit_scoped(
                        "order_event",
                        {
                            "symbol": inst_symbol,
                            "action": signal_action,
                            "orderid": mock_order_id,
                            "exchange": inst_exchange,
                            "price_type": execution["order_type"],
                            "product_type": execution["product"],
                            "mode": "live",
                        },
                        strategy.user_id,
                    )
                    _emit_scoped(
                        "order_notification",
                        {
                            "symbol": inst_symbol,
                            "status": "success",
                            "message": f"Paper Trade Order {mock_order_id} filled successfully on Paper Trading."
                        },
                        strategy.user_id,
                    )
                    continue

                session_info = get_broker_session(strategy.user_id, broker)
                if not session_info:
                    err_msg = f"No active connection found for broker '{broker}'"
                    logger.error(err_msg)
                    _emit_scoped(
                        "order_notification",
                        {
                            "symbol": inst_symbol,
                            "status": "error",
                            "message": f"Order failed on {broker}: {err_msg}"
                        },
                        strategy.user_id,
                    )
                    continue

                auth_token, feed_token, br_user_id = session_info

                # SHORT/EXIT are execution intents at this layer, not order
                # sides -- the broker API only knows BUY/SELL. By default
                # SHORT opens a short position (sell-to-open, no pre-existing
                # long required) and EXIT closes whatever's open, so both
                # place a SELL order; BUY stays BUY. This mirrors the legacy
                # path's SHORT/EXIT->SELL normalization, but SHORT and EXIT
                # resolve their OWN qty/product/order_type via
                # resolve_execution() instead of sharing SELL's mapping row.
                #
                # mapping.order_side overrides this derivation when set,
                # decoupling which order a mapping places from which signal
                # action it reacts to -- needed for reversal/flip strategies
                # (e.g. a SELL signal that exits a Call on one mapping AND
                # enters a Put via a BUY order on a second mapping, both
                # triggered by the same incoming SELL). NULL (the default
                # for every mapping created before this column existed)
                # falls back to the original behavior untouched.
                if mapping.order_side in ("BUY", "SELL"):
                    broker_side = mapping.order_side
                else:
                    broker_side = "SELL" if signal_action in ("SELL", "SHORT", "EXIT") else "BUY"

                # The mapping's own signal_action verb (ENTER/EXIT/REVERSE/
                # ADD/REDUCE) refines what the order means. EXIT/REDUCE close
                # an existing position, so they must trade the OPPOSITE side
                # of the entry -- deriving them from the incoming signal
                # alone would send a second entry in the same direction.
                # NULL => "ENTER", which leaves broker_side exactly as
                # derived above, so pre-existing mappings are untouched.
                mapping_verb = mapping.get_signal_action()
                if mapping_verb in ("EXIT", "REDUCE") and mapping.order_side not in ("BUY", "SELL"):
                    broker_side = "BUY" if broker_side == "SELL" else "SELL"

                order_data = {
                    "symbol": inst_symbol,
                    "exchange": inst_exchange,
                    "action": broker_side,
                    "quantity": execution["quantity"],
                    "pricetype": execution["order_type"],
                    "product": execution["product"],
                    "strategy": strategy.name,
                }

                # LIMIT/SL/SL-M need their price levels; MARKET ignores both.
                # Only sent when actually set so a MARKET order's payload is
                # byte-identical to what it was before this feature.
                if mapping.limit_price is not None:
                    order_data["price"] = mapping.limit_price
                if mapping.trigger_price is not None:
                    order_data["trigger_price"] = mapping.trigger_price

                # See the matching comment in _process_legacy_webhook_signal:
                # some broker modules resolve their API key via
                # os.getenv("BROKER_API_KEY"), which without this context
                # would resolve to the data broker's key instead of this
                # mapping/action's actual target broker.
                with broker_credential_context(strategy.user_id, broker):
                    success, resp, status = place_order(
                        order_data=order_data,
                        auth_token=auth_token,
                        broker=broker,
                        username=strategy.user_id,
                    )

                    # Attach SL / target orders for entries that configured
                    # them. Only on entry verbs -- placing a protective stop
                    # against a position we just CLOSED would open a new one.
                    if success and mapping_verb in ("ENTER", "ADD", "REVERSE"):
                        _place_risk_orders(
                            strategy=strategy,
                            mapping=mapping,
                            symbol=inst_symbol,
                            exchange=inst_exchange,
                            entry_side=broker_side,
                            quantity=execution["quantity"],
                            product=execution["product"],
                            auth_token=auth_token,
                            broker=broker,
                            entry_response=resp,
                        )

                # No notification/verification code here -- place_order()
                # (called above) routes through place_order_with_auth, which
                # already publishes OrderPlacedEvent ("sent to broker") on
                # success, OrderFailedEvent on broker rejection, and already
                # calls async_verify_order_fill itself. Duplicating any of
                # that here used to fire a second independent verification
                # worker + a second "sent to broker" emit for the same
                # order, producing duplicate toasts/notifications for one
                # outcome.
    except Exception as e:
        logger.exception(f"Signal Engine: Error handling unified webhook signal event: {e}")


def _mapping_sort_key(mapping) -> tuple:
    """Deterministic firing order for the mappings matched by one signal.

    Sorts by (basket, explicit leg order, closing-before-opening, id):
      * mappings in the same `leg_basket` stay contiguous, so a straddle's
        legs are sent together rather than interleaved with unrelated rows;
      * `basket_leg_order` is the user's explicit sequence within a basket;
      * closing verbs (EXIT/REDUCE) sort before opening ones, so a roll
        frees margin before the replacement leg tries to consume it;
      * `id` is the final tiebreak so the order is stable across runs
        instead of depending on however the DB returned the rows.
    """
    closing = 0 if mapping.get_signal_action() in ("EXIT", "REDUCE") else 1
    return (
        mapping.leg_basket or "",
        mapping.basket_leg_order if mapping.basket_leg_order is not None else 0,
        closing,
        mapping.id or 0,
    )


def _preflight_baskets(mappings, basket_names: set, api_key: str | None) -> set:
    """Return the basket names that must NOT be sent.

    A multi-leg basket only makes sense as a whole: a straddle missing its
    put is a naked call, and a spread missing its short leg is an unhedged
    long. So every leg is resolved up front, and if ANY leg of a basket
    fails, the entire basket is skipped rather than sending the rest.

    Resolution failure means the live contract could not be determined --
    a stale expiry, a strike outside the chain, or a missing API key for
    FUT/OPT lookups. Broker-side rejections after this point can still
    leave a basket partially filled; guarding against that would need
    order-level rollback, which is deliberately out of scope here (see the
    caller's comment). This check removes the large, predictable class of
    failures that happen before anything reaches the broker.
    """
    unresolvable: set = set()

    for mapping in mappings:
        basket = mapping.leg_basket
        if not basket or basket in unresolvable:
            continue

        if mapping.instrument_type in ("FUT", "OPT"):
            if not api_key:
                logger.error(
                    f"Signal Engine: basket '{basket}' leg {mapping.id} needs a live "
                    "contract but no API key is available."
                )
                unresolvable.add(basket)
                continue
            if not _resolve_live_instrument(mapping, api_key):
                # _resolve_live_instrument already logged the specifics.
                unresolvable.add(basket)
                continue
        elif not (mapping.instrument or mapping.symbol):
            logger.error(
                f"Signal Engine: basket '{basket}' leg {mapping.id} has no instrument."
            )
            unresolvable.add(basket)

    return unresolvable


def _lookup_lot_size(symbol: str, exchange: str) -> int | None:
    """Contract lot size for a resolved F&O symbol, or None if unknown.

    Used only to convert a `lots`-sized mapping into a broker quantity.
    Returns None (rather than a guess) when the symbol isn't found, so
    resolve_quantity falls back to the raw quantity instead of sending a
    wrongly-multiplied order.
    """
    try:
        # token_db_enhanced (not token_db) is the module that exposes full
        # SymbolData including lotsize, and it serves from the in-memory
        # master-contract cache before touching the DB.
        from database.token_db_enhanced import get_symbol_info

        info = get_symbol_info(symbol, exchange)
        lot_size = getattr(info, "lotsize", None) if info else None
        return int(lot_size) if lot_size else None
    except Exception:
        logger.debug(f"Signal Engine: lot-size lookup failed for {symbol}/{exchange}", exc_info=True)
        return None


def _place_risk_orders(
    strategy,
    mapping,
    symbol: str,
    exchange: str,
    entry_side: str,
    quantity: int,
    product: str,
    auth_token: str,
    broker: str,
    entry_response: dict | None,
) -> None:
    """Place the SL / target orders configured on `mapping` after an entry.

    Both are placed as protective orders on the OPPOSITE side of the entry
    (a long is protected by a SELL stop, a short by a BUY stop).

    Values are stored unit-tagged ("percent" or "points") rather than as
    absolute prices, because one mapping is reused across many fills at
    different prices -- see StrategySymbolMapping.get_risk_config. They are
    converted to absolute levels here against the actual fill price.

    Never raises: a protective order failing must be logged loudly but must
    not bubble up and abort the rest of the basket, which would leave the
    remaining legs unplaced. Trailing stops are recorded on the order but
    only brokers that natively support a trailing field will honour them.
    """
    risk = mapping.get_risk_config()
    if not risk:
        return

    entry_price = None
    for key in ("average_price", "avgprice", "price", "fill_price"):
        value = (entry_response or {}).get(key)
        if value:
            try:
                entry_price = float(value)
                break
            except (TypeError, ValueError):
                continue

    if not entry_price:
        logger.warning(
            f"Signal Engine: SL/target configured for {symbol} but the entry fill price "
            "was not in the broker response -- skipping protective orders. Configure "
            "them at the broker, or use a broker that returns average_price."
        )
        return

    exit_side = "SELL" if entry_side == "BUY" else "BUY"
    is_long = entry_side == "BUY"

    def _level(cfg: dict, favourable: bool) -> float | None:
        """Absolute price for a percent/points offset. `favourable` means
        the move is in the trade's favour (a target); otherwise it is
        against it (a stop)."""
        try:
            value = float(cfg["value"])
        except (TypeError, ValueError, KeyError):
            return None
        offset = entry_price * value / 100.0 if cfg.get("type") == "percent" else value
        # A target is above entry for a long and below it for a short; a
        # stop is the mirror image.
        upward = favourable if is_long else not favourable
        return round(entry_price + offset if upward else entry_price - offset, 2)

    from services.place_order_service import place_order

    for kind, cfg, favourable, price_type in (
        ("stop_loss", risk.get("stop_loss"), False, "SL-M"),
        ("target", risk.get("target"), True, "LIMIT"),
    ):
        if not cfg:
            continue
        level = _level(cfg, favourable)
        if level is None or level <= 0:
            logger.warning(f"Signal Engine: invalid {kind} level for {symbol}; skipping")
            continue

        order_data = {
            "symbol": symbol,
            "exchange": exchange,
            "action": exit_side,
            "quantity": quantity,
            "pricetype": price_type,
            "product": product,
            "strategy": strategy.name,
        }
        if price_type == "LIMIT":
            order_data["price"] = level
        else:
            order_data["trigger_price"] = level

        try:
            ok, resp, _status = place_order(
                order_data=order_data, auth_token=auth_token, broker=broker,
                username=strategy.user_id,
            )
            if ok:
                logger.info(
                    f"Signal Engine: {kind} placed for {symbol} at {level} "
                    f"(entry {entry_price}, {exit_side})"
                )
            else:
                logger.error(f"Signal Engine: {kind} order rejected for {symbol}: {resp}")
        except Exception:
            logger.exception(f"Signal Engine: {kind} order raised for {symbol}")

    trailing = risk.get("trailing")
    if trailing:
        # Arm a platform-managed trailing stop. This used to only log
        # "enforced by the broker where supported", which for most Indian
        # brokers meant nothing happened at all -- the field looked
        # configured while providing zero protection. Now a real monitor
        # (services/trailing_stop_service.py) ratchets the stop and fires
        # the exit itself.
        try:
            from database.strategy_db import create_trailing_stop

            create_trailing_stop(
                username=strategy.user_id,
                symbol=symbol,
                exchange=exchange,
                quantity=quantity,
                entry_side=entry_side,
                entry_price=entry_price,
                trail_type=trailing["type"],
                trail_value=trailing["value"],
                product=product,
                broker=broker,
                strategy_id=getattr(strategy, "id", None),
                mapping_id=getattr(mapping, "id", None),
            )
        except Exception:
            logger.exception(
                f"Signal Engine: failed to arm trailing stop for {symbol} -- the "
                "position is UNPROTECTED by trailing; SL/target (if set) still apply."
            )


def _place_leg_order(strategy, leg, order_side: str, api_key: str | None) -> None:
    """Place one order for a Leg (entry or exit -- `order_side` is passed
    explicitly rather than always using leg.order_side, since an exit order
    is the OPPOSITE side of the leg's own entry order_side). Reuses the
    exact broker-resolution / order-building / notification pattern from
    _process_unified_webhook_signal -- no new order-placement code path,
    just a new caller of the same primitives, parameterized per leg instead
    of per StrategySymbolMapping row.

    Brokers: a leg group has no per-leg broker override column (unlike
    StrategySymbolMapping's execution_profile/override JSON) -- every leg
    trades on the strategy's configured broker list, resolved the same way
    every other webhook path in this file resolves it.
    """
    from database.auth_db import get_broker_session, list_broker_sessions
    from services.place_order_service import place_order

    inst_exchange = leg.exchange
    if leg.instrument_type in ("FUT", "OPT"):
        if not api_key:
            logger.error(
                f"Signal Engine: No API key available -- cannot resolve live leg "
                f"'{leg.label}' (leg {leg.id}) for strategy '{strategy.name}'."
            )
            return
        resolved = _resolve_live_instrument(leg, api_key)
        if not resolved:
            return  # failure already logged inside _resolve_live_instrument
        inst_symbol, inst_exchange = resolved
    else:
        inst_symbol = leg.instrument

    brokers = []
    if strategy.brokers:
        brokers = [b.strip() for b in strategy.brokers.split(",") if b.strip()]
    if not brokers:
        active_sessions = list_broker_sessions(strategy.user_id)
        brokers = [s["broker"] for s in active_sessions if not s.get("is_revoked")]
    if not brokers:
        brokers = ["Paper Trading"]

    for broker in brokers:
        logger.info(
            f"Signal Engine LegGroup: Placing {order_side} for leg '{leg.label}' "
            f"({inst_symbol}) on broker {broker} (qty={leg.quantity}, product={leg.product_type})"
        )

        _emit_scoped(
            "order_notification",
            {
                "symbol": inst_symbol,
                "status": "info",
                "message": f"Leg '{leg.label}': placing {order_side} order on broker '{broker}'...",
            },
            strategy.user_id,
        )

        if broker == "Paper Trading":
            time.sleep(0.5)
            import uuid

            mock_order_id = f"MOCK-{uuid.uuid4().hex[:8].upper()}"
            _emit_scoped(
                "order_event",
                {
                    "symbol": inst_symbol,
                    "action": order_side,
                    "orderid": mock_order_id,
                    "exchange": inst_exchange,
                    "price_type": "MARKET",
                    "product_type": leg.product_type,
                    "mode": "live",
                },
                strategy.user_id,
            )
            _emit_scoped(
                "order_notification",
                {
                    "symbol": inst_symbol,
                    "status": "success",
                    "message": f"Paper Trade Order {mock_order_id} filled successfully on Paper Trading.",
                },
                strategy.user_id,
            )
            continue

        session_info = get_broker_session(strategy.user_id, broker)
        if not session_info:
            err_msg = f"No active connection found for broker '{broker}'"
            logger.error(err_msg)
            _emit_scoped(
                "order_notification",
                {"symbol": inst_symbol, "status": "error", "message": f"Order failed on {broker}: {err_msg}"},
                strategy.user_id,
            )
            continue

        auth_token, feed_token, br_user_id = session_info

        order_data = {
            "symbol": inst_symbol,
            "exchange": inst_exchange,
            "action": order_side,
            "quantity": leg.quantity,
            "pricetype": "MARKET",
            "product": leg.product_type,
            "strategy": strategy.name,
        }

        # See the matching comment in _process_unified_webhook_signal: some
        # broker modules resolve their API key via os.getenv, which without
        # this context would resolve to the data broker's key instead of
        # this leg's actual target broker.
        with broker_credential_context(strategy.user_id, broker):
            place_order(
                order_data=order_data, auth_token=auth_token, broker=broker,
                username=strategy.user_id,
            )


_LEG_GROUP_ACTIONS = frozenset({"BUY", "SELL", "SHORT", "EXIT"})


def _condition_needs_api_key(node: dict | None) -> bool:
    """True if any leaf in this condition tree needs an api_key to resolve
    -- FUT/OPT instrument leaves need it via _resolve_live_instrument, and
    indicator-type leaves need it for the REST-quote fallback
    (indicator_api_key_context). The newer system-condition leaf types
    (market_open, broker_connected, signal_fresh) never need one -- a leg
    gated ONLY by those shouldn't force an unnecessary
    get_api_key_for_tradingview call. Mirrors _assert_valid_condition's
    recursive shape in blueprints/strategy.py."""
    if not node:
        return False
    if "operator" in node:
        return any(_condition_needs_api_key(child) for child in node.get("children", []))
    leaf_type = (node.get("type") or "indicator").lower()
    return leaf_type == "indicator"


def _leg_condition_met(leg, api_key: str | None, strategy, event: SignalEvent) -> bool:
    """True if `leg` has no condition attached (the default -- always
    trigger), or its condition evaluates true right now. Only ever called
    for a leg about to be OPENED (an `open`/`flip`/`target_leg`) -- a leg
    already open is always closeable regardless of what its condition says
    now; conditions gate new entries, not exits (see
    _process_leg_group_webhook_signal).

    `strategy`/`event` are threaded through to build the `context` dict
    services/condition_engine.py's newer system-condition leaf types
    (broker_connected, signal_fresh) need -- see evaluate_conditions_tree's
    docstring. Indicator-only conditions ignore `context` entirely, so this
    is purely additive for legs using only the original leaf shape.
    """
    condition = leg.get_condition()
    if not condition:
        return True

    from services.condition_engine import evaluate_conditions_tree
    from services.indicator_registry import indicator_api_key_context

    context = {"username": strategy.user_id, "signal_timestamp": event.timestamp}

    if not _condition_needs_api_key(condition):
        # Pure system-condition leaves (market_open/broker_connected/
        # signal_fresh) -- symbol/exchange are irrelevant to them, and no
        # live instrument resolution is needed. Use the leg's own exchange
        # as a harmless default for symbol/exchange (unused by these leaf
        # types beyond market_open's optional exchange override).
        return evaluate_conditions_tree(condition, leg.instrument or "", leg.exchange or "", context=context)

    if leg.instrument_type in ("FUT", "OPT"):
        if not api_key:
            logger.error(
                f"Signal Engine: No API key available -- cannot evaluate condition for leg "
                f"'{leg.label}' (leg {leg.id}). Treating condition as not met."
            )
            return False
        resolved = _resolve_live_instrument(leg, api_key)
        if not resolved:
            return False  # failure already logged inside _resolve_live_instrument
        symbol, exchange = resolved
    else:
        symbol, exchange = leg.instrument, leg.exchange

    with indicator_api_key_context(api_key):
        return evaluate_conditions_tree(condition, symbol, exchange, context=context)


def _process_leg_group_webhook_signal(strategy, event: SignalEvent):
    """Stateful multi-leg rotation webhook handler (execution_model ==
    'stateful'). Unlike the legacy/unified paths, this tracks WHICH leg is
    currently open per LegGroup (LegGroup.current_leg_id) so the same raw
    signal can mean different things depending on prior state -- e.g. a
    BUY signal opens a Call from flat, but closes a Put and opens a Call if
    a Put is already open (a reversal/flip). This is the primitive that
    powers the "CE/PE Reversal" template: BUY -> Call; SELL -> close Call,
    open Put; BUY -> close Put, open Call; ...

    Accepts the same 4-action vocabulary as the unified execution model
    (BUY/SELL/SHORT/EXIT -- see _UNIFIED_ACTIONS). SHORT is an ordinary
    tradable leg like BUY/SELL, just a distinct trigger. EXIT is special: a
    leg with entry_signal="EXIT" has no instrument of its own (see Leg's
    class docstring in database/strategy_db.py) -- when its signal arrives,
    whatever leg is currently open gets closed and the group goes flat;
    there is nothing to open.

    A leg with a `condition` attached (an optional platform indicator
    comparison, e.g. RSI > 70) only actually triggers if that condition is
    ALSO true right now, in addition to its entry_signal matching the
    incoming signal -- see _leg_condition_met. This only gates OPENING a
    leg; a currently-open leg is always closeable on its own EXIT/flip
    signal regardless of its condition (a position already taken doesn't
    become un-closeable because some indicator moved).

    State resolution (resolve_leg_rotation) and state commit
    (commit_leg_rotation) are deliberately separate DB calls -- see their
    docstrings in database/strategy_db.py -- so orders are placed BEFORE
    current_leg_id is updated. If order placement raises partway through a
    flip, the group is left showing the OLD leg as open rather than an
    already-updated state that doesn't match reality; the next signal will
    re-evaluate from that (still correct, if slightly stale) state rather
    than from corrupted state.
    """
    try:
        from database.auth_db import get_api_key_for_tradingview
        from database.strategy_db import commit_leg_rotation, get_leg_groups, resolve_leg_rotation

        logger.info(f"Signal Engine: Processing LegGroup Strategy signal '{event.signal}' for '{strategy.name}'")

        signal_action = event.signal.upper()
        if signal_action not in _LEG_GROUP_ACTIONS:
            logger.warning(
                f"Signal Engine: Unknown signal '{signal_action}' for leg-group strategy "
                f"'{strategy.name}' (expected one of {sorted(_LEG_GROUP_ACTIONS)}). Ignoring."
            )
            return

        groups = get_leg_groups(strategy.id)
        if not groups:
            logger.warning(f"Signal Engine: No leg groups configured for strategy '{strategy.name}'.")
            return

        active_groups = [g for g in groups if g.is_active]
        for g in groups:
            if not g.is_active:
                logger.info(f"Signal Engine: Skipping paused leg group '{g.name}' (id={g.id}) for strategy '{strategy.name}'")
        if not active_groups:
            return

        needs_api_key = any(
            leg.instrument_type in ("FUT", "OPT") or _condition_needs_api_key(leg.get_condition())
            for g in active_groups for leg in g.legs
        )
        api_key = get_api_key_for_tradingview(strategy.user_id) if needs_api_key else None
        if needs_api_key and not api_key:
            logger.error(
                f"Signal Engine: No API key found for user {strategy.user_id} -- cannot resolve "
                f"live Futures/Options legs or evaluate conditions for strategy '{strategy.name}'. "
                "Generate one at /apikey."
            )

        for group in active_groups:
            resolution = resolve_leg_rotation(group.id, signal_action)
            if not resolution or resolution["action"] == "no_target":
                logger.info(
                    f"Signal Engine: No leg in group '{group.name}' reacts to signal "
                    f"'{signal_action}' for strategy '{strategy.name}'."
                )
                continue

            if resolution["action"] == "noop":
                logger.info(
                    f"Signal Engine: Leg group '{group.name}' already has '{resolution['leg'].label}' "
                    f"open -- signal '{signal_action}' is a no-op."
                )
                continue

            if resolution["action"] == "exit":
                # EXIT leg's signal -- close whatever's open, go flat. No
                # condition gate: closing is always allowed.
                current_leg = resolution["current_leg"]
                exit_side = "SELL" if current_leg.order_side == "BUY" else "BUY"
                _place_leg_order(strategy, current_leg, exit_side, api_key)
                commit_leg_rotation(
                    group.id, None,
                    f"Signal '{signal_action}': closed {current_leg.label}, now flat",
                )
                continue

            if resolution["action"] == "open":
                target_leg = resolution["target_leg"]
                if not _leg_condition_met(target_leg, api_key, strategy, event):
                    logger.info(
                        f"Signal Engine: Leg group '{group.name}': condition not met for "
                        f"'{target_leg.label}' -- signal '{signal_action}' skipped."
                    )
                    continue
                _place_leg_order(strategy, target_leg, target_leg.order_side, api_key)
                commit_leg_rotation(
                    group.id, target_leg.id,
                    f"Signal '{signal_action}': opened {target_leg.label}",
                )
                continue

            # "flip": close current leg first, then open target leg -- but
            # only if the target's condition (if any) is met. The signal
            # itself is real either way, so the current leg is always
            # closed; if the target's condition fails, the group is left
            # flat rather than opening a leg whose condition says not to.
            current_leg = resolution["current_leg"]
            target_leg = resolution["target_leg"]
            exit_side = "SELL" if current_leg.order_side == "BUY" else "BUY"
            _place_leg_order(strategy, current_leg, exit_side, api_key)

            if not _leg_condition_met(target_leg, api_key, strategy, event):
                logger.info(
                    f"Signal Engine: Leg group '{group.name}': closed '{current_leg.label}' but "
                    f"condition not met for '{target_leg.label}' -- staying flat."
                )
                commit_leg_rotation(
                    group.id, None,
                    f"Signal '{signal_action}': closed {current_leg.label}, "
                    f"condition not met for {target_leg.label} -- now flat",
                )
                continue

            _place_leg_order(strategy, target_leg, target_leg.order_side, api_key)
            commit_leg_rotation(
                group.id, target_leg.id,
                f"Signal '{signal_action}': closed {current_leg.label}, opened {target_leg.label}",
            )
    except Exception as e:
        logger.exception(f"Signal Engine: Error handling leg-group webhook signal event: {e}")


def _process_deployment_signal_event(strategy, event: SignalEvent):
    """Strategy-builder deployment signal handler (condition-tree-driven
    entry/exit legs). Unmodified from before this feature's split -- see
    _process_signal_event for the dispatch that routes here vs. the
    webhook handlers above."""
    try:
        from database.auth_db import get_broker_session
        from database.token_db import get_symbol_info_dbquery
        from services.place_order_service import place_order

        # Fetch all active deployments for this strategy
        active_deployments = Deployment.query.filter(
            Deployment.strategy_id == strategy.id,
            Deployment.status.in_(["Waiting", "Managing", "Paused"])
        ).all()

        if not active_deployments:
            logger.info(f"Signal Engine: No active deployments found for strategy '{strategy.name}'.")
            return

        for dep in active_deployments:
            try:
                # Retrieve execution profile parameters
                config = dep.strategy_version.get_config()
                legs = config.get("legs", [])

                # Retrieve existing events timeline
                try:
                    timeline = json.loads(dep.events_timeline) if dep.events_timeline else []
                except Exception:
                    timeline = []

                # Signal state machine evaluations
                current_status = dep.status
                signal_action = event.signal

                is_entry_signal = signal_action in ["BUY", "SHORT"]
                is_exit_signal = signal_action in ["SELL", "EXIT", "COVER"]

                # 1. State Awareness Rules
                if current_status == "Waiting" and is_exit_signal:
                    logger.info(f"Signal Engine: Deployment '{dep.name}' is WAITING. Ignoring exit signal '{signal_action}'.")
                    continue

                if current_status == "Managing" and is_entry_signal:
                    logger.info(f"Signal Engine: Deployment '{dep.name}' is already MANAGING. Ignoring duplicate entry signal '{signal_action}'.")
                    continue

                # 2. Trigger Entry Logic
                if current_status == "Waiting" and is_entry_signal:
                    logger.info(f"Signal Engine: Processing Entry trigger for deployment: '{dep.name}'")

                    # Perform Risk Validations
                    is_safe, reason = validate_risk(dep)
                    if not is_safe:
                        logger.warning(f"Signal Engine: Risk check failed for deployment '{dep.name}': {reason}")
                        update_deployment_status(dep.id, "Error", f"Risk check failed: {reason}")
                        continue

                    # Execute Orders for Configured Legs
                    # Set status to Entering
                    update_deployment_status(dep.id, "Entering", f"Received signal '{signal_action}'. Executing orders...")

                    # Resolve multiple brokers
                    brokers = [b.strip() for b in dep.broker.split(",") if b.strip()]
                    if not brokers:
                        brokers = ["Paper Trading"]

                    for broker in brokers:
                        for leg in legs:
                            leg_symbol = leg.get("symbol")
                            logger.info(
                                f"Signal Engine: Route Order -> Broker: {broker}, Symbol: {leg_symbol}, "
                                f"Exchange: {leg.get('exchange')}, Product: {dep.product}, Side: {leg.get('side')}, "
                                f"Capital Limit: {dep.capital}"
                            )

                            # Emit order receipt notification
                            _emit_scoped(
                                "order_notification",
                                {
                                    "symbol": leg_symbol,
                                    "status": "info",
                                    "message": f"Conditions matched. Routing order for leg {leg_symbol} to broker {broker}..."
                                },
                                dep.user_id,
                            )

                            if broker == "Paper Trading":
                                # Simulate order fill
                                time.sleep(0.5)
                                import uuid
                                mock_order_id = f"MOCK-{uuid.uuid4().hex[:8].upper()}"

                                _emit_scoped(
                                    "order_event",
                                    {
                                        "symbol": leg_symbol,
                                        "action": leg.get("side"),
                                        "orderid": mock_order_id,
                                        "exchange": leg.get("exchange"),
                                        "price_type": dep.order_type.upper() if dep.order_type else "MARKET",
                                        "product_type": dep.product.upper() if dep.product else "MIS",
                                        "mode": "live",
                                    },
                                    dep.user_id,
                                )
                                _emit_scoped(
                                    "order_notification",
                                    {
                                        "symbol": leg_symbol,
                                        "status": "success",
                                        "message": f"Paper Trade Order {mock_order_id} filled successfully on Paper Trading."
                                    },
                                    dep.user_id,
                                )
                            else:
                                # Place live order
                                session_info = get_broker_session(dep.user_id, broker)
                                if not session_info:
                                    err_msg = f"No active connection found for broker '{broker}'"
                                    logger.error(err_msg)
                                    _emit_scoped(
                                        "order_notification",
                                        {
                                            "symbol": leg_symbol,
                                            "status": "error",
                                            "message": f"Order failed on {broker}: {err_msg}"
                                        },
                                        dep.user_id,
                                    )
                                    continue

                                auth_token, feed_token, br_user_id = session_info

                                # Resolve quantity using lot size
                                info = get_symbol_info_dbquery(leg_symbol, leg.get("exchange"))
                                lotsize = info.lotsize if info and hasattr(info, "lotsize") and info.lotsize else 1
                                quantity = lotsize * (leg.get("quantity") or 1)

                                order_data = {
                                    "symbol": leg_symbol,
                                    "exchange": leg.get("exchange"),
                                    "action": leg.get("side"),
                                    "quantity": quantity,
                                    # See the matching comment in the webhook-strategy
                                    # branch above: OrderSchema expects "pricetype"/
                                    # "product", not "price_type"/"product_type".
                                    "pricetype": dep.order_type.upper() if dep.order_type else "MARKET",
                                    "product": dep.product.upper() if dep.product else "MIS",
                                    "strategy": dep.name,
                                }

                                # See the matching comment in the webhook-strategy
                                # branch above: without this, a multi-broker
                                # deployment would silently place every order
                                # using the current data broker's API key.
                                with broker_credential_context(dep.user_id, broker):
                                    success, resp, status = place_order(
                                        order_data=order_data,
                                        auth_token=auth_token,
                                        broker=broker,
                                        username=dep.user_id,
                                    )

                                # No notification/verification code here --
                                # place_order() (called above) routes through
                                # place_order_with_auth, which already
                                # publishes OrderPlacedEvent ("sent to
                                # broker") on success, OrderFailedEvent on
                                # broker rejection, and already calls
                                # async_verify_order_fill itself. Duplicating
                                # any of that here used to fire a second
                                # independent verification worker + a second
                                # "sent to broker" emit for the same order,
                                # producing duplicate toasts/notifications
                                # for one outcome.

                    # Update to managing state
                    update_deployment_status(
                        dep.id,
                        "Managing",
                        f"Entry position filled. Managing position. (Signal: {signal_action})"
                    )

                    timeline.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "event": f"Signal '{signal_action}' matched. Orders placed successfully."
                    })
                    dep.events_timeline = json.dumps(timeline)
                    dep.trades_count += 1
                    db_session.commit()

                # 3. Trigger Exit Logic
                elif current_status == "Managing" and is_exit_signal:
                    logger.info(f"Signal Engine: Processing Exit trigger for deployment: '{dep.name}'")

                    update_deployment_status(dep.id, "Entering", f"Received exit signal '{signal_action}'. Closing positions...")

                    # Place closing opposite orders
                    brokers = [b.strip() for b in dep.broker.split(",") if b.strip()]
                    if not brokers:
                        brokers = ["Paper Trading"]

                    for broker in brokers:
                        for leg in legs:
                            closing_side = "SELL" if leg.get("side") == "BUY" else "BUY"
                            leg_symbol = leg.get("symbol")
                            logger.info(
                                f"Signal Engine: Close Position Order -> Broker: {broker}, Symbol: {leg_symbol}, "
                                f"Exchange: {leg.get('exchange')}, Product: {dep.product}, Side: {closing_side}"
                            )

                            # Emit order Squareoff notification
                            _emit_scoped(
                                "order_notification",
                                {
                                    "symbol": leg_symbol,
                                    "status": "info",
                                    "message": f"Exit signal received. Squaring off leg {leg_symbol} on broker {broker}..."
                                },
                                dep.user_id,
                            )

                            if broker == "Paper Trading":
                                time.sleep(0.5)
                                import uuid
                                mock_order_id = f"MOCK-{uuid.uuid4().hex[:8].upper()}"

                                _emit_scoped(
                                    "order_event",
                                    {
                                        "symbol": leg_symbol,
                                        "action": closing_side,
                                        "orderid": mock_order_id,
                                        "exchange": leg.get("exchange"),
                                        "price_type": dep.order_type.upper() if dep.order_type else "MARKET",
                                        "product_type": dep.product.upper() if dep.product else "MIS",
                                        "mode": "live",
                                    },
                                    dep.user_id,
                                )
                                _emit_scoped(
                                    "order_notification",
                                    {
                                        "symbol": leg_symbol,
                                        "status": "success",
                                        "message": f"Paper Squareoff Order {mock_order_id} filled successfully on Paper Trading."
                                    },
                                    dep.user_id,
                                )
                            else:
                                session_info = get_broker_session(dep.user_id, broker)
                                if not session_info:
                                    err_msg = f"No active connection found for broker '{broker}'"
                                    logger.error(err_msg)
                                    _emit_scoped(
                                        "order_notification",
                                        {
                                            "symbol": leg_symbol,
                                            "status": "error",
                                            "message": f"Square-off failed on {broker}: {err_msg}"
                                        },
                                        dep.user_id,
                                    )
                                    continue

                                auth_token, feed_token, br_user_id = session_info

                                # Resolve quantity using lot size
                                info = get_symbol_info_dbquery(leg_symbol, leg.get("exchange"))
                                lotsize = info.lotsize if info and hasattr(info, "lotsize") and info.lotsize else 1
                                quantity = lotsize * (leg.get("quantity") or 1)

                                order_data = {
                                    "symbol": leg_symbol,
                                    "exchange": leg.get("exchange"),
                                    "action": closing_side,
                                    "quantity": quantity,
                                    # See the matching comment on the entry-order
                                    # order_data above: OrderSchema expects
                                    # "pricetype"/"product", not "price_type"/
                                    # "product_type".
                                    "pricetype": dep.order_type.upper() if dep.order_type else "MARKET",
                                    "product": dep.product.upper() if dep.product else "MIS",
                                    "strategy": dep.name,
                                }

                                # See the matching comment on the entry-order
                                # place_order call above: without this, a
                                # multi-broker deployment's square-off orders
                                # would silently use the data broker's API key.
                                with broker_credential_context(dep.user_id, broker):
                                    success, resp, status = place_order(
                                        order_data=order_data,
                                        auth_token=auth_token,
                                        broker=broker,
                                        username=dep.user_id,
                                    )

                                # No notification/verification code here --
                                # place_order() (called above) routes through
                                # place_order_with_auth, which already
                                # publishes OrderPlacedEvent ("sent to
                                # broker") on success, OrderFailedEvent on
                                # broker rejection, and already calls
                                # async_verify_order_fill itself. Duplicating
                                # any of that here used to fire a second
                                # independent verification worker + a second
                                # "sent to broker" emit for the same order,
                                # producing duplicate toasts/notifications
                                # for one outcome.

                    # Transition status back to Waiting
                    update_deployment_status(
                        dep.id,
                        "Waiting",
                        f"Positions closed successfully. Waiting for next signal. (Signal: {signal_action})"
                    )

                    timeline.append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "event": f"Signal '{signal_action}' exit matched. Positions squared off."
                    })
                    dep.events_timeline = json.dumps(timeline)
                    db_session.commit()

            except Exception as e:
                logger.error(f"Signal Engine: Error processing deployment {dep.id}: {e}")
                update_deployment_status(dep.id, "Error", f"Error in processing signal: {str(e)}")

    except Exception as e:
        logger.error(f"Signal Engine: Error handling signal event: {e}")


# In-flight (future, event, submitted_at) tuples, watched by _timeout_reaper_loop.
# Not the dispatch pool itself -- just bookkeeping so a stuck future can be
# flagged without any thread blocking on another pool thread's result (that
# would risk deadlocking the pool once all workers are simultaneously stuck
# waiting on each other).
_inflight_lock = threading.Lock()
_inflight = []


def _on_signal_done(event: SignalEvent, future):
    """Callback fired by the executor when a signal finishes (success or error)."""
    with _inflight_lock:
        _inflight[:] = [item for item in _inflight if item[0] is not future]
    exc = future.exception()
    if exc:
        logger.error(f"Signal Engine: Dispatch for signal '{event.signal}' raised: {exc}")


def _timeout_reaper_loop():
    """Watches in-flight futures and emits a notification if one runs too long.

    Does not (and cannot) kill the underlying thread -- Python offers no way
    to force-terminate a thread stuck in a blocking network call. What this
    achieves is purely user-facing: the signal is no longer silently dropped,
    and the pool keeps accepting new signals from _worker_loop regardless
    (each signal has its own worker slot, so one hang doesn't block others
    unless all _SIGNAL_DISPATCH_WORKERS slots are simultaneously stuck).
    """
    global _worker_running
    logger.info("Signal Engine timeout-reaper loop started.")
    while _worker_running:
        try:
            time.sleep(2.0)
            now = time.time()
            with _inflight_lock:
                snapshot = list(_inflight)
            for future, event, submitted_at, notified in snapshot:
                if future.done() or notified:
                    continue
                if now - submitted_at < _SIGNAL_PROCESSING_TIMEOUT_SECONDS:
                    continue
                logger.error(
                    f"Signal Engine: Processing signal '{event.signal}' for webhook "
                    f"{event.webhook_id} exceeded {_SIGNAL_PROCESSING_TIMEOUT_SECONDS}s "
                    "(likely a hung broker API call). Still running in the background; "
                    "other signals are not blocked."
                )
                try:
                    strategy = get_strategy_by_webhook_id(event.webhook_id)
                    _emit_scoped(
                        "order_notification",
                        {
                            "status": "error",
                            "message": (
                                f"Signal '{event.signal}' is taking longer than "
                                f"{_SIGNAL_PROCESSING_TIMEOUT_SECONDS}s waiting on the broker. "
                                "It may not have been placed -- check the broker/orderbook."
                            ),
                        },
                        strategy.user_id if strategy else None,
                    )
                except Exception:
                    pass
                with _inflight_lock:
                    for i, item in enumerate(_inflight):
                        if item[0] is future:
                            _inflight[i] = (future, event, submitted_at, True)
                            break
        except Exception as e:
            # This loop must never die: it's the only thing that can still
            # notify the user when a signal is stuck. A single bad iteration
            # (e.g. a malformed event) must not silently kill the thread and
            # leave every future timeout undetected for the rest of the process.
            logger.error(f"Signal Engine reaper loop encountered an error: {e}")


def _worker_loop():
    global _worker_running
    logger.info("Signal Engine worker loop started.")
    while _worker_running:
        try:
            event = signal_queue.get(timeout=1.0)
            if event:
                # Dispatch onto the bounded pool instead of processing inline --
                # a slow/hung broker call must not stall this dequeue loop, or
                # every subsequent webhook signal for every strategy queues up
                # behind it indefinitely.
                future = _dispatch_executor.submit(_process_signal_event, event)
                with _inflight_lock:
                    _inflight.append((future, event, time.time(), False))
                future.add_done_callback(lambda f, e=event: _on_signal_done(e, f))
                signal_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Signal Engine worker thread encountered error: {e}")


def start_signal_engine():
    """
    Starts the background worker thread and timeout-reaper thread for
    asynchronous signal dispatching.
    """
    global _worker_thread, _reaper_thread, _worker_running
    if _worker_running:
        return

    _worker_running = True
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True)
    _worker_thread.start()
    _reaper_thread = threading.Thread(target=_timeout_reaper_loop, daemon=True)
    _reaper_thread.start()
    logger.info("Signal Engine service started.")


def stop_signal_engine():
    """
    Stops the background worker and reaper threads, and shuts down the
    signal-dispatch pool. wait=False: in-flight broker calls are daemon
    threads under the pool and the process is exiting anyway, so we don't
    block shutdown waiting on a potentially-hung broker call.
    """
    global _worker_running
    _worker_running = False
    if _worker_thread:
        _worker_thread.join(timeout=2.0)
    if _reaper_thread:
        _reaper_thread.join(timeout=3.0)
    _dispatch_executor.shutdown(wait=False)
    logger.info("Signal Engine service stopped.")
