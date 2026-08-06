"""Kill switch cleanup orchestrator.

See docs/plans/2026-04-24-kill-switch-implementation-plan.md for the full
design. This module is internal-only -- not exposed directly as an API
route. blueprints/killswitch.py (REST) is the only caller.

Cleanup calls the SAME order-cancel/position-close service functions that
"Cancel All"/"Close All" buttons already use elsewhere in the UI, rather
than talking to broker APIs directly, so kill-switch cleanup gets the exact
same live/sandbox routing, error handling, and event emission those paths
already have.
"""

import json
from typing import Any

from database.auth_db import Auth, get_auth_token, get_broker_session, list_broker_sessions
from database.settings_db import (
    get_kill_switch_scope,
    get_kill_switch_state,
    record_kill_switch_audit,
    set_kill_switch,
)
from utils.logging import get_logger
from utils.socket_scope import emit_to_user

logger = get_logger(__name__)


def _get_legacy_single_user() -> str | None:
    """Legacy last-resort identity: the first non-revoked `auth` row.

    Correct only on a single-user install. Kept solely as a fallback for
    callers that supply no identity at all (e.g. an old scripted
    integration), because returning None there would silently turn the
    panic button into a no-op on exactly the deployments that relied on
    this behaviour. Every real caller now passes `actor_id`.
    """
    row = Auth.query.filter_by(is_revoked=False).first()
    return row.name if row else None


def _get_acting_username(actor_type: str, actor_id: str | None) -> str | None:
    """Resolve WHICH ACCOUNT this kill-switch operation acts on.

    Prefers, in order:
      1. `actor_id` -- blueprints/killswitch.py always resolves this from
         the authenticated session cookie or the supplied apikey, so it is
         the real, verified identity of the caller for both UI and
         programmatic presses,
      2. the live Flask session / active user_scope,
      3. the legacy single-row lookup (see above).

    This drives cleanup as well as notification, so getting it wrong means
    flattening the wrong person's positions -- hence preferring the
    authenticated caller over any ambient global state.
    """
    if actor_id:
        return actor_id

    from utils.socket_scope import resolve_current_username

    username = resolve_current_username()
    if username:
        return username
    return _get_legacy_single_user()


def _get_connected_broker_sessions(username: str) -> list[tuple[str, str]]:
    """Resolve every ACTIVELY connected (broker, auth_token) pair for this
    user, across BOTH broker-session sources this platform has:
      - the legacy singleton `Auth` table (the current "data broker" --
        every install has exactly one of these; may or may not also have
        a matching AuthBrokerSession row)
      - `AuthBrokerSession` (additional brokers connected via the
        multi-broker flow -- see database/auth_db.py, Broker Management
        page)
    Deduplicated by broker name so a broker present in both sources is
    only cleaned up once. Mirrors the fan-out pattern already used by
    services/multi_broker_order_service.py.
    """
    brokers_seen: dict[str, str] = {}  # broker -> auth_token

    auth_row = Auth.query.filter_by(name=username, is_revoked=False).first()
    if auth_row:
        auth_token = get_auth_token(username)
        if auth_token:
            brokers_seen[auth_row.broker] = auth_token

    for session_info in list_broker_sessions(username):
        broker = session_info["broker"]
        if session_info["is_revoked"] or broker in brokers_seen:
            continue
        resolved = get_broker_session(username, broker)
        if resolved:
            auth_token, _feed_token, _user_id = resolved
            brokers_seen[broker] = auth_token

    return list(brokers_seen.items())


def _qty(p: dict) -> float:
    # Quantity field name varies by broker mapping (quantity/qty/netqty/
    # net_qty) -- this count only feeds the audit-log display, never the
    # actual close operation, so best-effort across the known variants is
    # acceptable rather than betting on one name.
    for field in ("quantity", "qty", "netqty", "net_qty"):
        if field in p:
            try:
                return float(p[field] or 0)
            except (TypeError, ValueError):
                continue
    return 0


