# blueprints/settings.py

from flask import Blueprint, jsonify, request, session

from database.settings_db import get_analyze_mode, set_analyze_mode
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

settings_bp = Blueprint("settings_bp", __name__, url_prefix="/settings")


@settings_bp.route("/analyze-mode")
@check_session_validity
def get_mode():
    """Get the CALLING USER's own analyze mode setting.

    Own mode only -- see set_mode's docstring for why this legacy endpoint
    can no longer read/write a single global flag.
    """
    try:
        return jsonify({"analyze_mode": get_analyze_mode(session.get("user"))})
    except Exception as e:
        logger.exception(f"Error getting analyze mode: {str(e)}")
        return jsonify({"error": "Failed to get analyze mode"}), 500


@settings_bp.route("/analyze-mode/<int:mode>", methods=["POST"])
@check_session_validity
def set_mode(mode):
    """Set the CALLING USER's own analyze mode setting.

    Analyze/Live mode used to be one global Settings.analyze_mode row
    shared by every account on the instance, and this endpoint additionally
    started/stopped the shared sandbox execution-engine thread on every
    call -- one user hitting this endpoint to switch to Live mode silently
    stopped sandbox order execution for every OTHER user who still had
    Analyze Mode on. Fixed the same way as blueprints/auth.py's
    /analyzer-toggle: analyze_mode moved to a per-user UserRiskSettings
    column, and the execution engine + square-off scheduler are now
    always-on background workers started once at app startup (see app.py),
    not by this route. They already filter their work correctly per user.
    """
    try:
        username = session.get("user")
        set_analyze_mode(bool(mode), username)
        mode_name = "Analyze" if mode else "Live"
        logger.info(f"Analyze mode set to {mode_name} for user '{username}'")

        return jsonify(
            {
                "success": True,
                "analyze_mode": bool(mode),
                "message": f"Switched to {mode_name} Mode",
            }
        )
    except Exception as e:
        logger.exception(f"Error setting analyze mode: {str(e)}")
        return jsonify({"error": "Failed to set analyze mode"}), 500
