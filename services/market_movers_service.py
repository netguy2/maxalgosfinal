# services/market_movers_service.py
"""
Top Gainers/Losers for the Dashboard. Reuses the existing bulk multiquote
service (services/quotes_service.py's get_multiquotes -- the same path
Option Chain already uses for strike quotes) rather than talking to
broker APIs directly, so this gets the same per-symbol error handling,
broker routing, and shared-httpx-client pooling that path already has.

On-demand only (no polling/streaming) -- computed fresh on each call.
"""

from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

# Hardcoded NIFTY 50 constituents (standard Max Algos symbol format, NSE
# exchange). No canonical basket exists in database/token_db.py (confirmed
# via research) -- a user-configurable watchlist-as-basket is a future
# follow-up, not built here.
NIFTY50_SYMBOLS = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]

_NIFTY50_EXCHANGE = "NSE"


def get_market_movers(auth_token: str, broker: str, limit: int = 5) -> dict[str, Any]:
    """Fetches quotes for the NIFTY 50 basket in one batch call, ranks by
    % change, returns {"gainers": [...], "losers": [...]}. Each entry:
    {"symbol", "exchange", "ltp", "change_percent"}.

    Symbols whose quote fetch errored (broker rejected/unavailable) are
    silently excluded from ranking -- the underlying multiquote service
    already isolates per-symbol failures (confirmed: _fetch_single_quote_*
    returns {"error": ...} per symbol rather than failing the whole
    batch), so a handful of bad symbols never blocks the rest.
    """
    from services.quotes_service import get_multiquotes

    symbols = [{"symbol": s, "exchange": _NIFTY50_EXCHANGE} for s in NIFTY50_SYMBOLS]

    success, response, _status = get_multiquotes(symbols, auth_token=auth_token, broker=broker)
    if not success:
        logger.warning(f"Market movers: multiquote fetch failed: {response.get('message')}")
        return {"gainers": [], "losers": []}

    results = response.get("results", []) or []

    movers = []
    for item in results:
        data = item.get("data")
        if not data:
            continue
        try:
            ltp = float(data.get("ltp", 0) or 0)
            prev_close = float(data.get("prev_close", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not prev_close:
            continue
        change_percent = (ltp - prev_close) / prev_close * 100
        movers.append(
            {
                "symbol": item.get("symbol"),
                "exchange": item.get("exchange"),
                "ltp": round(ltp, 2),
                "change_percent": round(change_percent, 2),
            }
        )

    movers.sort(key=lambda m: m["change_percent"], reverse=True)
    gainers = [m for m in movers if m["change_percent"] > 0][:limit]
    losers = sorted(
        [m for m in movers if m["change_percent"] < 0], key=lambda m: m["change_percent"]
    )[:limit]

    return {"gainers": gainers, "losers": losers}
