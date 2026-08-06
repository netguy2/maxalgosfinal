from flask import Blueprint, jsonify, redirect, render_template, session, url_for

from database.auth_db import get_api_key_for_tradingview, get_auth_token, get_auth_token_dbquery
from database.settings_db import get_analyze_mode
from services.funds_service import get_funds
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

dashboard_bp = Blueprint("dashboard_bp", __name__, url_prefix="/")
scalper_process = None


@dashboard_bp.route("/dashboard")
@check_session_validity
def dashboard():
    login_username = session["user"]
    AUTH_TOKEN = get_auth_token(login_username)

    if AUTH_TOKEN is None:
        logger.warning(f"No auth token found for user {login_username}")
        return redirect(url_for("auth.logout"))

    broker = session.get("broker")
    if not broker:
        logger.error("Broker not set in session")
        return "Broker not set in session", 400

    # Check if in analyze mode and route accordingly
    if get_analyze_mode(login_username):
        # Get API key for sandbox mode
        api_key = get_api_key_for_tradingview(login_username)
        if api_key:
            success, response, status_code = get_funds(api_key=api_key)
        else:
            logger.error("No API key found for analyze mode")
            return "API key required for analyze mode", 400
    else:
        # Use live broker
        success, response, status_code = get_funds(auth_token=AUTH_TOKEN, broker=broker)

    if not success:
        logger.error(f"Failed to get funds data: {response.get('message', 'Unknown error')}")
        if status_code == 404:
            return "Failed to import broker module", 500
        return redirect(url_for("auth.logout"))

    margin_data = response.get("data", {})

    # Check if margin_data is empty (authentication failed)
    if not margin_data:
        logger.error(
            f"Failed to get margin data for user {login_username} - authentication may have expired"
        )
        return redirect(url_for("auth.logout"))

    # Check if all values are zero (but don't log warning during known service hours)
    if (
        margin_data.get("availablecash") == "0.00"
        and margin_data.get("collateral") == "0.00"
        and margin_data.get("utiliseddebits") == "0.00"
    ):
        # This could be service hours or authentication issue
        # The service already logs the appropriate message
        logger.debug(f"All margin data values are zero for user {login_username}")

    return render_template("dashboard.html", margin_data=margin_data)


@dashboard_bp.route("/api/dashboard/market-movers", methods=["GET"])
@check_session_validity
def market_movers():
    """Top NIFTY 50 gainers/losers for the React dashboard. Resolves the
    broker from the Auth table row (never session["broker"] -- see
    blueprints/auth.py's dashboard-data fix for why that scalar can go
    stale after a partial/abandoned broker-connect attempt)."""
    from services.market_movers_service import get_market_movers

    login_username = session["user"]
    auth_row = get_auth_token_dbquery(login_username)
    if not auth_row or auth_row.is_revoked:
        return jsonify({"status": "error", "message": "No active broker session"}), 400

    auth_token = get_auth_token(login_username)
    if not auth_token:
        return jsonify({"status": "error", "message": "No active broker session"}), 400

    try:
        movers = get_market_movers(auth_token, auth_row.broker)
        return jsonify({"status": "success", **movers}), 200
    except Exception as e:
        logger.exception(f"Error fetching market movers: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@dashboard_bp.route("/api/dashboard/ticker-quotes", methods=["GET"])
@check_session_validity
def ticker_quotes():
    """Fetch REST quotes for all ticker symbols (indices and top stocks) so the
    horizontal marquee ticker bar shows closing prices even after market close
    when WebSockets stop emitting live ticks."""
    from services.quotes_service import get_multiquotes

    login_username = session["user"]
    auth_row = get_auth_token_dbquery(login_username)
    if not auth_row or auth_row.is_revoked:
        return jsonify({"status": "error", "message": "No active broker session"}), 400

    auth_token = get_auth_token(login_username)
    if not auth_token:
        return jsonify({"status": "error", "message": "No active broker session"}), 400

    ticker_symbols = [
        {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "BANKNIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "FINNIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "SENSEX", "exchange": "BSE_INDEX"},
        {"symbol": "RELIANCE", "exchange": "NSE"},
        {"symbol": "TCS", "exchange": "NSE"},
        {"symbol": "HDFCBANK", "exchange": "NSE"},
        {"symbol": "INFY", "exchange": "NSE"},
        {"symbol": "ICICIBANK", "exchange": "NSE"},
        {"symbol": "SBIN", "exchange": "NSE"},
        {"symbol": "TATAMOTORS", "exchange": "NSE"},
        {"symbol": "ITC", "exchange": "NSE"},
    ]

    try:
        success, response, _status = get_multiquotes(
            ticker_symbols, auth_token=auth_token, broker=auth_row.broker
        )
        if not success:
            return jsonify({"status": "error", "message": "Failed to fetch ticker quotes"}), 400

        results = response.get("results", []) or []
        quotes_map = {}
        for item in results:
            sym = item.get("symbol")
            exch = item.get("exchange")
            data = item.get("data")
            if sym and exch and data:
                key = f"{exch}:{sym}"
                try:
                    ltp_val = float(data.get("ltp", 0) or 0)
                    change_val = float(data.get("change", 0) or 0)
                    change_pct = float(data.get("change_percent", 0) or 0)
                    quotes_map[key] = {
                        "ltp": ltp_val,
                        "change": change_val,
                        "change_percent": change_pct,
                    }
                except (TypeError, ValueError):
                    pass

        return jsonify({"status": "success", "quotes": quotes_map}), 200
    except Exception as e:
        logger.exception(f"Error fetching ticker quotes: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
