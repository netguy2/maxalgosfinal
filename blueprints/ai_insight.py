# blueprints/ai_insight.py
"""
AI Insight Blueprint

Advisory-only endpoint: analyzes the currently open symbol's recent bars
+ already-computed indicators via the user's own configured AI provider
(database/ai_settings_db.py) and returns a structured suggestion for the
Charts page (components/charts/AiInsightCard.tsx) to render. Never
places or influences an order -- output is read-only.

Session/cookie authenticated and NOT exempted from Flask-WTF's global
CSRFProtect (frontend uses webClient). Rate-limited via the same
Flask-Limiter convention as restx_api/place_order.py, since each call is
real per-request spend against the user's own AI provider account.
"""

import os
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request, session

from limiter import limiter
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

ai_insight_bp = Blueprint("ai_insight_bp", __name__, url_prefix="/ai-insight")

# Conservative default -- this is real per-call spend against the user's
# own AI provider account, independent of whatever limit their provider
# account itself enforces.
AI_INSIGHT_RATE_LIMIT = os.getenv("AI_INSIGHT_RATE_LIMIT", "10 per hour")

# Keep the prompt small and bounded -- last N bars only, not full history.
_RECENT_BARS_WINDOW = 20

# Indicator functions available to bundle into the prompt, keyed by the
# same names services/historify_service.py's _INDICATOR_SPECS already
# uses -- reuses computation the user already triggered for their chart,
# never recomputes from scratch with different params.
_SINGLE_INDICATORS = {
    "EMA_20": ("compute_ema", {"period": 20}),
    "SMA_50": ("compute_sma", {"period": 50}),
    "VWAP": ("compute_vwap", {}),
    "RSI_14": ("compute_rsi", {"period": 14}),
    "ATR_14": ("compute_atr", {"period": 14}),
}
_MULTI_INDICATORS = {
    "MACD": "compute_macd",
    "BOLLINGER": "compute_bollinger",
    "STOCH": "compute_stochastic",
}


def _get_market_context(api_key: str) -> dict:
    """Best-effort broader market-risk readings to give the AI something
    beyond this one symbol's own price/indicators, without a net-new data
    integration -- both are public quotes fetched through the exact same
    api_key-based quotes_service.get_quotes() path the rest of the
    platform already uses (services/quotes_service.py), not a new external
    API or news/sentiment source.

    - India VIX (symbol INDIAVIX, exchange NSE_INDEX): the market-wide
      volatility/fear gauge -- meaningful for every symbol regardless of
      exchange or asset class, unlike PCR/OI/Max Pain which only apply to
      index/F&O underlyings and would need expiry resolution to fetch.
    - GIFT NIFTY (symbol GIFTNIFTY, exchange GLOBAL_INDEX, Zerodha-only
      per broker/zerodha/database/master_contract_db.py): overnight/
      pre-market signal for likely NIFTY gap risk at the next session
      open.

    Either or both may be unavailable depending on the user's connected
    broker/symbol master -- each is fetched independently and simply
    omitted (never fabricated) on failure, so one missing reading never
    blocks the other or the insight as a whole.
    """
    from services.quotes_service import get_quotes

    context: dict = {}

    try:
        success, response, _status = get_quotes("INDIAVIX", "NSE_INDEX", api_key=api_key)
        if success:
            ltp = response.get("data", {}).get("ltp")
            if ltp is not None:
                context["india_vix"] = ltp
    except Exception as e:
        logger.debug(f"AI Insight: India VIX quote unavailable: {e}")

    try:
        success, response, _status = get_quotes("GIFTNIFTY", "GLOBAL_INDEX", api_key=api_key)
        if success:
            data = response.get("data", {})
            gift_ltp = data.get("ltp")
            # NIFTY's own previous close is the reference GIFT NIFTY's
            # premium/discount is measured against, not GIFT NIFTY's own
            # prior close -- that's what makes the reading a gap-risk
            # signal rather than just GIFT NIFTY's own day-over-day move.
            nifty_success, nifty_response, _ns = get_quotes("NIFTY", "NSE_INDEX", api_key=api_key)
            nifty_prev_close = (
                nifty_response.get("data", {}).get("prev_close") if nifty_success else None
            )
            if gift_ltp is not None and nifty_prev_close:
                context["gift_nifty_change_pct"] = round(
                    (gift_ltp - nifty_prev_close) / nifty_prev_close * 100, 2
                )
    except Exception as e:
        logger.debug(f"AI Insight: GIFT NIFTY quote unavailable: {e}")

    return context


