"""Master Target / Master SL monitor.

Account-wide combined P&L auto-exit for scalpers running multiple
simultaneous positions. Every tick, sums the normalized `pnl` field (see
each broker's mapping/order_data.py::transform_positions_data) across every
OPEN position on every actively connected LIVE broker, and closes everything
the moment the combined total crosses either the configured SL (loss) or
target (profit) threshold.

Deliberately narrow scope for V1 (see docs/plans/2026-02-06-strategy-risk-
management-prd.md for the full per-leg/combined risk-engine design this is
NOT attempting to replace):
  - Live positions only, no sandbox -- sandbox already has its own
    capital/leverage controls (see blueprints/sandbox.py) and mixing the two
    P&L sources into one threshold would misrepresent real risk.
  - Account-wide, not per-strategy -- there is no strategy-position linkage
    to key off yet (that's exactly what the PRD's StrategyPosition table
    would add). This monitors ALL open positions across the account.
  - Reuses the exact same close-everything mechanism as the kill switch
    (services/kill_switch_service.py's per-broker close_position() loop)
    rather than a new position-tracking layer.

Runs on its own BackgroundScheduler singleton, same convention as
services/historify_scheduler_service.py and services/flow_scheduler_service.py
-- each polling job on the platform gets its own scheduler instance rather
than being forced onto an unrelated service's cadence.
"""

import json
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from database.auth_db import Auth, get_auth_token, get_broker_session, list_broker_sessions
from database.market_calendar_db import is_market_open
from database.settings_db import (
    get_master_risk_settings,
    list_enabled_master_risk_users,
    record_master_risk_audit,
    record_master_risk_trigger,
)
from utils.logging import get_logger

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 5
JOB_ID = "master_risk_monitor_tick"

_scheduler: BackgroundScheduler | None = None


def _get_current_username() -> str | None:
    """Resolve the requesting user for on-demand (request-bound) reads.

    Used only by get_current_combined_pnl below, which serves the UI's live
    P&L widget from inside a Flask request -- so the session identity is
    both available and correct. The monitor loop itself no longer uses this:
    it iterates every armed user explicitly (see _check_and_trigger), since
    a background tick has no session and must not guess.

    Falls back to the legacy first-non-revoked-row lookup only when there is
    no session at all, preserving single-user installs' behaviour.
    """
    from utils.socket_scope import resolve_current_username

    username = resolve_current_username()
    if username:
        return username
    row = Auth.query.filter_by(is_revoked=False).first()
    return row.name if row else None


def _get_connected_broker_sessions(username: str) -> list[tuple[str, str]]:
    """Every actively connected (broker, auth_token) pair for this user,
    deduplicated by broker name. Identical to
    kill_switch_service.py::_get_connected_broker_sessions -- kept as its
    own copy rather than a shared import since the two call sites have no
    other coupling and duplicating one small helper is cheaper than adding
    a cross-service dependency for it."""
    brokers_seen: dict[str, str] = {}

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
    """Same best-effort field-name fallback as kill_switch_service.py --
    quantity field name varies by broker mapping."""
    for field in ("quantity", "qty", "netqty", "net_qty"):
        if field in p:
            try:
                return float(p[field] or 0)
            except (TypeError, ValueError):
                continue
    return 0


def _get_combined_open_pnl(username: str) -> tuple[float, int, list[tuple[str, str]]]:
    """Sum `pnl` across every open position on every connected live broker.
    Returns (combined_pnl, open_position_count, broker_sessions) -- the
    broker session list is returned too so the caller doesn't have to
    re-resolve it when a trigger fires and positions need closing."""
    from services.positionbook_service import get_positionbook

    broker_sessions = _get_connected_broker_sessions(username)
    combined_pnl = 0.0
    open_count = 0

    for broker, auth_token in broker_sessions:
        try:
            success, response, _status = get_positionbook(auth_token=auth_token, broker=broker)
            if not success or not isinstance(response, dict):
                continue
            positions = response.get("data", []) or []
            for p in positions:
                if _qty(p) == 0:
                    continue
                open_count += 1
                try:
                    combined_pnl += float(p.get("pnl", 0) or 0)
                except (TypeError, ValueError):
                    continue
        except Exception as e:
            logger.exception(f"Master risk monitor: failed to fetch positions for {broker}: {e}")

    return combined_pnl, open_count, broker_sessions


def _close_all_positions(
    username: str, broker_sessions: list[tuple[str, str]]
) -> tuple[int, list[str]]:
    """Close every open position across every connected live broker.
    Mirrors kill_switch_service.py's live-cleanup loop exactly (same
    close_position() call, same broker_credential_context scoping) but
    limited to position closing -- Master SL/Target does not cancel pending
    orders, since a scalper's resting limit orders are a separate,
    deliberate decision from "get me out of what's already open."""
    from services.close_position_service import close_position
    from utils.broker_context import broker_credential_context

    closed_count = 0
    notes: list[str] = []

    for broker, auth_token in broker_sessions:
        with broker_credential_context(username, broker):
            try:
                success, response, _status = close_position(auth_token=auth_token, broker=broker)
                if success:
                    closed_count += 1
                    notes.append(f"[{broker}] closed")
                else:
                    notes.append(f"[{broker}] close_position failed: {response}")
            except Exception as e:
                logger.exception(f"Master risk monitor: close_position raised for {broker}: {e}")
                notes.append(f"[{broker}] close_position raised: {e}")

    return closed_count, notes


