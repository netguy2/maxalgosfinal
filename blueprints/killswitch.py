"""Kill switch REST API -- platform-level emergency stop.

See docs/plans/2026-04-24-kill-switch-implementation-plan.md for the full
design. Accepts EITHER a valid Flask session cookie (dashboard UI) OR an
`apikey` in the JSON body (Swagger/programmatic/scripted use) -- this
mirrors how the rest of /api/v1/ resolves identity, except kill-switch
routes stay reachable even for an otherwise-gated (e.g. unsubscribed)
session, since an emergency stop must never be something a billing issue
can lock a user out of (see utils/session.py's _SUBSCRIPTION_EXEMPT_PREFIXES).

Deliberately NOT gated by @check_session_validity (which redirects
unauthenticated browser requests to /login instead of returning JSON, and
enforces subscription status) -- this module does its own lightweight
identity resolution instead so both auth paths return clean JSON.
"""

import os
from datetime import UTC, datetime, timezone

from flask import Blueprint, jsonify, request, session

from database.auth_db import verify_api_key
from database.settings_db import (
    KILL_SWITCH_MIN_UNLOCK_SECONDS,
    get_kill_switch_audit,
    get_kill_switch_scope,
    get_kill_switch_state,
    set_kill_switch_scope,
)
from limiter import limiter
from services.kill_switch_service import activate_kill_switch, deactivate_kill_switch
from utils.logging import get_logger

logger = get_logger(__name__)

killswitch_bp = Blueprint("killswitch_bp", __name__, url_prefix="/api/v1/killswitch")

ACTIVATE_RATE_LIMIT = os.getenv("KILL_SWITCH_RATE_LIMIT", "5 per minute")


def _resolve_actor():
    """Resolve (actor_type, actor_id) from either a session cookie (UI) or
    an apikey in the JSON body (programmatic). Returns (None, None) if
    neither authenticates."""
    username = session.get("user")
    if isinstance(username, str) and username:
        return "ui", username

    data = request.get_json(silent=True) or {}
    api_key = data.get("apikey")
    if api_key:
        resolved_username = verify_api_key(api_key)
        if resolved_username:
            actor_type = data.get("actor_type") or "api"
            return actor_type, resolved_username

    return None, None


@killswitch_bp.route("/activate", methods=["POST"])
@limiter.limit(ACTIVATE_RATE_LIMIT)
def activate():
    """Activate the kill switch and run the full cleanup sequence."""
    actor_type, actor_id = _resolve_actor()
    if not actor_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    data = request.get_json(silent=True) or {}
    reason = data.get("reason")

    result = activate_kill_switch(actor_type=actor_type, actor_id=actor_id, reason=reason)
    return jsonify({"status": "success", **result}), 200


@killswitch_bp.route("/deactivate", methods=["POST"])
@limiter.limit(ACTIVATE_RATE_LIMIT)
def deactivate():
    """Deactivate the kill switch. Requires the min-unlock window to have
    elapsed and an exact 'UNLOCK' confirmation string, so a fat-finger press
    or a scripted retry loop can't undo an activation."""
    actor_type, actor_id = _resolve_actor()
    if not actor_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    data = request.get_json(silent=True) or {}
    confirmation = data.get("confirmation")

    # actor_id is this caller's own username -- the min-unlock window and
    # active check must be evaluated against THEIR switch, not a global one.
    state = get_kill_switch_state(actor_id)
    if not state["kill_switch_active"]:
        return jsonify({"status": "error", "code": "ALREADY_INACTIVE", "message": "Kill switch is not active"}), 400

    min_unlock_at = state.get("min_unlock_at")
    if min_unlock_at:
        min_unlock_dt = datetime.fromisoformat(min_unlock_at)
        now = datetime.now(UTC)
        if now < min_unlock_dt:
            retry_after = int((min_unlock_dt - now).total_seconds())
            return jsonify(
                {
                    "status": "error",
                    "code": "MIN_UNLOCK_NOT_REACHED",
                    "message": f"Minimum {KILL_SWITCH_MIN_UNLOCK_SECONDS}s hold has not elapsed yet.",
                    "retry_after_seconds": max(retry_after, 0),
                }
            ), 423

    if confirmation != "UNLOCK":
        return jsonify({"status": "error", "code": "CONFIRMATION_MISMATCH", "message": "Type UNLOCK to confirm."}), 400

    result = deactivate_kill_switch(actor_type=actor_type, actor_id=actor_id)
    result["note"] = "Python strategies and Flow workflows remain stopped. Restart each manually."
    return jsonify({"status": "success", **result}), 200


@killswitch_bp.route("/status", methods=["GET"])
def status():
    """Current kill-switch state for the requesting user. Not rate-limited;
    the UI needs to poll/check this even from a logged-out-adjacent state.

    Unlike the pre-multi-user version this DOES resolve identity, because
    the state is per-user -- returning a global flag here would show one
    user their own dashboard reporting another account's emergency stop.
    An unauthenticated caller gets the inactive default rather than a 401,
    preserving the "always answerable" property the UI relies on.
    """
    _actor_type, actor_id = _resolve_actor()
    return jsonify({"status": "success", **get_kill_switch_state(actor_id)}), 200


@killswitch_bp.route("/audit", methods=["GET"])
def audit():
    """Recent activation/deactivation history for the requesting user."""
    actor_type, actor_id = _resolve_actor()
    if not actor_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(limit, 200))
    return jsonify(
        {"status": "success", "audit": get_kill_switch_audit(actor_id, limit=limit)}
    ), 200


@killswitch_bp.route("/scope", methods=["GET"])
def get_scope():
    """Which cleanup steps the kill switch currently runs (cancel orders /
    close positions -- strategy/flow stopping always runs and is not
    configurable). A settings read, not an emergency action, so this only
    accepts the session-cookie identity path, same as the apikey path
    below is available for programmatic callers wanting to check before
    scripting an activation."""
    actor_type, actor_id = _resolve_actor()
    if not actor_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    return jsonify({"status": "success", "scope": get_kill_switch_scope(actor_id)}), 200


@killswitch_bp.route("/scope", methods=["POST"])
def update_scope():
    """Update which cleanup steps the kill switch runs on activation."""
    actor_type, actor_id = _resolve_actor()
    if not actor_id:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    data = request.get_json(silent=True) or {}
    if "cancel_orders_enabled" not in data or "close_positions_enabled" not in data:
        return jsonify(
            {
                "status": "error",
                "message": "cancel_orders_enabled and close_positions_enabled are both required",
            }
        ), 400

    scope = set_kill_switch_scope(
        actor_id,
        cancel_orders_enabled=bool(data["cancel_orders_enabled"]),
        close_positions_enabled=bool(data["close_positions_enabled"]),
    )
    logger.info(f"Kill switch scope updated by {actor_id}: {scope}")
    return jsonify({"status": "success", "scope": scope}), 200