@ai_insight_bp.route("/api/analyze", methods=["POST"])
@check_session_validity
@limiter.limit(AI_INSIGHT_RATE_LIMIT)
def analyze():
    """Body: {symbol, exchange, interval, indicators?, live_price?}
    `indicators` is an optional list of keys from the same set the Charts
    page's overlay chips use (EMA, SMA, VWAP, RSI, MACD, ATR, BOLLINGER,
    STOCH) -- when given, only those are computed and sent to the AI, so
    the analysis matches what the user is actually looking at instead of
    a fixed bundle they may not have enabled. Omitted/empty means "use the
    full default set" (backward compatible with older frontend builds).
    `live_price` is the chart's current live tick, more recent than the
    last closed candle -- included in the prompt so the model isn't
    reasoning off a stale bar."""
    try:
        from database.ai_settings_db import get_ai_settings_decrypted
        from database.auth_db import get_api_key_for_tradingview
        from services import indicator_series_service as iss
        from services.ai_insight_service import AiInsightError, get_ai_insight
        from services.history_service import get_history

        data = request.get_json(silent=True) or {}
        symbol = (data.get("symbol") or "").strip().upper()
        exchange = (data.get("exchange") or "").strip().upper()
        interval = (data.get("interval") or "5m").strip()
        requested_indicators = data.get("indicators")
        requested_keys = (
            {str(k).upper() for k in requested_indicators}
            if isinstance(requested_indicators, list) and requested_indicators
            else None
        )
        live_price = data.get("live_price")
        try:
            live_price = float(live_price) if live_price is not None else None
        except (TypeError, ValueError):
            live_price = None
        if not symbol or not exchange:
            return jsonify({"status": "error", "message": "symbol and exchange are required"}), 400

        user = session.get("user")

        settings = get_ai_settings_decrypted(user)
        if not settings:
            return jsonify(
                {"status": "error", "message": "Configure your AI provider in Settings first"}
            ), 400

        api_key = get_api_key_for_tradingview(user)
        if not api_key:
            return jsonify(
                {"status": "error", "message": "No API key found. Please generate an API key first."}
            ), 400

        default_start = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        default_end = datetime.now().strftime("%Y-%m-%d")
        success, response, status_code = get_history(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=default_start,
            end_date=default_end,
            api_key=api_key,
        )
        if not success:
            return jsonify(response), status_code

        bars = response.get("data", [])
        if not bars:
            return jsonify({"status": "error", "message": "No chart data available"}), 400

        import pandas as pd

        df = pd.DataFrame(bars).sort_values("timestamp").reset_index(drop=True)

        # _SINGLE_INDICATORS/_MULTI_INDICATORS keys carry a "_20"/"_14"-style
        # suffix (e.g. "EMA_20") while the frontend's overlay chips use the
        # bare indicator name (e.g. "EMA") -- match on the prefix before the
        # first underscore so "EMA" selects "EMA_20", "RSI" selects
        # "RSI_14", etc. Multi-output names (MACD/BOLLINGER/STOCH) have no
        # suffix and match directly.
        def _indicator_selected(indicator_key: str) -> bool:
            if requested_keys is None:
                return True
            return indicator_key.split("_")[0] in requested_keys

        indicator_snapshot = {}
        for name, (func_name, kwargs) in _SINGLE_INDICATORS.items():
            if not _indicator_selected(name):
                continue
            points = getattr(iss, func_name)(df, **kwargs)
            if points:
                indicator_snapshot[name] = points[-1]["value"]
        for name, func_name in _MULTI_INDICATORS.items():
            if not _indicator_selected(name):
                continue
            sub_series = getattr(iss, func_name)(df)
            last_values = {k: v[-1]["value"] for k, v in sub_series.items() if v}
            if last_values:
                indicator_snapshot[name] = last_values

        # ATR and support/resistance always computed regardless of the
        # user's selected overlay indicators -- these feed trade_levels
        # (stop-loss/target/position sizing), not the chart display, so
        # they shouldn't be gated by requested_keys the way display
        # indicators are above.
        atr_points = iss.compute_atr(df, period=14)
        atr = atr_points[-1]["value"] if atr_points else None
        support_resistance = iss.compute_support_resistance(df)
        market_context = _get_market_context(api_key)

        recent_bars = bars[-_RECENT_BARS_WINDOW:]

        # Session OHLC from today's bars in the already-fetched window --
        # gives the model today's actual range/open and yesterday's close,
        # not just the tail of `recent_bars`. `interval` can be sub-day
        # (e.g. "5m"), so "today" is derived from the bar timestamps
        # themselves rather than assumed to be the whole `bars` list.
        session_ohlc = None
        if bars:
            last_ts = bars[-1]["timestamp"]
            last_day_start = datetime.fromtimestamp(last_ts).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            today_bars = [
                b for b in bars if datetime.fromtimestamp(b["timestamp"]) >= last_day_start
            ]
            prior_bars = [
                b for b in bars if datetime.fromtimestamp(b["timestamp"]) < last_day_start
            ]
            if today_bars:
                session_ohlc = {
                    "open": today_bars[0]["open"],
                    "high": max(b["high"] for b in today_bars),
                    "low": min(b["low"] for b in today_bars),
                    "prev_close": prior_bars[-1]["close"] if prior_bars else None,
                }

        insight = get_ai_insight(
            provider=settings["provider"],
            api_key=settings["apiKey"],
            model=settings["model"],
            base_url=settings["baseUrl"],
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            recent_bars=recent_bars,
            indicator_snapshot=indicator_snapshot,
            live_price=live_price,
            session_ohlc=session_ohlc,
            atr=atr,
            support_resistance=support_resistance,
            market_context=market_context,
        )
        return jsonify({"status": "success", "data": insight}), 200
    except AiInsightError as e:
        return jsonify({"status": "error", "message": str(e)}), 502
    except Exception as e:
        logger.exception(f"Error generating AI insight: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
