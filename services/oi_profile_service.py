"""
OI Profile Service
Combines futures candlestick data with options Open Interest profile.

Three panels:
  1. Futures OHLC candles (intraday, user-selected interval)
  2. Current OI butterfly (CE right, PE left per strike)
  3. Daily OI change butterfly (CE change right, PE change left)

Current OI is fetched efficiently via option chain (multiquotes).
Daily OI change is computed from daily history (parallel execution).
"""

import time
from datetime import datetime, timedelta
from typing import Any

import pytz

from services.history_service import get_history
from services.option_chain_service import get_option_chain
from services.option_symbol_service import get_futures_symbol as _find_futures_symbol
from services.strategy_chart_service import (
    _cap_last_n_trading_dates,
    _resolve_trading_window,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# Index symbols that need special exchange for quotes
NSE_INDEX_SYMBOLS = {
    "NIFTY",
    "BANKNIFTY",
    "FINNIFTY",
    "MIDCPNIFTY",
    "NIFTYNXT50",
}

BSE_INDEX_SYMBOLS = {"SENSEX", "BANKEX", "SENSEX50"}


def _fetch_daily_oi_changes(
    option_symbols: list[dict], options_exchange: str, api_key: str
) -> dict[str, float]:
    """
    Fetch daily history for options and return previous day's OI.

    Sequential by necessity: services/history_service.py's get_history()
    already enforces a hard process-wide ~3 req/s rate limit via a
    single unlocked module-level timestamp (_enforce_rate_limit -- not
    thread-safe, and every caller of get_history anywhere in the app
    funnels through the same limiter). Running these calls from a thread
    pool would not increase real broker throughput -- callers would just
    contend on the same global sleep -- and risks the unlocked timestamp
    being read/written from multiple threads at once. Retries individual
    429s with exponential backoff.

    Args:
        option_symbols: List of dicts with 'symbol' key
        options_exchange: Exchange for options (NFO, BFO)
        api_key: Max Algos API key

    Returns:
        Dict mapping symbol -> previous_day_oi
    """
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")

    results = {}

    # Only fetch for symbols with non-zero current OI
    symbols_to_fetch = [s["symbol"] for s in option_symbols if s.get("oi", 0) > 0]

    if not symbols_to_fetch:
        return results

    MAX_RETRIES = 2
    RETRY_BASE_DELAY = 1.0  # seconds, doubles each retry

    def fetch_one_with_retry(symbol: str) -> tuple[str, float]:
        for attempt in range(MAX_RETRIES + 1):
            try:
                success, resp, status_code = get_history(
                    symbol=symbol,
                    exchange=options_exchange,
                    interval="D",
                    start_date=start,
                    end_date=end,
                    api_key=api_key,
                )
                if success and resp.get("data"):
                    data = resp["data"]
                    if len(data) >= 2:
                        prev_oi = data[-2].get("oi", 0) or 0
                        return symbol, float(prev_oi)
                    return symbol, 0.0

                # Rate limited - retry with backoff
                if status_code == 429 and attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(f"Rate limited fetching {symbol}, retry {attempt + 1} after {delay}s")
                    time.sleep(delay)
                    continue

                return symbol, 0.0
            except Exception as e:
                if attempt < MAX_RETRIES and "429" in str(e):
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(f"Rate limited fetching {symbol}, retry {attempt + 1} after {delay}s")
                    time.sleep(delay)
                    continue
                return symbol, 0.0
        return symbol, 0.0

    # get_history() already enforces the real rate limit (see docstring
    # above) -- no additional batching/delay needed here.
    for symbol in symbols_to_fetch:
        sym, prev_oi = fetch_one_with_retry(symbol)
        results[sym] = prev_oi

    return results


def get_oi_profile_data(
    underlying: str,
    exchange: str,
    expiry_date: str,
    interval: str,
    days: int,
    api_key: str,
) -> tuple[bool, dict[str, Any], int]:
    """
    Get OI Profile data: futures candles + OI butterfly + OI change.

    Args:
        underlying: Underlying symbol (e.g., NIFTY, BANKNIFTY)
        exchange: Exchange (NFO, BFO)
        expiry_date: Expiry in DDMMMYY format
        interval: Candle interval (1m, 5m, 15m)
        days: Number of days for futures candles
        api_key: Max Algos API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Determine options exchange
        options_exchange = exchange.upper()
        if options_exchange in ("NSE_INDEX", "NSE"):
            options_exchange = "NFO"
        elif options_exchange in ("BSE_INDEX", "BSE"):
            options_exchange = "BFO"

        # Step 1: Get option chain (current OI via multiquotes - efficient)
        success, chain_response, status_code = get_option_chain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=20,
            api_key=api_key,
        )

        if not success:
            return False, chain_response, status_code

        full_chain = chain_response.get("chain", [])
        atm_strike = chain_response.get("atm_strike")
        spot_price = chain_response.get("underlying_ltp")
        lot_size = None

        # Extract current OI data and build symbol list for daily history
        oi_chain = []
        option_symbols_for_history = []

        for item in full_chain:
            strike = item["strike"]
            ce = item.get("ce")
            pe = item.get("pe")

            ce_oi = 0
            pe_oi = 0
            ce_symbol = None
            pe_symbol = None

            if ce:
                ce_oi = ce.get("oi", 0) or 0
                ce_symbol = ce.get("symbol")
                if lot_size is None and ce.get("lotsize"):
                    lot_size = ce["lotsize"]
                if ce_symbol and ce_oi > 0:
                    option_symbols_for_history.append(
                        {"symbol": ce_symbol, "type": "CE", "strike": strike, "oi": ce_oi}
                    )

            if pe:
                pe_oi = pe.get("oi", 0) or 0
                pe_symbol = pe.get("symbol")
                if lot_size is None and pe.get("lotsize"):
                    lot_size = pe["lotsize"]
                if pe_symbol and pe_oi > 0:
                    option_symbols_for_history.append(
                        {"symbol": pe_symbol, "type": "PE", "strike": strike, "oi": pe_oi}
                    )

            oi_chain.append(
                {
                    "strike": strike,
                    "ce_oi": ce_oi,
                    "pe_oi": pe_oi,
                    "ce_symbol": ce_symbol,
                    "pe_symbol": pe_symbol,
                    "ce_oi_change": 0,
                    "pe_oi_change": 0,
                }
            )

        # Step 2: Find futures symbol and fetch candles
        futures_info = _find_futures_symbol(underlying, options_exchange, expiry_date, api_key)
        candles = []
        futures_symbol = None

        if futures_info:
            futures_symbol = futures_info["symbol"]
            fut_exchange = futures_info["exchange"]

            ist = pytz.timezone("Asia/Kolkata")
            # Generous calendar window; post-filter the returned candles to
            # the last N distinct trading dates with data so "3 days" stays
            # 3 days even when queried before market open / on holidays.
            start_date, end_date = _resolve_trading_window(days, ist)

            success_h, hist_response, _ = get_history(
                symbol=futures_symbol,
                exchange=fut_exchange,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
                api_key=api_key,
            )

            if success_h and hist_response.get("data"):
                candles = hist_response["data"]
                # Normalize each candle's timestamp key so the helper can
                # read it — get_history returns `timestamp` in seconds/ms.
                # The helper expects a `time` key (Unix seconds) so tag that
                # from the existing `timestamp` column if needed.
                for c in candles:
                    if "time" not in c and "timestamp" in c:
                        try:
                            ts_val = c["timestamp"]
                            # Heuristic: ms if > 10^12, else seconds.
                            c["time"] = int(ts_val // 1000) if ts_val > 1e12 else int(ts_val)
                        except (TypeError, ValueError):
                            pass
                candles = _cap_last_n_trading_dates(candles, days, ist)

        # Step 3: Fetch daily OI changes (parallel)
        prev_oi_map = _fetch_daily_oi_changes(
            option_symbols_for_history, options_exchange, api_key
        )

        # Step 4: Compute OI changes
        for item in oi_chain:
            ce_sym = item.get("ce_symbol")
            pe_sym = item.get("pe_symbol")

            if ce_sym and ce_sym in prev_oi_map:
                item["ce_oi_change"] = item["ce_oi"] - prev_oi_map[ce_sym]
            if pe_sym and pe_sym in prev_oi_map:
                item["pe_oi_change"] = item["pe_oi"] - prev_oi_map[pe_sym]

        # Remove internal symbol fields from response
        for item in oi_chain:
            item.pop("ce_symbol", None)
            item.pop("pe_symbol", None)

        return (
            True,
            {
                "status": "success",
                "underlying": chain_response.get("underlying", underlying),
                "spot_price": spot_price,
                "atm_strike": atm_strike,
                "lot_size": lot_size or 1,
                "expiry_date": expiry_date,
                "futures_symbol": futures_symbol,
                "interval": interval,
                "candles": candles,
                "oi_chain": oi_chain,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error in get_oi_profile_data: {e}")
        return (
            False,
            {"status": "error", "message": "Error fetching OI Profile data"},
            500,
        )
