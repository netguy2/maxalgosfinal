# blueprints/custom_indicators.py
"""
Custom Indicators Blueprint

Per-user, formula-builder-defined indicator overlays for the Charts page
(pages/Charts.tsx). Session/cookie authenticated (like historify_bp) and
NOT exempted from Flask-WTF's global CSRFProtect -- the frontend
(api/custom-indicators.ts) uses webClient, whose request interceptor
attaches X-CSRFToken automatically.
"""

from flask import Blueprint, jsonify, request, session

from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

custom_indicators_bp = Blueprint("custom_indicators_bp", __name__, url_prefix="/custom-indicators")


@custom_indicators_bp.route("/api/list", methods=["GET"])
@check_session_validity
def list_custom_indicators():
    """List the current user's saved custom indicators."""
    try:
        from database.custom_indicator_db import get_custom_indicators

        user = session.get("user")
        indicators = get_custom_indicators(user)
        return jsonify({"status": "success", "data": indicators}), 200
    except Exception as e:
        logger.exception(f"Error listing custom indicators: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@custom_indicators_bp.route("/api/create", methods=["POST"])
@check_session_validity
def create_custom_indicator():
    """Save a new custom indicator. Body: {name, formula, color}."""
    try:
        from database.custom_indicator_db import create_custom_indicator as db_create
        from services.custom_indicator_service import (
            FormulaValidationError,
            validate_formula,
        )

        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        formula = data.get("formula")
        color = data.get("color") or "#f59e0b"

        if not name:
            return jsonify({"status": "error", "message": "name is required"}), 400
        if len(name) > 100:
            return jsonify({"status": "error", "message": "name too long (max 100 chars)"}), 400

        try:
            validate_formula(formula)
        except FormulaValidationError as e:
            return jsonify({"status": "error", "message": str(e)}), 400

        user = session.get("user")
        created = db_create(user, name, formula, color)
        if created is None:
            return jsonify({"status": "error", "message": "Failed to save indicator"}), 500
        return jsonify({"status": "success", "data": created}), 200
    except Exception as e:
        logger.exception(f"Error creating custom indicator: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@custom_indicators_bp.route("/api/<int:indicator_id>", methods=["DELETE"])
@check_session_validity
def delete_custom_indicator(indicator_id: int):
    """Delete a custom indicator, ownership-checked against the session user."""
    try:
        from database.custom_indicator_db import delete_custom_indicator as db_delete

        user = session.get("user")
        success = db_delete(user, indicator_id)
        if not success:
            return jsonify({"status": "error", "message": "Indicator not found"}), 404
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.exception(f"Error deleting custom indicator: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@custom_indicators_bp.route("/api/compute", methods=["POST"])
@check_session_validity
def compute_custom_indicators():
    """Compute one or more custom indicators over caller-supplied bars.

    Body:
        bars - list of {timestamp, open, high, low, close, volume}
        formulas - list of {id, formula} (each formula validated again
                   here, not just trusted from what was saved at create
                   time, in case client-sent data is tampered with)
    """
    try:
        from services.custom_indicator_service import compute_custom_indicators_from_bars

        payload = request.get_json(silent=True) or {}
        bars = payload.get("bars", [])
        formulas = payload.get("formulas", [])

        if not bars or not formulas:
            return jsonify({"status": "success", "data": {}}), 200

        success, response, status_code = compute_custom_indicators_from_bars(bars, formulas)
        return jsonify(response), status_code
    except Exception as e:
        logger.exception(f"Error computing custom indicators: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
