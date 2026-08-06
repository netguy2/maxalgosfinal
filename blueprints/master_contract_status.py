from threading import Thread

from flask import Blueprint, jsonify, request, session

from database.master_contract_status_db import check_if_ready, get_status, init_broker_status
from utils.auth_utils import (
    async_master_contract_download,
    get_master_contract_cutoff,
    should_download_master_contract,
)
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

# Admin-only: master contract download/cache internals are shared, per-broker
# platform infrastructure (see database/symbol.py's SymToken.broker), not a
# per-user setting -- regular users never need to see or touch this, and
# having every logged-in account able to trigger a Force Download / cache
# clear was needless exposure of an operational control. Mounted under
# /admin/api (not the general /api prefix) to match blueprints/admin.py's
# other admin-only routes.
master_contract_status_bp = Blueprint(
    "master_contract_status_bp", __name__, url_prefix="/admin/api"
)

# Not admin-gated: a minimal, read-only readiness signal for the regular
# user's own dashboard ("Synced" / "Syncing..." pill) -- deliberately
# stripped down to status + total_symbols only, no download-history,
# cache-health, or exchange-stats internals (those stay admin-only above).
master_contract_readiness_bp = Blueprint(
    "master_contract_readiness_bp", __name__, url_prefix="/api"
)


@master_contract_readiness_bp.route("/master-contract/status", methods=["GET"])
@check_session_validity
def get_master_contract_readiness():
    """Minimal synced/syncing readiness signal for the dashboard KPI pill."""
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"status": "error", "message": "No broker session found"}), 401

        status_data = get_status(broker)
        return jsonify(
            {
                "status": status_data.get("status"),
                "total_symbols": status_data.get("total_symbols"),
            }
        ), 200

    except Exception as e:
        logger.exception(f"Error getting master contract readiness: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to get status"}), 500


def _require_admin():
    """Return an error Flask response if the current session user is not an
    admin, else None. Mirrors blueprints/admin.py's inline admin-check
    pattern (no reusable @admin_required decorator exists in this codebase
    yet)."""
    from database.user_db import find_user_by_exact_username

    username = session.get("user", "")
    if not username or not isinstance(username, str):
        return jsonify({"status": "error", "message": "Admin access required"}), 403
    user = find_user_by_exact_username(username)
    if not user or not bool(user.is_admin):
        return jsonify({"status": "error", "message": "Admin access required"}), 403
    return None


@master_contract_status_bp.route("/master-contract/status", methods=["GET"])
@check_session_validity
def get_master_contract_status():
    """Get the current master contract download status (admin only)"""
    denied = _require_admin()
    if denied:
        return denied
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"status": "error", "message": "No broker session found"}), 401

        status_data = get_status(broker)
        return jsonify(status_data), 200

    except Exception as e:
        logger.exception(f"Error getting master contract status: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to get master contract status"}), 500


@master_contract_status_bp.route("/master-contract/ready", methods=["GET"])
@check_session_validity
def check_master_contract_ready():
    """Check if master contracts are ready for trading (admin only)"""
    denied = _require_admin()
    if denied:
        return denied
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"ready": False, "message": "No broker session found"}), 401

        is_ready = check_if_ready(broker)
        return jsonify(
            {
                "ready": is_ready,
                "message": "Master contracts are ready"
                if is_ready
                else "Master contracts not ready",
            }
        ), 200

    except Exception as e:
        logger.exception(f"Error checking master contract readiness: {str(e)}")
        return jsonify(
            {"ready": False, "message": "Failed to check master contract readiness"}
        ), 500


@master_contract_status_bp.route("/cache/status", methods=["GET"])
@check_session_validity
def get_cache_status():
    """Get the current symbol cache status and statistics (admin only)"""
    denied = _require_admin()
    if denied:
        return denied
    try:
        from database.token_db_enhanced import get_cache_stats

        cache_info = get_cache_stats()
        return jsonify(cache_info), 200

    except ImportError:
        # Fallback if enhanced cache not available yet
        return jsonify(
            {"status": "not_available", "message": "Enhanced cache module not available"}
        ), 200
    except Exception as e:
        logger.exception(f"Error getting cache status: {str(e)}")
        return jsonify({"status": "error", "message": f"Failed to get cache status: {str(e)}"}), 500


