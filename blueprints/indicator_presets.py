# blueprints/indicator_presets.py
"""
Indicator Presets Blueprint

Saved indicator selections ("setups") for the Charts page
(pages/Charts.tsx), scoped per-user to either one symbol/exchange or
globally (NULL symbol/exchange = default for symbols without their own
saved setup). Session/cookie authenticated (like chart_watchlists_bp/
chart_drawings_bp) and NOT exempted from Flask-WTF's global
CSRFProtect -- the frontend (api/indicator-presets.ts) uses webClient,
whose request interceptor attaches X-CSRFToken automatically.
"""

from flask import Blueprint, jsonify, request, session

from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

indicator_presets_bp = Blueprint(
    "indicator_presets_bp", __name__, url_prefix="/indicator-presets"
)


def _validate_config(config) -> bool:
    if not isinstance(config, dict):
        return False
    indicators = config.get("indicators")
    custom_ids = config.get("customIndicatorIds")
    if not isinstance(indicators, list) or not all(isinstance(i, str) for i in indicators):
        return False
    if not isinstance(custom_ids, list) or not all(isinstance(i, int) for i in custom_ids):
        return False
    return True


@indicator_presets_bp.route("/api/get", methods=["GET"])
@check_session_validity
def get_preset():
    """Resolve the preset for a symbol: prefer the symbol-scoped preset,
    fall back to the global one. Returns which scope was matched (or none)
    so the frontend can show where the loaded setup came from."""
    try:
        from database.indicator_preset_db import get_preset as db_get

        symbol = (request.args.get("symbol") or "").strip().upper()
        exchange = (request.args.get("exchange") or "").strip().upper()
        user = session.get("user")

        if symbol and exchange:
            symbol_preset = db_get(user, symbol, exchange)
            if symbol_preset:
                return jsonify({"status": "success", "scope": "symbol", "data": symbol_preset}), 200

        global_preset = db_get(user, None, None)
        if global_preset:
            return jsonify({"status": "success", "scope": "global", "data": global_preset}), 200

        return jsonify({"status": "success", "scope": None, "data": None}), 200
    except Exception as e:
        logger.exception(f"Error getting indicator preset: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@indicator_presets_bp.route("/api/save", methods=["POST"])
@check_session_validity
def save_preset():
    """Save (upsert) the current indicator selection.

    Body: {scope: 'symbol'|'global', symbol?, exchange?, indicators, customIndicatorIds}
    """
    try:
        from database.indicator_preset_db import save_preset as db_save

        data = request.get_json(silent=True) or {}
        scope = data.get("scope")
        if scope not in ("symbol", "global"):
            return jsonify({"status": "error", "message": "scope must be 'symbol' or 'global'"}), 400

        config = {
            "indicators": data.get("indicators") or [],
            "customIndicatorIds": data.get("customIndicatorIds") or [],
        }
        if not _validate_config(config):
            return jsonify({"status": "error", "message": "Invalid indicator config"}), 400

        symbol = None
        exchange = None
        if scope == "symbol":
            symbol = (data.get("symbol") or "").strip().upper()
            exchange = (data.get("exchange") or "").strip().upper()
            if not symbol or not exchange:
                return jsonify(
                    {"status": "error", "message": "symbol and exchange are required for scope=symbol"}
                ), 400

        user = session.get("user")
        saved = db_save(user, symbol, exchange, config)
        if saved is None:
            return jsonify({"status": "error", "message": "Failed to save preset"}), 500
        return jsonify({"status": "success", "data": saved}), 200
    except Exception as e:
        logger.exception(f"Error saving indicator preset: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@indicator_presets_bp.route("/api/<scope>", methods=["DELETE"])
@check_session_validity
def delete_preset(scope: str):
    """Clear a saved preset. scope is 'global' or 'symbol' (with
    ?symbol=&exchange= query params for the symbol scope)."""
    try:
        from database.indicator_preset_db import delete_preset as db_delete

        user = session.get("user")
        if scope == "global":
            symbol, exchange = None, None
        elif scope == "symbol":
            symbol = (request.args.get("symbol") or "").strip().upper()
            exchange = (request.args.get("exchange") or "").strip().upper()
            if not symbol or not exchange:
                return jsonify(
                    {"status": "error", "message": "symbol and exchange are required"}
                ), 400
        else:
            return jsonify({"status": "error", "message": "scope must be 'symbol' or 'global'"}), 400

        success = db_delete(user, symbol, exchange)
        if not success:
            return jsonify({"status": "error", "message": "Preset not found"}), 404
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.exception(f"Error deleting indicator preset: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