def _cleanup_live_orders_and_positions(username: str) -> dict[str, Any]:
    """Cancel all live pending orders and close all live open positions,
    across EVERY actively connected broker (not just the current data
    broker -- see _get_connected_broker_sessions). Returns
    partial-success-safe counts; broker errors are caught and logged,
    never raised, since one broker being unreachable must not stop
    cleanup on the others or the rest of the kill-switch sequence."""
    result = {
        "live_orders_cancelled": 0,
        "live_orders_failed": 0,
        "live_positions_closed": 0,
        "live_notes": [],
    }

    scope = get_kill_switch_scope(username)
    if not scope["cancel_orders_enabled"] and not scope["close_positions_enabled"]:
        result["live_notes"].append("Order cancellation and position closing disabled in kill switch settings.")
        return result

    broker_sessions = _get_connected_broker_sessions(username)
    if not broker_sessions:
        result["live_notes"].append("No active broker session -- live cleanup skipped.")
        return result

    from services.cancel_all_order_service import cancel_all_orders
    from services.close_position_service import close_position
    from services.positionbook_service import get_positionbook
    from utils.broker_context import broker_credential_context

    for broker, auth_token in broker_sessions:
        with broker_credential_context(username, broker):
            if scope["cancel_orders_enabled"]:
                try:
                    success, response, _status = cancel_all_orders(
                        auth_token=auth_token, broker=broker, username=username
                    )
                    if success and isinstance(response, dict):
                        result["live_orders_cancelled"] += len(response.get("canceled_orders", []) or [])
                        result["live_orders_failed"] += len(response.get("failed_cancellations", []) or [])
                    elif not success:
                        result["live_notes"].append(f"[{broker}] cancel_all_orders failed: {response}")
                except Exception as e:
                    logger.exception(f"Kill switch: live order cancellation raised for {broker}: {e}")
                    result["live_notes"].append(f"[{broker}] cancel_all_orders raised: {e}")
            else:
                result["live_notes"].append(f"[{broker}] order cancellation disabled in kill switch settings.")

            if not scope["close_positions_enabled"]:
                result["live_notes"].append(f"[{broker}] position closing disabled in kill switch settings.")
                continue

            # close_position()'s response has no count field (just a flat
            # success/message) -- count open positions ourselves beforehand
            # so the audit log reports a real number instead of a
            # fabricated one.
            open_position_count = 0
            try:
                pb_success, pb_response, _pb_status = get_positionbook(auth_token=auth_token, broker=broker)
                if pb_success and isinstance(pb_response, dict):
                    positions = pb_response.get("data", []) or []
                    open_position_count = len([p for p in positions if _qty(p) != 0])
            except Exception as e:
                logger.exception(f"Kill switch: failed to count open positions before close for {broker}: {e}")

            try:
                success, response, _status = close_position(
                    auth_token=auth_token, broker=broker, username=username
                )
                if success:
                    result["live_positions_closed"] += open_position_count
                else:
                    result["live_notes"].append(f"[{broker}] close_position failed: {response}")
            except Exception as e:
                logger.exception(f"Kill switch: live position close raised for {broker}: {e}")
                result["live_notes"].append(f"[{broker}] close_position raised: {e}")

    return result


def _cleanup_sandbox_orders_and_positions(username: str | None) -> dict[str, Any]:
    """Cancel all sandbox pending orders and close all sandbox open
    positions. Runs unconditionally regardless of whether analyze_mode is
    currently on -- the user may flip into sandbox mode between activation
    and deactivation (see plan section 8). Sandbox is API-key-scoped per
    user, not per-broker, so this stays a single call (no per-broker loop
    needed here unlike the live cleanup above)."""
    result = {
        "sandbox_orders_cancelled": 0,
        "sandbox_positions_closed": 0,
        "sandbox_notes": [],
    }

    scope = get_kill_switch_scope(username)
    if not scope["cancel_orders_enabled"] and not scope["close_positions_enabled"]:
        result["sandbox_notes"].append("Order cancellation and position closing disabled in kill switch settings.")
        return result

    api_key = None
    if username:
        from database.auth_db import get_api_key_for_tradingview

        api_key = get_api_key_for_tradingview(username)

    if not api_key:
        result["sandbox_notes"].append("No API key resolved -- sandbox cleanup skipped.")
        return result

    from services.sandbox_service import sandbox_cancel_all_orders, sandbox_close_position

    if scope["cancel_orders_enabled"]:
        try:
            success, response, _status = sandbox_cancel_all_orders({}, api_key, {})
            if success:
                result["sandbox_orders_cancelled"] = len(response.get("canceled_orders", []) or [])
            else:
                result["sandbox_notes"].append(f"sandbox_cancel_all_orders failed: {response}")
        except Exception as e:
            logger.exception(f"Kill switch: sandbox order cancellation raised: {e}")
            result["sandbox_notes"].append(f"sandbox_cancel_all_orders raised: {e}")
    else:
        result["sandbox_notes"].append("Order cancellation disabled in kill switch settings.")

    if not scope["close_positions_enabled"]:
        result["sandbox_notes"].append("Position closing disabled in kill switch settings.")
        return result

    try:
        success, response, _status = sandbox_close_position({}, api_key, {})
        if success:
            result["sandbox_positions_closed"] = response.get("closed_positions", 0) or 0
        else:
            result["sandbox_notes"].append(f"sandbox_close_position failed: {response}")
    except Exception as e:
        logger.exception(f"Kill switch: sandbox position close raised: {e}")
        result["sandbox_notes"].append(f"sandbox_close_position raised: {e}")

    return result


