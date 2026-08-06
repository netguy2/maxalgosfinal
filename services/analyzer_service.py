import copy
from typing import Any, Dict, Optional, Tuple

from database.analyzer_db import AnalyzerLog, db_session
from database.apilog_db import async_log_order
from database.apilog_db import executor as log_executor
from database.auth_db import get_auth_token_broker
from database.settings_db import get_analyze_mode, set_analyze_mode
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)


def get_analyzer_status_with_auth(
    analyzer_data: dict[str, Any], auth_token: str, broker: str, original_data: dict[str, Any]
) -> tuple[bool, dict[str, Any], int]:
    """
    Get analyzer mode status and statistics.

    Args:
        analyzer_data: Analyzer data (currently just apikey)
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    request_data = copy.deepcopy(original_data)
    if "apikey" in request_data:
        request_data.pop("apikey", None)

    try:
        # Resolve the calling user explicitly rather than relying on
        # get_analyze_mode()'s Flask-session fallback -- this is an
        # API-key-authenticated call, which may or may not be running
        # inside a session-backed request depending on the caller
        # (TradingView/Python-strategy-style direct HTTP calls have no
        # Flask session cookie at all).
        from database.auth_db import verify_api_key

        acting_username = verify_api_key(original_data.get("apikey", ""))

        # Get current analyzer mode
        current_mode = get_analyze_mode(acting_username)

        # Get analyzer logs count
        logs_count = db_session.query(AnalyzerLog).count()

        response_data = {
            "status": "success",
            "data": {
                "mode": "analyze" if current_mode else "live",
                "analyze_mode": current_mode,
                "total_logs": logs_count,
            },
        }

        log_executor.submit(async_log_order, "analyzer_status", request_data, response_data)
        return True, response_data, 200

    except Exception as e:
        logger.exception(f"Error getting analyzer status: {e}")
        error_response = {"status": "error", "message": str(e)}
        log_executor.submit(async_log_order, "analyzer_status", original_data, error_response)
        return False, error_response, 500


def toggle_analyzer_mode_with_auth(
    analyzer_data: dict[str, Any], auth_token: str, broker: str, original_data: dict[str, Any]
) -> tuple[bool, dict[str, Any], int]:
    """
    Toggle analyzer mode on/off.

    Args:
        analyzer_data: Analyzer data containing mode
        auth_token: Authentication token for the broker API
        broker: Name of the broker
        original_data: Original request data for logging

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    request_data = copy.deepcopy(original_data)
    if "apikey" in request_data:
        request_data.pop("apikey", None)

    try:
        # Resolve the calling user explicitly -- see get_analyzer_status_with_auth's
        # matching comment. A write with no resolvable identity must fail
        # loudly (set_analyze_mode raises ValueError), not silently no-op or
        # fall back to some other user's mode.
        from database.auth_db import verify_api_key

        acting_username = verify_api_key(original_data.get("apikey", ""))

        # Get the requested mode
        new_mode = analyzer_data.get("mode", False)

        # Set the analyzer mode for THIS user only.
        set_analyze_mode(new_mode, acting_username)

        # The execution engine and square-off scheduler are shared, always-
        # on background workers started once at app startup (see app.py) --
        # they are no longer started/stopped by any single user's toggle.
        # Both already filter their per-user work to whatever sandbox
        # orders/positions actually exist, which is itself gated per-user
        # at order-PLACEMENT time by get_analyze_mode(username) in
        # place_order_service.py, so nothing needs to be (re)started here.
        # Previously this call unconditionally stopped BOTH threads for
        # every user on the instance the moment any ONE user switched back
        # to Live Mode, silently halting sandbox execution and square-off
        # for every other user who still had Analyze Mode enabled.
        if new_mode:
            # Run catch-up settlement for any missed settlements in case this
            # user's sandbox positions went unmonitored while the shared
            # engine was down for any reason (e.g. a restart).
            from sandbox.position_manager import catchup_missed_settlements

            try:
                catchup_missed_settlements()
                logger.info("Catch-up settlement check completed")
            except Exception as e:
                logger.exception(f"Error in catch-up settlement: {e}")

            logger.info(f"Analyze mode enabled for user '{acting_username}'")
        else:
            logger.info(f"Analyze mode disabled for user '{acting_username}'")

        # Get logs count for response
        logs_count = db_session.query(AnalyzerLog).count()

        response_data = {
            "status": "success",
            "data": {
                "mode": "analyze" if new_mode else "live",
                "analyze_mode": new_mode,
                "total_logs": logs_count,
                "message": f"Analyzer mode switched to {'analyze' if new_mode else 'live'}",
            },
        }

        log_executor.submit(async_log_order, "analyzer_toggle", request_data, response_data)
        return True, response_data, 200

    except Exception as e:
        logger.exception(f"Error toggling analyzer mode: {e}")
        error_response = {"status": "error", "message": str(e)}
        log_executor.submit(async_log_order, "analyzer_toggle", original_data, error_response)
        return False, error_response, 500


