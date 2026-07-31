# blueprints/chart_drawings.py
"""
Chart Drawings Blueprint

Manually-placed trendlines/horizontal rays for the Charts page
(pages/Charts.tsx), persisted per-user/symbol/exchange/interval. Session/
cookie authenticated (like chart_watchlists_bp/custom_indicators_bp) and
NOT exempted from Flask-WTF's global CSRFProtect -- the frontend
(api/chart-drawings.ts) uses webClient, whose request interceptor attaches
X-CSRFToken automatically.
"""

from flask import Blueprint, jsonify, request, session

from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

chart_drawings_bp = Blueprint("chart_drawings_bp", __name__, url_prefix="/chart-drawings")

_VALID_TYPES = {"trendline", "horizontal_ray", "rectangle", "fibonacci"}
_TWO_POINT_TYPES = {"trendline", "rectangle", "fibonacci"}


def _validate_point(point) -> bool:
    return (
        isinstance(point, dict)
        and isinstance(point.get("time"), (int, float))
        and isinstance(point.get("price"), (int, float))
    )


@chart_drawings_bp.route("/api/list", methods=["GET"])
@check_session_validity
def list_drawings():
    """List a user's drawings for one symbol/exchange/interval."""
    try:
        from database.chart_drawing_db import get_drawings

        symbol = (request.args.get("symbol") or "").strip().upper()
        exchange = (request.args.get("exchange") or "").strip().upper()
        interval = (request.args.get("interval") or "").strip()
        if not symbol or not exchange or not interval:
            return jsonify(
                {"status": "error", "message": "symbol, exchange and interval are required"}
            ), 400

        user = session.get("user")
        drawings = get_drawings(user, symbol, exchange, interval)
        return jsonify({"status": "success", "data": drawings}), 200
    except Exception as e:
        logger.exception(f"Error listing chart drawings: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@chart_drawings_bp.route("/api/create", methods=["POST"])
@check_session_validity
def create_drawing():
    """Save a new drawing.

    Body: {symbol, exchange, interval, type, color,
           pointA, pointB}  -- for a trendline
        or
           {symbol, exchange, interval, type, color, point}  -- for a horizontal ray
    """
    try:
        from database.chart_drawing_db import create_drawing as db_create

        data = request.get_json(silent=True) or {}
        symbol = (data.get("symbol") or "").strip().upper()
        exchange = (data.get("exchange") or "").strip().upper()
        interval = (data.get("interval") or "").strip()
        drawing_type = data.get("type")
        color = data.get("color") or "#3b82f6"

        if not symbol or not exchange or not interval:
            return jsonify(
                {"status": "error", "message": "symbol, exchange and interval are required"}
            ), 400
        if drawing_type not in _VALID_TYPES:
            return jsonify(
                {"status": "error", "message": f"type must be one of {sorted(_VALID_TYPES)}"}
            ), 400

        if drawing_type in _TWO_POINT_TYPES:
            point_a = data.get("pointA")
            point_b = data.get("pointB")
            if not _validate_point(point_a) or not _validate_point(point_b):
                return jsonify(
                    {
                        "status": "error",
                        "message": "pointA and pointB must each have numeric time and price",
                    }
                ), 400
            payload = {"pointA": point_a, "pointB": point_b}
        else:
            point = data.get("point")
            if not _validate_point(point):
                return jsonify(
                    {"status": "error", "message": "point must have numeric time and price"}
                ), 400
            payload = {"point": point}

        user = session.get("user")
        created = db_create(user, symbol, exchange, interval, drawing_type, payload, color)
        if created is None:
            return jsonify({"status": "error", "message": "Failed to save drawing"}), 500
        return jsonify({"status": "success", "data": created}), 200
    except Exception as e:
        logger.exception(f"Error creating chart drawing: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@chart_drawings_bp.route("/api/<int:drawing_id>", methods=["DELETE"])
@check_session_validity
def delete_drawing(drawing_id: int):
    """Delete a drawing, ownership-checked against the session user."""
    try:
        from database.chart_drawing_db import delete_drawing as db_delete

        user = session.get("user")
        success = db_delete(user, drawing_id)
        if not success:
            return jsonify({"status": "error", "message": "Drawing not found"}), 404
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.exception(f"Error deleting chart drawing: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