@master_contract_status_bp.route("/cache/health", methods=["GET"])
@check_session_validity
def get_cache_health():
    """Get cache health metrics and recommendations (admin only)"""
    denied = _require_admin()
    if denied:
        return denied
    try:
        from database.master_contract_cache_hook import get_cache_health

        health_info = get_cache_health()
        return jsonify(health_info), 200

    except ImportError:
        return jsonify(
            {
                "health_score": 0,
                "status": "not_available",
                "message": "Cache health monitoring not available",
            }
        ), 200
    except Exception as e:
        logger.exception(f"Error getting cache health: {str(e)}")
        return jsonify(
            {
                "health_score": 0,
                "status": "error",
                "message": f"Failed to get cache health: {str(e)}",
            }
        ), 500


@master_contract_status_bp.route("/cache/reload", methods=["POST"])
@check_session_validity
def reload_cache():
    """Manually trigger cache reload (admin only)"""
    denied = _require_admin()
    if denied:
        return denied
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"status": "error", "message": "No broker session found"}), 401

        from database.master_contract_cache_hook import load_symbols_to_cache

        success = load_symbols_to_cache(broker)

        if success:
            return jsonify(
                {
                    "status": "success",
                    "message": f"Cache reloaded successfully for broker: {broker}",
                }
            ), 200
        else:
            return jsonify({"status": "error", "message": "Failed to reload cache"}), 500

    except ImportError:
        return jsonify(
            {"status": "error", "message": "Cache reload functionality not available"}
        ), 501
    except Exception as e:
        logger.exception(f"Error reloading cache: {str(e)}")
        return jsonify({"status": "error", "message": f"Failed to reload cache: {str(e)}"}), 500


@master_contract_status_bp.route("/cache/clear", methods=["POST"])
@check_session_validity
def clear_cache():
    """Manually clear the cache (admin only)"""
    denied = _require_admin()
    if denied:
        return denied
    try:
        from database.token_db_enhanced import clear_cache as clear_symbol_cache

        clear_symbol_cache()

        return jsonify({"status": "success", "message": "Cache cleared successfully"}), 200

    except ImportError:
        return jsonify(
            {"status": "error", "message": "Cache clear functionality not available"}
        ), 501
    except Exception as e:
        logger.exception(f"Error clearing cache: {str(e)}")
        return jsonify({"status": "error", "message": f"Failed to clear cache: {str(e)}"}), 500


@master_contract_status_bp.route("/master-contract/download", methods=["POST"])
@check_session_validity
def force_master_contract_download():
    """Force a fresh master contract download regardless of smart download logic (admin only)"""
    denied = _require_admin()
    if denied:
        return denied
    try:
        broker = session.get("broker")
        if not broker:
            user_id = session.get("user")
            if user_id:
                from database.auth_db import get_broker_name
                broker = get_broker_name(user_id)
        if not broker:
            broker = "zebu"

        # Get request body for force flag
        data = request.get_json(silent=True) or {}
        force = data.get("force", False)

        if not force:
            # Check if download is needed using smart logic
            should_download, reason = should_download_master_contract(broker)
            if not should_download:
                return jsonify({
                    "status": "skipped",
                    "message": reason,
                    "should_download": False
                }), 200

        # Initialize status and start download
        init_broker_status(broker)
        # Pass the requesting user so the completion toast lands only in their
        # browser, not every logged-in account's (see utils/socket_scope.py).
        thread = Thread(
            target=async_master_contract_download,
            args=(broker, session.get("user")),
            daemon=True,
        )
        thread.start()

        return jsonify({
            "status": "success",
            "message": "Master contract download started",
            "started": True
        }), 200

    except Exception as e:
        logger.exception(f"Error starting master contract download: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Failed to start download: {str(e)}"
        }), 500


@master_contract_status_bp.route("/master-contract/smart-status", methods=["GET"])
@check_session_validity
def get_smart_download_status():
    """Get detailed status including smart download information (admin only)"""
    denied = _require_admin()
    if denied:
        return denied
    try:
        broker = session.get("broker")
        if not broker:
            return jsonify({"status": "error", "message": "No broker session found"}), 401

        # Get full status with smart download fields
        status_data = get_status(broker)

        # Add smart download recommendation
        should_download, reason = should_download_master_contract(broker)
        cutoff_hour, cutoff_minute, tz = get_master_contract_cutoff(broker)
        import pytz
        tz_label = "UTC" if tz is pytz.utc else "IST"
        status_data["smart_download"] = {
            "should_download": should_download,
            "reason": reason,
            "cutoff_time": f"{cutoff_hour:02d}:{cutoff_minute:02d}",
            "cutoff_timezone": tz_label
        }

        return jsonify(status_data), 200

    except Exception as e:
        logger.exception(f"Error getting smart download status: {str(e)}")
        return jsonify({"status": "error", "message": "Failed to get status"}), 500


