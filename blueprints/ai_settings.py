# blueprints/ai_settings.py
"""
AI Settings Blueprint

Lets a user configure their own AI provider API key (OpenAI/Anthropic/
Gemini/OpenAI-compatible custom endpoint) for the "AI Insight" advisory
feature on the Charts page. Session/cookie authenticated (like
chart_drawings_bp) and NOT exempted from Flask-WTF's global CSRFProtect
-- the frontend (api/ai-settings.ts) uses webClient, whose request
interceptor attaches X-CSRFToken automatically.

The decrypted API key is NEVER returned in any response here -- only
whether one is configured (hasApiKey). Re-saving requires re-entering the
key; there is no "reveal" endpoint.
"""

from flask import Blueprint, jsonify, request, session

from database.ai_settings_db import VALID_PROVIDERS
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

ai_settings_bp = Blueprint("ai_settings_bp", __name__, url_prefix="/ai-settings")


@ai_settings_bp.route("/api/get", methods=["GET"])
@check_session_validity
def get_settings():
    """Returns provider/model/baseUrl + hasApiKey/hasNewsApiKey -- never the raw key."""
    try:
        from database.ai_settings_db import get_ai_settings_public

        user = session.get("user")
        settings = get_ai_settings_public(user)
        return jsonify({"status": "success", "data": settings}), 200
    except Exception as e:
        logger.exception(f"Error getting AI settings: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@ai_settings_bp.route("/api/save", methods=["POST"])
@check_session_validity
def save_settings():
    """Body: {provider, apiKey, model?, baseUrl?}"""
    try:
        from database.ai_settings_db import save_ai_settings

        data = request.get_json(silent=True) or {}
        provider = (data.get("provider") or "").strip().lower()
        api_key = data.get("apiKey") or ""
        model = (data.get("model") or "").strip() or None
        base_url = (data.get("baseUrl") or "").strip() or None

        if provider not in VALID_PROVIDERS:
            return jsonify(
                {"status": "error", "message": f"provider must be one of {sorted(VALID_PROVIDERS)}"}
            ), 400
        if not api_key.strip():
            return jsonify({"status": "error", "message": "apiKey is required"}), 400
        if provider == "custom" and not base_url:
            return jsonify(
                {"status": "error", "message": "baseUrl is required for provider=custom"}
            ), 400

        user = session.get("user")
        # Never log the raw key.
        logger.info(f"Saving AI settings for user={user}, provider={provider}")
        saved = save_ai_settings(user, provider, api_key.strip(), model, base_url)
        if saved is None:
            return jsonify({"status": "error", "message": "Failed to save AI settings"}), 500
        return jsonify({"status": "success", "data": saved}), 200
    except Exception as e:
        logger.exception(f"Error saving AI settings: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@ai_settings_bp.route("/api/delete", methods=["DELETE"])
@check_session_validity
def delete_settings():
    """Removes the user's AI provider configuration entirely."""
    try:
        from database.ai_settings_db import delete_ai_settings

        user = session.get("user")
        success = delete_ai_settings(user)
        if not success:
            return jsonify({"status": "error", "message": "No AI settings found"}), 404
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.exception(f"Error deleting AI settings: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@ai_settings_bp.route("/api/save-news", methods=["POST"])
@check_session_validity
def save_news_settings_route():
    """Fast-follow: news provider API key. Body: {newsProvider, newsApiKey}."""
    try:
        from database.ai_settings_db import save_news_settings

        data = request.get_json(silent=True) or {}
        news_provider = (data.get("newsProvider") or "").strip()
        news_api_key = data.get("newsApiKey") or ""

        if not news_provider:
            return jsonify({"status": "error", "message": "newsProvider is required"}), 400
        if not news_api_key.strip():
            return jsonify({"status": "error", "message": "newsApiKey is required"}), 400

        user = session.get("user")
        saved = save_news_settings(user, news_provider, news_api_key.strip())
        if saved is None:
            return jsonify(
                {"status": "error", "message": "Configure an AI provider before adding a news key"}
            ), 400
        return jsonify({"status": "success", "data": saved}), 200
    except Exception as e:
        logger.exception(f"Error saving news settings: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