def _stop_all_python_strategies(username: str | None = None) -> dict[str, Any]:
    """Halt `username`'s currently-running hosted Python strategy
    processes. Does NOT mark strategies as disabled -- only stopped. They
    do not auto-resume on kill-switch deactivation (explicit manual restart
    required, per plan section 9.1).

    Scoped by owner: this previously stopped EVERY running strategy on the
    instance, so one user's panic button killed other users' live trading
    strategies. Strategies whose owner cannot be determined (legacy configs
    with no user_id) are left running rather than stopped, since stopping
    someone else's strategy is the more harmful error.
    """
    result = {"strategies_stopped": 0, "strategy_notes": []}

    try:
        from blueprints.python_strategy import (
            RUNNING_STRATEGIES,
            STRATEGY_CONFIGS,
            stop_strategy_process,
        )

        strategy_ids = list(RUNNING_STRATEGIES.keys())
        for strategy_id in strategy_ids:
            owner = (STRATEGY_CONFIGS.get(strategy_id) or {}).get("user_id")
            if username and owner != username:
                result["strategy_notes"].append(
                    f"{strategy_id}: skipped (owned by another user)"
                )
                continue
            try:
                success, message = stop_strategy_process(strategy_id)
                if success:
                    result["strategies_stopped"] += 1
                else:
                    result["strategy_notes"].append(f"{strategy_id}: {message}")
            except Exception as e:
                logger.exception(f"Kill switch: failed to stop strategy {strategy_id}: {e}")
                result["strategy_notes"].append(f"{strategy_id}: {e}")
    except Exception as e:
        logger.exception(f"Kill switch: python strategy cleanup raised: {e}")
        result["strategy_notes"].append(f"python strategy cleanup raised: {e}")

    return result


def _abort_all_active_flows() -> dict[str, Any]:
    """Flows already executing at activation moment cannot be forcibly
    killed mid-node (there's no subprocess to terminate -- execute_workflow
    runs inline). They will naturally hit the kill-switch gate at the next
    order-placing service call. This function's job is narrower: count
    currently-in-flight workflow locks so the audit log reflects how many
    were caught mid-run, and new invocations are blocked at
    execute_workflow's own top-of-function check (added separately)."""
    result = {"flows_aborted": 0, "flow_notes": []}

    try:
        from services.flow_executor_service import _locks_mutex, _workflow_locks

        with _locks_mutex:
            in_flight = [wf_id for wf_id, lock in _workflow_locks.items() if lock.locked()]
        result["flows_aborted"] = len(in_flight)
        if in_flight:
            result["flow_notes"].append(
                f"Workflows in-flight at activation (will hit order gate): {in_flight}"
            )
    except Exception as e:
        logger.exception(f"Kill switch: flow cleanup accounting raised: {e}")
        result["flow_notes"].append(f"flow cleanup accounting raised: {e}")

    return result


