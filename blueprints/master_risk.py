"""Master Target / Master SL REST API.

Account-wide combined P&L auto-exit for scalpers running multiple
simultaneous live positions. See services/master_risk_monitor_service.py
for the actual monitoring loop -- this blueprint is just the settings CRUD
+ live-snapshot read the frontend polls.

Standard session-gated routes (unlike killswitch.py's dual auth path) --
this is a regular settings feature, not an emergency action that needs to
stay reachable through subscription/session gating.
"""

from flask import Blueprint, jsonify, request, session

from database.settings_db import (
    get_master_risk_audit,
    get_master_risk_settings,
    set_master_risk_settings,
)
from services.master_risk_monitor_service import get_current_combined_pnl
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

master_risk_bp = Blueprint("master_risk_bp", __name__, url_prefix="/api/v1/master-risk")


def _current_user() -> str | None:
    """The requesting user. Master SL/Target is per-user (see
    database/settings_db.py) -- every route below reads and writes only
    this account's own thresholds and trigger history. All routes here are
    @check_session_validity-gated, so the session identity is always
    present and authenticated by the time these run."""
    username = session.get("user")
    return username if isinstance(username, str) and username else None


@master_risk_bp.route("/settings", methods=["GET"])
@check_session_validity
def get_settings():
    """Current Master SL/Target configuration for the requesting user."""
    return jsonify({"status": "success", **get_master_risk_settings(_current_user())}), 200


@master_risk_bp.route("/settings", methods=["POST"])
@check_session_validity
def update_settings():
    """Update Master SL/Target configuration.

    Body: {enabled: bool, sl_value: number|null, target_value: number|null}
    sl_value/target_value are plain rupee amounts (not percentage) -- see
    Settings.master_risk_sl_value's column comment for why. Either may be
    null to disable just that side (e.g. target only, no SL, or vice versa).
    """
    data = request.get_json(silent=True) or {}

    if "enabled" not in data:
        return jsonify({"status": "error", "message": "enabled is required"}), 400

    enabled = bool(data["enabled"])
    sl_value = data.get("sl_value")
    target_value = data.get("target_value")

    for label, value in (("sl_value", sl_value), ("target_value", target_value)):
        if value is not None:
            try:
                float(value)
            except (TypeError, ValueError):
                return jsonify({"status": "error", "message": f"{label} must be a number or null"}), 400

    if enabled and sl_value is None and target_value is None:
        return jsonify(
            {
                "status": "error",
                "message": "At least one of sl_value or target_value must be set to enable monitoring",
            }
        ), 400

    username = _current_user()
    if not username:
        return jsonify({"status": "error", "message": "Authentication required"}), 401

    settings = set_master_risk_settings(
        username,
        enabled=enabled,
        sl_value=float(sl_value) if sl_value is not None else None,
        target_value=float(target_value) if target_value is not None else None,
    )
    logger.info(f"Master risk settings updated for {username}: {settings}")
    return jsonify({"status": "success", **settings}), 200


@master_risk_bp.route("/live", methods=["GET"])
@check_session_validity
def live_snapshot():
    """On-demand combined P&L snapshot -- same number the monitor loop
    computes on its next tick, for the settings card's live display."""
    return jsonify({"status": "success", **get_current_combined_pnl()}), 200


@master_risk_bp.route("/audit", methods=["GET"])
@check_session_validity
def audit():
    """Recent Master SL/Target trigger history."""
    limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(limit, 200))
    return jsonify(
        {"status": "success", "audit": get_master_risk_audit(_current_user(), limit=limit)}
    ), 200