def get_analyzer_status(
    analyzer_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get analyzer mode status and statistics.
    Supports both API-based authentication and direct internal calls.

    Args:
        analyzer_data: Analyzer data (currently just apikey)
        api_key: Max Algos API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(analyzer_data)
    if api_key:
        original_data["apikey"] = api_key

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to analyzer data
        analyzer_data["apikey"] = api_key

        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid maxalgos apikey"}
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403

        return get_analyzer_status_with_auth(analyzer_data, AUTH_TOKEN, broker_name, original_data)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return get_analyzer_status_with_auth(analyzer_data, auth_token, broker, original_data)

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400


def toggle_analyzer_mode(
    analyzer_data: dict[str, Any],
    api_key: str | None = None,
    auth_token: str | None = None,
    broker: str | None = None,
) -> tuple[bool, dict[str, Any], int]:
    """
    Toggle analyzer mode on/off.
    Supports both API-based authentication and direct internal calls.

    Args:
        analyzer_data: Analyzer data containing mode
        api_key: Max Algos API key (for API-based calls)
        auth_token: Direct broker authentication token (for internal calls)
        broker: Direct broker name (for internal calls)

    Returns:
        Tuple containing:
        - Success status (bool)
        - Response data (dict)
        - HTTP status code (int)
    """
    original_data = copy.deepcopy(analyzer_data)
    if api_key:
        original_data["apikey"] = api_key

    # Case 1: API-based authentication
    if api_key and not (auth_token and broker):
        # Add API key to analyzer data
        analyzer_data["apikey"] = api_key

        AUTH_TOKEN, broker_name = get_auth_token_broker(api_key)
        if AUTH_TOKEN is None:
            error_response = {"status": "error", "message": "Invalid maxalgos apikey"}
            # Skip logging for invalid API keys to prevent database flooding
            return False, error_response, 403

        # Check if in semi-auto mode - block analyzer toggle for RA compliance
        from database.auth_db import get_order_mode

        order_mode = get_order_mode(api_key)

        if order_mode == "semi_auto":
            error_response = {
                "status": "error",
                "message": "Operation analyzer/toggle is not allowed in Semi-Auto mode. This operation can only be performed by the client via the UI. This restriction ensures SEBI Research Analyst compliance where mode switching is a client-only decision.",
            }
            log_executor.submit(async_log_order, "analyzer_toggle", original_data, error_response)
            return False, error_response, 403

        return toggle_analyzer_mode_with_auth(analyzer_data, AUTH_TOKEN, broker_name, original_data)

    # Case 2: Direct internal call with auth_token and broker
    elif auth_token and broker:
        return toggle_analyzer_mode_with_auth(analyzer_data, auth_token, broker, original_data)

    # Case 3: Invalid parameters
    else:
        error_response = {
            "status": "error",
            "message": "Either api_key or both auth_token and broker must be provided",
        }
        return False, error_response, 400