def activate_kill_switch(actor_type: str, actor_id: str | None, reason: str | None) -> dict:
    """One-shot panic button: cancel every order, close every position
    (live + sandbox), stop every strategy/flow -- then IMMEDIATELY reset
    back to inactive. This is deliberately NOT a persistent "block all
    future orders" toggle: a trader pressing this during a market crash
    wants the platform flattened right now, not locked out of trading for
    an indeterminate stretch afterward with a separate deactivate step to
    remember. See deactivate_kill_switch below, which now only exists to
    clear a switch that got stuck active (e.g. a crash mid-cleanup) rather
    than being part of the normal flow.

    While cleanup is running, kill_switch_active is set True so
    enforce_kill_switch blocks any order that races the cleanup itself
    (e.g. a webhook signal arriving mid-flatten) -- it's flipped back to
    False only after cleanup finishes, not before.

    Idempotent against overlapping presses: if already active (mid-cleanup
    from a concurrent call), returns the current state with
    already_active=True and does NOT re-run cleanup -- set_kill_switch uses
    SELECT...FOR UPDATE so a concurrent second call can't race the flag
    write itself.
    """
    # The acting user. This is the single identity the whole activation
    # operates on: whose flag is set, whose brokers get flattened, whose
    # strategies are stopped, and whose browser is notified.
    #
    # Previously cleanup ran against `_get_current_username()` -- literally
    # `Auth.query.filter_by(is_revoked=False).first()` -- so on a
    # multi-user instance User A pressing the panic button could cancel
    # orders and close real positions in User B's broker account. The
    # identity now comes from the authenticated caller
    # (blueprints/killswitch.py resolves it from the session cookie or the
    # apikey), and only falls back to the legacy lookup when the caller
    # supplied nothing at all.
    username = _get_acting_username(actor_type, actor_id)
    if not username:
        return {
            "kill_switch_active": False,
            "error": "Could not resolve the acting user -- kill switch not activated.",
            "already_active": False,
            "cleanup_summary": {},
        }

    if get_kill_switch_state(username)["kill_switch_active"]:
        state = get_kill_switch_state(username)
        state["already_active"] = True
        return state

    state = set_kill_switch(username, True, actor_type, actor_id, reason)

    # Notifications land only in this user's own browser. These were bare
    # broadcasts, which meant one user hitting the panic button showed
    # "KILL SWITCH ACTIVATED" (and the full cleanup summary: order counts,
    # position counts, strategy names) in every other logged-in user's UI,
    # implying their own trading had been halted when it had not.
    emit_username = username

    try:
        emit_to_user(
            "kill_switch_activated",
            {
                "activated_at": state["activated_at"],
                "activated_by": state["activated_by"],
                "reason": state["reason"],
            },
            emit_username,
        )
    except Exception as e:
        logger.exception(f"Kill switch: failed to emit activation event: {e}")

    live = _cleanup_live_orders_and_positions(username)
    sandbox = _cleanup_sandbox_orders_and_positions(username)
    strategies = _stop_all_python_strategies(username)
    flows = _abort_all_active_flows()

    notes = {
        "live_notes": live["live_notes"],
        "sandbox_notes": sandbox["sandbox_notes"],
        "strategy_notes": strategies["strategy_notes"],
        "flow_notes": flows["flow_notes"],
    }

    cleanup_summary = {
        "live_orders_cancelled": live["live_orders_cancelled"],
        "live_orders_failed": live["live_orders_failed"],
        "live_positions_closed": live["live_positions_closed"],
        "sandbox_orders_cancelled": sandbox["sandbox_orders_cancelled"],
        "sandbox_positions_closed": sandbox["sandbox_positions_closed"],
        "strategies_stopped": strategies["strategies_stopped"],
        "flows_aborted": flows["flows_aborted"],
    }

    record_kill_switch_audit(
        username=username,
        event_type="activated",
        actor_type=actor_type,
        actor_id=actor_id,
        reason=reason,
        notes=json.dumps(notes),
        **cleanup_summary,
    )

    try:
        emit_to_user(
            "kill_switch_cleanup_complete",
            {"cleanup_summary": cleanup_summary},
            emit_username,
        )
    except Exception as e:
        logger.exception(f"Kill switch: failed to emit cleanup-complete event: {e}")

    # Auto-reset -- cleanup is done, so the emergency is over. Leaving
    # kill_switch_active=True here would silently block every order the
    # trader places for the rest of the day until they remember to come
    # back and turn it off. record_kill_switch_audit above already logged
    # the "activated" event with the full cleanup summary, so there is a
    # permanent record of the panic-button press even though the live flag
    # itself doesn't stay set.
    set_kill_switch(username, False, actor_type, actor_id, None)
    record_kill_switch_audit(
        username=username,
        event_type="deactivated",
        actor_type="system",
        actor_id=None,
        reason="auto-reset after cleanup",
    )

    try:
        emit_to_user(
            "kill_switch_deactivated",
            {"deactivated_by": "system", "reason": "auto-reset after cleanup"},
            emit_username,
        )
    except Exception as e:
        logger.exception(f"Kill switch: failed to emit auto-reset deactivation event: {e}")

    state = get_kill_switch_state(username)
    state["kill_switch_active"] = False
    state["cleanup_summary"] = cleanup_summary
    state["already_active"] = False
    return state


def deactivate_kill_switch(actor_type: str, actor_id: str | None) -> dict:
    """Deactivate the acting user's OWN kill switch. The REST endpoint caller
    is responsible for validating the min-unlock window and UNLOCK
    confirmation BEFORE calling this -- this function just performs the flip
    once those checks have already passed."""
    username = _get_acting_username(actor_type, actor_id)
    if not username:
        return {
            "kill_switch_active": False,
            "error": "Could not resolve the acting user -- kill switch not deactivated.",
        }

    state = set_kill_switch(username, False, actor_type, actor_id, None)

    record_kill_switch_audit(
        username=username,
        event_type="deactivated",
        actor_type=actor_type,
        actor_id=actor_id,
        reason=None,
    )

    try:
        emit_to_user(
            "kill_switch_deactivated",
            {"deactivated_at": state.get("activated_at"), "deactivated_by": actor_type},
            username,
        )
    except Exception as e:
        logger.exception(f"Kill switch: failed to emit deactivation event: {e}")

    return state