def _emit_trigger_events(
    reason: str, combined_pnl: float, threshold: float, username: str | None = None
) -> None:
    """Notify the monitored user that their Master SL/Target fired.

    Scoped to `username` -- this runs on an APScheduler thread with no
    Flask session, and as a bare broadcast it told EVERY logged-in user
    that their master stop-loss had triggered and their positions were
    closed, including the triggering user's live P&L figure. Dropped
    rather than broadcast if the user can't be resolved.
    """
    try:
        from utils.socket_scope import emit_to_user

        emit_to_user(
            "master_risk_triggered",
            {"reason": reason, "combined_pnl": combined_pnl, "threshold": threshold},
            username,
        )
    except Exception as e:
        logger.exception(f"Master risk monitor: failed to emit trigger event: {e}")


def _check_and_trigger_for_user(username: str) -> None:
    """Evaluate one user's own thresholds against their own positions.

    Raises nothing to the caller's loop -- see _check_and_trigger.
    """
    settings = get_master_risk_settings(username)
    if not settings["enabled"]:
        return
    if settings["sl_value"] is None and settings["target_value"] is None:
        return

    combined_pnl, open_count, broker_sessions = _get_combined_open_pnl(username)
    if open_count == 0:
        return

    reason: str | None = None
    threshold: float | None = None
    sl_value = settings["sl_value"]
    target_value = settings["target_value"]

    if sl_value is not None and combined_pnl <= -abs(sl_value):
        reason, threshold = "sl", sl_value
    elif target_value is not None and combined_pnl >= abs(target_value):
        reason, threshold = "target", target_value

    if reason is None:
        return

    logger.warning(
        f"Master risk monitor: {reason.upper()} triggered for user '{username}' -- "
        f"combined P&L {combined_pnl:.2f} crossed threshold {threshold:.2f}. "
        "Closing all positions."
    )

    # Disable monitoring FIRST (before closing) so a slow broker
    # response can't let a second tick fire the same trigger again
    # mid-close.
    record_master_risk_trigger(username, reason, combined_pnl)

    closed_count, notes = _close_all_positions(username, broker_sessions)

    record_master_risk_audit(
        username=username,
        reason=reason,
        combined_pnl_at_trigger=combined_pnl,
        threshold_value=threshold,
        positions_closed=closed_count,
        notes=json.dumps(notes),
    )

    _emit_trigger_events(reason, combined_pnl, threshold, username)


def _check_and_trigger() -> None:
    """One monitor tick, evaluated independently for EVERY user who has
    master-risk monitoring armed.

    Previously this read the single global settings row and resolved the
    account via `Auth.query.filter_by(is_revoked=False).first()`, so on a
    multi-user instance one trader's SL threshold was applied to whichever
    account happened to come back first -- closing real positions in
    someone else's broker account. Each user is now evaluated against their
    own thresholds, their own positions, and their own brokers.

    Never raises -- APScheduler would otherwise drop the job on an uncaught
    exception, silently disabling the whole feature until the next app
    restart. One user's failure must not stop the others being checked, so
    each user is additionally wrapped individually.
    """
    try:
        if not is_market_open():
            return

        for username in list_enabled_master_risk_users():
            try:
                _check_and_trigger_for_user(username)
            except Exception as e:
                logger.exception(
                    f"Master risk monitor: tick failed for user '{username}': {e}"
                )

    except Exception as e:
        logger.exception(f"Master risk monitor: tick raised unexpectedly: {e}")


def start_master_risk_monitor() -> None:
    """Start the background polling job. Idempotent -- safe to call
    multiple times (e.g. dev server autoreload)."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.debug("Master risk monitor: already running, skipping re-start")
        return

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _check_and_trigger,
        trigger=IntervalTrigger(seconds=POLL_INTERVAL_SECONDS),
        id=JOB_ID,
        replace_existing=True,
        max_instances=1,  # never let a slow tick overlap the next one
        coalesce=True,
    )
    _scheduler.start()
    logger.info(f"Master risk monitor: started (polling every {POLL_INTERVAL_SECONDS}s)")


def stop_master_risk_monitor() -> None:
    """Stop the background polling job. Called from app.py's shutdown path
    -- see FD/thread hygiene note in CLAUDE.md; an un-joined
    BackgroundScheduler thread is exactly the kind of leak that
    accumulates across dev-server autoreloads."""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception as e:
            logger.debug(f"Master risk monitor: shutdown raised (likely already stopped): {e}")
        _scheduler = None


def get_current_combined_pnl() -> dict[str, Any]:
    """On-demand snapshot for the UI's live combined-P&L display -- does
    NOT check thresholds or trigger anything, just reports the same number
    the monitor loop would compute on its next tick."""
    username = _get_current_username()
    if not username:
        return {"combined_pnl": 0.0, "open_positions": 0}
    combined_pnl, open_count, _sessions = _get_combined_open_pnl(username)
    return {"combined_pnl": combined_pnl, "open_positions": open_count}
