# blueprints/chart_watchlists.py
"""
Chart Watchlists Blueprint

Named, multiple watchlists for the Charts page (pages/Charts.tsx).
Session/cookie authenticated (like historify_bp and custom_indicators_bp)
and NOT exempted from Flask-WTF's global CSRFProtect -- the frontend
(api/chart-watchlists.ts) uses webClient, whose request interceptor
attaches X-CSRFToken automatically.
"""

from flask import Blueprint, jsonify, request, session

from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

chart_watchlists_bp = Blueprint("chart_watchlists_bp", __name__, url_prefix="/chart-watchlists")


@chart_watchlists_bp.route("/api/list", methods=["GET"])
@check_session_validity
def list_watchlists():
    """List the current user's named watchlists, each with its items."""
    try:
        from database.chart_watchlist_db import get_watchlists

        user = session.get("user")
        watchlists = get_watchlists(user)
        return jsonify({"status": "success", "data": watchlists}), 200
    except Exception as e:
        logger.exception(f"Error listing chart watchlists: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@chart_watchlists_bp.route("/api/create", methods=["POST"])
@check_session_validity
def create_watchlist():
    """Create a new named watchlist. Body: {name}."""
    try:
        from database.chart_watchlist_db import create_watchlist as db_create

        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"status": "error", "message": "name is required"}), 400
        if len(name) > 100:
            return jsonify({"status": "error", "message": "name too long (max 100 chars)"}), 400

        user = session.get("user")
        created = db_create(user, name)
        if created is None:
            return jsonify({"status": "error", "message": "Failed to create watchlist"}), 500
        return jsonify({"status": "success", "data": created}), 200
    except Exception as e:
        logger.exception(f"Error creating chart watchlist: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@chart_watchlists_bp.route("/api/<int:watchlist_id>", methods=["DELETE"])
@check_session_validity
def delete_watchlist(watchlist_id: int):
    """Delete a watchlist, ownership-checked against the session user."""
    try:
        from database.chart_watchlist_db import delete_watchlist as db_delete

        user = session.get("user")
        success = db_delete(user, watchlist_id)
        if not success:
            return jsonify({"status": "error", "message": "Watchlist not found"}), 404
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.exception(f"Error deleting chart watchlist: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@chart_watchlists_bp.route("/api/<int:watchlist_id>/symbols", methods=["POST"])
@check_session_validity
def add_symbol(watchlist_id: int):
    """Add a symbol to a watchlist. Body: {symbol, exchange}."""
    try:
        from database.chart_watchlist_db import add_symbol_to_watchlist

        data = request.get_json(silent=True) or {}
        symbol = (data.get("symbol") or "").strip().upper()
        exchange = (data.get("exchange") or "").strip().upper()
        if not symbol or not exchange:
            return jsonify({"status": "error", "message": "symbol and exchange are required"}), 400

        user = session.get("user")
        item = add_symbol_to_watchlist(user, watchlist_id, symbol, exchange)
        if item is None:
            return jsonify({"status": "error", "message": "Watchlist not found"}), 404
        return jsonify({"status": "success", "data": item}), 200
    except Exception as e:
        logger.exception(f"Error adding symbol to chart watchlist: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@chart_watchlists_bp.route("/api/<int:watchlist_id>/symbols", methods=["DELETE"])
@check_session_validity
def remove_symbol(watchlist_id: int):
    """Remove a symbol from a watchlist. Body: {symbol, exchange}."""
    try:
        from database.chart_watchlist_db import remove_symbol_from_watchlist

        data = request.get_json(silent=True) or {}
        symbol = (data.get("symbol") or "").strip().upper()
        exchange = (data.get("exchange") or "").strip().upper()
        if not symbol or not exchange:
            return jsonify({"status": "error", "message": "symbol and exchange are required"}), 400

        user = session.get("user")
        success = remove_symbol_from_watchlist(user, watchlist_id, symbol, exchange)
        if not success:
            return jsonify({"status": "error", "message": "Symbol not found in watchlist"}), 404
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.exception(f"Error removing symbol from chart watchlist: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
