import contextvars
import logging
import time
from contextlib import contextmanager

import pandas as pd

logger = logging.getLogger(__name__)

# Scopes an api_key for _fallback_ltp's REST quote fallback (see that
# function's docstring) without threading api_key through calculate()'s
# **kwargs at all 16 _fallback_ltp call sites across every indicator
# plugin below. Mirrors utils/broker_context.py's contextvars pattern for
# the same reason documented there: a plain module global would leak
# across concurrent callers, and threading.local() wouldn't propagate into
# a caller's own worker thread if it ever needed one. Callers with no
# api_key of their own (the vast majority -- anything with a live
# WebSocket-populated market_data_service cache) never set this, so
# _fallback_ltp's behavior for them is unchanged.
_indicator_api_key_var: contextvars.ContextVar = contextvars.ContextVar(
    "indicator_api_key_override", default=None
)
# Scopes the SPECIFIC broker a REST fallback should use, alongside
# _indicator_api_key_var above. Without this, get_quotes/get_history's
# api_key-only path resolves "whichever broker is the user's primary Auth
# session" (get_auth_token_broker) -- which silently ignores the
# deployment's actually-configured broker and returns 0.0/None for every
# indicator whenever that primary session doesn't match, or doesn't exist.
_indicator_broker_var: contextvars.ContextVar = contextvars.ContextVar(
    "indicator_broker_override", default=None
)


@contextmanager
def indicator_api_key_context(api_key: str | None, broker: str | None = None):
    """Scope an api_key (and optionally a specific broker) for every
    indicator calculation inside this block to use as _fallback_ltp's REST
    quote/history fallback. See services/deployment_service.py's evaluation
    loop for the intended caller -- a headless background thread with no
    WebSocket client of its own, so market_data_service's tick cache is
    always empty for it. Passing `broker` (the deployment's configured
    broker) ensures the fallback queries that specific connected broker
    instead of whichever one happens to be the user's primary session."""
    api_key_token = _indicator_api_key_var.set(api_key)
    broker_token = _indicator_broker_var.set(broker)
    try:
        yield
    finally:
        _indicator_api_key_var.reset(api_key_token)
        _indicator_broker_var.reset(broker_token)

# Default candle interval used when a caller doesn't specify one. Must be a
# value services/history_service.py::get_history's broker-facing interval
# param actually supports (1m, 5m, 15m, 1h, D, ...) -- '5m' balances enough
# history for a 14-period RSI/MACD within a single trading day against
# staying responsive intraday.
DEFAULT_INTERVAL = "5m"
# How far back to look. Generous enough that a 26-period MACD (needs the
# most bars of anything here) still has a full window even accounting for
# gaps (holidays, no data yet for a freshly-added symbol).
LOOKBACK_DAYS = 5


class BaseIndicator:
    """Base class for all indicator plugins"""

    def calculate(self, symbol: str, exchange: str, **kwargs) -> float:
        """Calculate and return the indicator value"""
        raise NotImplementedError

    def name(self) -> str:
        raise NotImplementedError

    def inputs(self) -> list:
        """List of input fields/parameters needed"""
        return []

    def outputs(self) -> list:
        """List of output fields returned"""
        return ["value"]


def _lookback_days_for(interval: str, min_bars: int) -> int:
    """LOOKBACK_DAYS (5 calendar days) is sized for intraday intervals --
    it's far too short for daily-bar ("D") strategies that need e.g. 200
    bars for a golden-cross SMA. For daily bars, widen the window to
    comfortably cover min_bars trading days (x1.6 to absorb weekends/
    holidays), with a floor of LOOKBACK_DAYS so intraday callers are
    unaffected."""
    if interval == "D":
        return max(LOOKBACK_DAYS, int(min_bars * 1.6) + 10)
    return LOOKBACK_DAYS


def _fetch_broker_ohlcv_range(symbol: str, exchange: str, interval: str, start_date: str, end_date: str):
    """Fetch real OHLCV candles straight from the broker's own history API
    (services/history_service.py::get_history, source="api" -- the exact
    same broker-backed call the Python Strategy Host's `client.history()`
    SDK method makes, see maxalgos/__init__.py::api.history). Returns a
    pandas DataFrame (oldest first) or None.

    This deliberately does NOT touch Historify/DuckDB (database/
    historify_db.py) at all -- Historify requires a symbol to be manually
    added to a watchlist and backfilled before any data exists for it,
    which would mean every deployed strategy is broken out of the box
    until a user does that extra setup step. Every other live-data feature
    on this platform (Python strategies, Option Chain, quotes) reads
    straight from the broker with zero setup, so indicator calculation
    does the same here -- no watchlist, no backfill, works the moment a
    broker session is connected, matching what users already see working
    elsewhere on the platform.

    Needs an api_key to resolve which broker session to call -- see
    indicator_api_key_context; a caller with no WebSocket-populated cache
    of its own (services/deployment_service.py's headless evaluation loop)
    sets one for the duration of each evaluation cycle. If that caller also
    scoped a specific broker (the deployment's configured one), that is
    passed through too -- otherwise get_history falls back to whichever
    broker happens to be the user's single "primary" Auth session, which
    silently returns no data whenever that doesn't match.
    """
    from services.history_service import get_history

    api_key = _indicator_api_key_var.get()
    if not api_key:
        logger.debug(f"No api_key in scope for {symbol}/{exchange} history fetch -- skipping")
        return None

    broker = _indicator_broker_var.get()
    try:
        success, response, _status = get_history(
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            start_date=start_date,
            end_date=end_date,
            api_key=api_key,
            broker=broker,
        )
    except Exception:
        logger.exception(f"get_history failed for {symbol}/{exchange}/{interval}")
        return None

    if not success:
        logger.debug(
            f"Broker history fetch failed for {symbol}/{exchange}/{interval}: "
            f"{response.get('message') if isinstance(response, dict) else response}"
        )
        return None

    rows = response.get("data") if isinstance(response, dict) else None
    if not rows:
        return None

    df = pd.DataFrame(rows)
    if df.empty:
        return None
    # Broker responses are already oldest-first per every BrokerData.get_history
    # implementation's documented contract (see e.g. broker/zebu/api/data.py).
    return df


def _fetch_broker_ohlcv(symbol: str, exchange: str, interval: str, min_bars: int):
    """Multi-day lookback wrapper around _fetch_broker_ohlcv_range, for
    indicators that need a fixed number of recent bars (as opposed to
    VWAP's today-only session window, which calls the range fetcher
    directly). Returns None if fewer than min_bars candles came back."""
    end_date = time.strftime("%Y-%m-%d")
    start_date = time.strftime(
        "%Y-%m-%d", time.localtime(time.time() - _lookback_days_for(interval, min_bars) * 86400)
    )
    df = _fetch_broker_ohlcv_range(symbol, exchange, interval, start_date, end_date)
    if df is None or len(df) < min_bars:
        return None
    return df


def _get_close_series(symbol: str, exchange: str, interval: str, min_bars: int):
    """Fetch a real close-price series from the broker's own history API
    (see _fetch_broker_ohlcv). Returns a pandas Series (oldest first) or
    None if there isn't enough real history yet.

    This is the one place all trend/momentum indicators below get their
    data from -- swapping the data source only means changing this
    function.
    """
    df = _fetch_broker_ohlcv(symbol, exchange, interval, min_bars)
    if df is None or "close" not in df.columns:
        return None
    return df["close"]


def _fallback_ltp(symbol: str, exchange: str) -> float:
    """Last-resort value when there isn't enough historical candle data yet
    to compute a real indicator (e.g. the broker doesn't have enough bars
    in the requested lookback window yet, or the history call failed).
    Returning the raw LTP rather than a fabricated indicator number is a
    deliberate, honest degradation: a caller comparing this against a
    threshold gets today's real price, not a number dressed up to look
    like an indicator that wasn't actually computed. Logged so it's
    visible in Flow run logs, not silent.

    Picks up an api_key from indicator_api_key_context if the current
    caller set one (see that context manager's docstring) -- lets
    get_ltp_value's REST fallback work for callers with no WebSocket-
    populated cache of their own, without threading api_key through
    calculate()'s **kwargs at every one of this function's 16 call sites.
    """
    from services.market_data_service import get_ltp_value

    logger.warning(
        f"Not enough historical data for {symbol}/{exchange} yet -- "
        f"falling back to raw LTP instead of a computed indicator value."
    )
    api_key = _indicator_api_key_var.get()
    broker = _indicator_broker_var.get()
    return get_ltp_value(symbol, exchange, api_key=api_key, broker=broker) or 0.0


# --- Trend Indicators ---


class EMAIndicator(BaseIndicator):
    def name(self):
        return "EMA"

    def inputs(self):
        return ["period"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 20))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        closes = _get_close_series(symbol, exchange, interval, min_bars=period)
        if closes is None:
            return _fallback_ltp(symbol, exchange)
        # Standard exponential moving average, most recent bar as the
        # current EMA value.
        ema = closes.ewm(span=period, adjust=False).mean()
        return float(ema.iloc[-1])


class SMAIndicator(BaseIndicator):
    def name(self):
        return "SMA"

    def inputs(self):
        return ["period"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 20))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        closes = _get_close_series(symbol, exchange, interval, min_bars=period)
        if closes is None:
            return _fallback_ltp(symbol, exchange)
        return float(closes.tail(period).mean())


class VWAPIndicator(BaseIndicator):
    def name(self):
        return "VWAP"

    def calculate(self, symbol, exchange, **kwargs):
        # VWAP is a same-day, volume-weighted figure -- always computed
        # over today's session, never the multi-day lookback the other
        # indicators use. The broker history API takes date-level
        # start/end, not intraday timestamps, so this just requests
        # today's date and lets the platform-side interval bucketing
        # return only today's session's bars.
        interval = kwargs.get("interval", "1m")
        today = time.strftime("%Y-%m-%d")
        df = _fetch_broker_ohlcv_range(symbol, exchange, interval, today, today)

        if df is None or df.empty or df["volume"].sum() <= 0:
            return _fallback_ltp(symbol, exchange)

        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (typical_price * df["volume"]).sum() / df["volume"].sum()
        return float(vwap)


# --- Momentum Indicators ---


class RSIIndicator(BaseIndicator):
    def name(self):
        return "RSI"

    def inputs(self):
        return ["period"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 14))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        # Wilder's smoothing needs period+1 price changes, so period+1 bars.
        closes = _get_close_series(symbol, exchange, interval, min_bars=period + 1)
        if closes is None:
            return 50.0  # neutral RSI, not a fabricated 30-70 range value

        delta = closes.diff().dropna()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        # Wilder's smoothing (equivalent to an EMA with alpha = 1/period),
        # the standard RSI definition.
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

        last_avg_loss = float(avg_loss.iloc[-1])
        if last_avg_loss == 0:
            return 100.0
        rs = float(avg_gain.iloc[-1]) / last_avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi)


class MACDIndicator(BaseIndicator):
    def name(self):
        return "MACD"

    def inputs(self):
        return ["fast_period", "slow_period"]

    def calculate(self, symbol, exchange, **kwargs):
        fast_period = int(kwargs.get("fast_period", 12))
        slow_period = int(kwargs.get("slow_period", 26))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        closes = _get_close_series(symbol, exchange, interval, min_bars=slow_period)
        if closes is None:
            return 0.0  # neutral (no momentum signal) rather than a fake ltp*0.002

        # MACD line = fast EMA - slow EMA. (Signal-line crossover is a
        # further refinement left to the caller if/when needed -- this
        # returns the MACD line value itself, matching what the fake
        # implementation's single-float contract already promised callers.)
        ema_fast = closes.ewm(span=fast_period, adjust=False).mean()
        ema_slow = closes.ewm(span=slow_period, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        return float(macd_line.iloc[-1])


# --- Volatility Indicators ---


class ATRIndicator(BaseIndicator):
    def name(self):
        return "ATR"

    def inputs(self):
        return ["period"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 14))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        df = _get_ohlcv_window(symbol, exchange, interval, min_bars=period + 1)

        if df is None:
            return _fallback_ltp(symbol, exchange) * 0.015

        high, low, close = df["high"], df["low"], df["close"]
        prev_close = close.shift(1)
        true_range = (
            (high - low)
            .to_frame("hl")
            .assign(hc=(high - prev_close).abs(), lc=(low - prev_close).abs())
            .max(axis=1)
        )
        atr = true_range.ewm(alpha=1 / period, adjust=False).mean()
        return float(atr.iloc[-1])


# --- Breakout Indicators ---


class OpeningRangeIndicator(BaseIndicator):
    """The high or low of the opening range -- the first N minutes of the
    trading session starting 09:15 IST. Powers ORB (Opening Range Breakout)
    strategies (services/strategy_compiler.py::compile_orb), which express
    a breakout as SPOT vs this indicator's value via condition_engine.py's
    value_indicator mechanism, e.g. {"indicator": "SPOT", "condition": ">",
    "value_indicator": "ORB_HIGH", "value_indicator_params": {"duration": 15}}.

    Mirrors VWAPIndicator's same-IST-session-window pattern above, but with
    a FIXED window (session start to session start + duration) rather than
    VWAP's open-ended "start of day to now" window.
    """

    def __init__(self, side: str):
        self.side = side  # "high" or "low"

    def name(self):
        return f"ORB_{self.side.upper()}"

    def inputs(self):
        return ["duration"]

    def calculate(self, symbol, exchange, **kwargs):
        duration_min = int(kwargs.get("duration", 15))
        now = time.time()
        ist_offset = 5.5 * 3600
        seconds_into_day = int((now + ist_offset) % 86400)
        market_open_seconds = 9 * 3600 + 15 * 60  # 09:15 IST
        session_start_ts = int(now - seconds_into_day + market_open_seconds)
        window_end_ts = session_start_ts + duration_min * 60

        if now < session_start_ts:
            # Before today's market open -- no opening range exists yet.
            return _fallback_ltp(symbol, exchange)

        # The broker history API only takes date-level start/end (not
        # intraday timestamps), so fetch today's full 1m session and slice
        # the opening-range window out of it client-side.
        today = time.strftime("%Y-%m-%d")
        df = _fetch_broker_ohlcv_range(symbol, exchange, "1m", today, today)

        if df is None or df.empty or "timestamp" not in df.columns:
            return _fallback_ltp(symbol, exchange)

        window_end = min(int(now), window_end_ts)
        window_df = df[(df["timestamp"] >= session_start_ts) & (df["timestamp"] <= window_end)]

        if window_df.empty:
            return _fallback_ltp(symbol, exchange)

        return float(window_df["high"].max()) if self.side == "high" else float(window_df["low"].min())


# --- Crossover / Transition Indicators ---
# These express a crossover (e.g. "fast EMA just crossed above slow EMA")
# as its own indicator returning 1.0 (crossed this bar) / 0.0 (didn't),
# computed fresh from OHLCV history on every call by comparing the last two
# closed bars -- no state is stored on the Deployment row. This mirrors
# OpeningRangeIndicator's pattern and avoids state-drift bugs on
# pause/resume or missed ticks. A compiled leaf checks
# {"indicator": "EMA_CROSS_UP", "condition": ">", "value": 0.5} (i.e. "== 1").


def _get_ohlcv_window(symbol: str, exchange: str, interval: str, min_bars: int):
    """Like _get_close_series but returns the full OHLCV DataFrame (oldest
    first), for indicators that need more than just close (e.g. swing
    high/low, previous day levels). Returns None if there isn't enough
    real history yet. See _fetch_broker_ohlcv's docstring for why this
    reads straight from the broker instead of Historify/DuckDB."""
    return _fetch_broker_ohlcv(symbol, exchange, interval, min_bars)


class EMACrossIndicator(BaseIndicator):
    """1.0 if fast EMA crossed the slow EMA in the specified direction on
    the most recently closed bar, else 0.0."""

    def __init__(self, direction: str):
        self.direction = direction  # "up" or "down"

    def name(self):
        return f"EMA_CROSS_{self.direction.upper()}"

    def inputs(self):
        return ["fast_period", "slow_period"]

    def calculate(self, symbol, exchange, **kwargs):
        fast_period = int(kwargs.get("fast_period", 9))
        slow_period = int(kwargs.get("slow_period", 21))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        closes = _get_close_series(symbol, exchange, interval, min_bars=slow_period + 1)
        if closes is None:
            return 0.0

        fast_ema = closes.ewm(span=fast_period, adjust=False).mean()
        slow_ema = closes.ewm(span=slow_period, adjust=False).mean()
        prev_fast, curr_fast = float(fast_ema.iloc[-2]), float(fast_ema.iloc[-1])
        prev_slow, curr_slow = float(slow_ema.iloc[-2]), float(slow_ema.iloc[-1])

        if self.direction == "up":
            crossed = prev_fast <= prev_slow and curr_fast > curr_slow
        else:
            crossed = prev_fast >= prev_slow and curr_fast < curr_slow
        return 1.0 if crossed else 0.0


class SMACrossIndicator(BaseIndicator):
    """1.0 if fast SMA crossed the slow SMA in the specified direction on
    the most recently closed bar, else 0.0."""

    def __init__(self, direction: str):
        self.direction = direction

    def name(self):
        return f"SMA_CROSS_{self.direction.upper()}"

    def inputs(self):
        return ["fast_period", "slow_period"]

    def calculate(self, symbol, exchange, **kwargs):
        fast_period = int(kwargs.get("fast_period", 50))
        slow_period = int(kwargs.get("slow_period", 200))
        interval = kwargs.get("interval", "D")
        closes = _get_close_series(symbol, exchange, interval, min_bars=slow_period + 1)
        if closes is None:
            return 0.0

        fast_sma = closes.rolling(window=fast_period).mean()
        slow_sma = closes.rolling(window=slow_period).mean()
        prev_fast, curr_fast = float(fast_sma.iloc[-2]), float(fast_sma.iloc[-1])
        prev_slow, curr_slow = float(slow_sma.iloc[-2]), float(slow_sma.iloc[-1])

        if self.direction == "up":
            crossed = prev_fast <= prev_slow and curr_fast > curr_slow
        else:
            crossed = prev_fast >= prev_slow and curr_fast < curr_slow
        return 1.0 if crossed else 0.0


class MACDCrossIndicator(BaseIndicator):
    """1.0 if the MACD line crossed its signal line in the specified
    direction on the most recently closed bar, else 0.0."""

    def __init__(self, direction: str):
        self.direction = direction

    def name(self):
        return f"MACD_CROSS_{self.direction.upper()}"

    def inputs(self):
        return ["fast_period", "slow_period", "signal_period"]

    def calculate(self, symbol, exchange, **kwargs):
        fast_period = int(kwargs.get("fast_period", 12))
        slow_period = int(kwargs.get("slow_period", 26))
        signal_period = int(kwargs.get("signal_period", 9))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        closes = _get_close_series(symbol, exchange, interval, min_bars=slow_period + signal_period)
        if closes is None:
            return 0.0

        ema_fast = closes.ewm(span=fast_period, adjust=False).mean()
        ema_slow = closes.ewm(span=slow_period, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()

        prev_macd, curr_macd = float(macd_line.iloc[-2]), float(macd_line.iloc[-1])
        prev_signal, curr_signal = float(signal_line.iloc[-2]), float(signal_line.iloc[-1])

        if self.direction == "up":
            crossed = prev_macd <= prev_signal and curr_macd > curr_signal
        else:
            crossed = prev_macd >= prev_signal and curr_macd < curr_signal
        return 1.0 if crossed else 0.0


class RSIThresholdCrossIndicator(BaseIndicator):
    """1.0 if RSI crossed the given threshold in the specified direction on
    the most recently closed bar, else 0.0. Used for RSI reversal
    strategies (e.g. "RSI crossed back up through 30" = oversold bounce)."""

    def __init__(self, direction: str):
        self.direction = direction  # "up_thru" or "down_thru"

    def name(self):
        return f"RSI_CROSS_{self.direction.upper()}"

    def inputs(self):
        return ["period", "threshold"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 14))
        threshold = float(kwargs.get("threshold", 30 if self.direction == "up_thru" else 70))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        closes = _get_close_series(symbol, exchange, interval, min_bars=period + 2)
        if closes is None:
            return 0.0

        delta = closes.diff().dropna()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, float("nan"))
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(100)

        if len(rsi) < 2:
            return 0.0
        prev_rsi, curr_rsi = float(rsi.iloc[-2]), float(rsi.iloc[-1])

        if self.direction == "up_thru":
            crossed = prev_rsi <= threshold and curr_rsi > threshold
        else:
            crossed = prev_rsi >= threshold and curr_rsi < threshold
        return 1.0 if crossed else 0.0


class ROCIndicator(BaseIndicator):
    """Rate of Change: percentage price change over `period` bars."""

    def name(self):
        return "ROC"

    def inputs(self):
        return ["period"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 12))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        closes = _get_close_series(symbol, exchange, interval, min_bars=period + 1)
        if closes is None:
            return 0.0

        prev_close = float(closes.iloc[-1 - period])
        curr_close = float(closes.iloc[-1])
        if prev_close == 0:
            return 0.0
        return ((curr_close - prev_close) / prev_close) * 100.0


class SwingLevelIndicator(BaseIndicator):
    """Highest high / lowest low over the last `period` closed bars,
    EXCLUDING the current (most recent) bar -- a swing level is a level
    formed by prior price action, not the bar that's testing it."""

    def __init__(self, side: str):
        self.side = side  # "high" or "low"

    def name(self):
        return f"SWING_{self.side.upper()}"

    def inputs(self):
        return ["period"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 20))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        df = _get_ohlcv_window(symbol, exchange, interval, min_bars=period + 1)
        if df is None:
            return _fallback_ltp(symbol, exchange)

        window = df.iloc[-1 - period:-1]
        if window.empty:
            return _fallback_ltp(symbol, exchange)
        return float(window["high"].max()) if self.side == "high" else float(window["low"].min())


class PrevDayLevelIndicator(BaseIndicator):
    """Previous trading day's high/low/close, derived from daily bars."""

    def __init__(self, field: str):
        self.field = field  # "high", "low", or "close"

    def name(self):
        return f"PREV_DAY_{self.field.upper()}"

    def calculate(self, symbol, exchange, **kwargs):
        df = _get_ohlcv_window(symbol, exchange, "D", min_bars=2)
        if df is None:
            return _fallback_ltp(symbol, exchange)
        prev_day = df.iloc[-2]
        return float(prev_day[self.field])


# --- Trend-Stack / Volatility-Band / Pattern Indicators ---
# Round 2: powers the remaining marketplace strategy types (Triple EMA,
# Supertrend, ADX, Volume Breakout, Bollinger, Keltner, Donchian, ATR trail,
# candlestick patterns, gap). Same stateless-recompute-from-OHLCV pattern as
# the crossover indicators above -- no state stored on the Deployment row.


def _atr_series(df, period):
    """Shared ATR (Average True Range) computation on a full OHLCV
    DataFrame. Simple rolling mean of True Range, matching the reference
    Python-generator implementations (frontend/src/lib/python-strategy-
    generator.ts's `_atr` helper) -- NOT Wilder's smoothing, to stay
    consistent with what the generated Python strategies already do."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period).mean()


class TripleEMAStackIndicator(BaseIndicator):
    """1.0 if fast/mid/slow EMAs are stacked in the given direction
    (fast > mid > slow for "up", fast < mid < slow for "down") on the most
    recently closed bar, else 0.0."""

    def __init__(self, direction: str):
        self.direction = direction  # "up" or "down"

    def name(self):
        return f"TRIPLE_EMA_{self.direction.upper()}"

    def inputs(self):
        return ["fast_period", "mid_period", "slow_period"]

    def calculate(self, symbol, exchange, **kwargs):
        fast_period = int(kwargs.get("fast_period", 5))
        mid_period = int(kwargs.get("mid_period", 13))
        slow_period = int(kwargs.get("slow_period", 34))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        closes = _get_close_series(symbol, exchange, interval, min_bars=slow_period + 1)
        if closes is None:
            return 0.0

        ema_fast = float(closes.ewm(span=fast_period, adjust=False).mean().iloc[-1])
        ema_mid = float(closes.ewm(span=mid_period, adjust=False).mean().iloc[-1])
        ema_slow = float(closes.ewm(span=slow_period, adjust=False).mean().iloc[-1])

        if self.direction == "up":
            stacked = ema_fast > ema_mid > ema_slow
        else:
            stacked = ema_fast < ema_mid < ema_slow
        return 1.0 if stacked else 0.0


class SupertrendFlipIndicator(BaseIndicator):
    """1.0 if the Supertrend direction flipped (bullish/bearish) on the
    most recently closed bar, else 0.0. Mirrors the reference Python
    generator's iterative trend-band algorithm."""

    def __init__(self, direction: str):
        self.direction = direction  # "up" (flip to bullish) or "down" (flip to bearish)

    def name(self):
        return f"SUPERTREND_FLIP_{self.direction.upper()}"

    def inputs(self):
        return ["atr_period", "atr_multiplier"]

    def calculate(self, symbol, exchange, **kwargs):
        atr_period = int(kwargs.get("atr_period", 10))
        multiplier = float(kwargs.get("atr_multiplier", 3.0))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        df = _get_ohlcv_window(symbol, exchange, interval, min_bars=atr_period + 3)
        if df is None:
            return 0.0

        atr = _atr_series(df, atr_period)
        hl2 = (df["high"] + df["low"]) / 2
        upper_band = hl2 + multiplier * atr
        lower_band = hl2 - multiplier * atr
        close = df["close"]

        trend = [1.0] * len(df)
        for i in range(1, len(df)):
            if pd.isna(upper_band.iloc[i - 1]):
                trend[i] = trend[i - 1]
            elif close.iloc[i] > upper_band.iloc[i - 1]:
                trend[i] = 1.0
            elif close.iloc[i] < lower_band.iloc[i - 1]:
                trend[i] = -1.0
            else:
                trend[i] = trend[i - 1]

        if len(trend) < 2:
            return 0.0
        prev_trend, curr_trend = trend[-2], trend[-1]
        if self.direction == "up":
            flipped = prev_trend == -1.0 and curr_trend == 1.0
        else:
            flipped = prev_trend == 1.0 and curr_trend == -1.0
        return 1.0 if flipped else 0.0


class ADXTrendIndicator(BaseIndicator):
    """1.0 if ADX confirms a trending market (ADX above threshold) AND
    +DI/-DI agree with the requested direction on the most recently closed
    bar, else 0.0."""

    def __init__(self, direction: str):
        self.direction = direction  # "up" or "down"

    def name(self):
        return f"ADX_TREND_{self.direction.upper()}"

    def inputs(self):
        return ["period", "threshold"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 14))
        threshold = float(kwargs.get("threshold", 25))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        df = _get_ohlcv_window(symbol, exchange, interval, min_bars=period * 2 + 1)
        if df is None:
            return 0.0

        high, low = df["high"], df["low"]
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
        minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move
        atr = _atr_series(df, period)
        plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
        adx = dx.rolling(period).mean()

        if adx.empty or pd.isna(adx.iloc[-1]):
            return 0.0
        if float(adx.iloc[-1]) < threshold:
            return 0.0

        trending_up = float(plus_di.iloc[-1]) > float(minus_di.iloc[-1])
        if self.direction == "up":
            return 1.0 if trending_up else 0.0
        return 1.0 if not trending_up else 0.0


class VolumeSurgeIndicator(BaseIndicator):
    """1.0 if the most recently closed bar's volume exceeds `multiplier`x
    its rolling average volume, else 0.0."""

    def name(self):
        return "VOLUME_SURGE"

    def inputs(self):
        return ["period", "multiplier"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 20))
        multiplier = float(kwargs.get("multiplier", 2.0))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        df = _get_ohlcv_window(symbol, exchange, interval, min_bars=period + 1)
        if df is None:
            return 0.0

        avg_volume = df["volume"].rolling(period).mean()
        if avg_volume.empty or pd.isna(avg_volume.iloc[-2]):
            return 0.0
        last_volume = float(df["volume"].iloc[-1])
        prev_avg = float(avg_volume.iloc[-2])
        if prev_avg <= 0:
            return 0.0
        return 1.0 if last_volume > prev_avg * multiplier else 0.0


class BollingerBandIndicator(BaseIndicator):
    """Upper/lower Bollinger Band value on the most recently closed bar."""

    def __init__(self, side: str):
        self.side = side  # "upper" or "lower"

    def name(self):
        return f"BB_{self.side.upper()}"

    def inputs(self):
        return ["period", "stddev"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 20))
        stddev = float(kwargs.get("stddev", 2.0))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        closes = _get_close_series(symbol, exchange, interval, min_bars=period + 1)
        if closes is None:
            return _fallback_ltp(symbol, exchange)

        mid = closes.rolling(period).mean()
        std = closes.rolling(period).std()
        if pd.isna(mid.iloc[-1]) or pd.isna(std.iloc[-1]):
            return _fallback_ltp(symbol, exchange)
        band = mid.iloc[-1] + stddev * std.iloc[-1] if self.side == "upper" else mid.iloc[-1] - stddev * std.iloc[-1]
        return float(band)


class BollingerSqueezeIndicator(BaseIndicator):
    """1.0 if Bollinger bandwidth was in a low-volatility squeeze
    (bottom `percentile`th of the last `lookback` bars) on the PRIOR bar
    and price has now broken out beyond the band in the given direction,
    else 0.0."""

    def __init__(self, direction: str):
        self.direction = direction  # "up" or "down"

    def name(self):
        return f"BB_SQUEEZE_BREAKOUT_{self.direction.upper()}"

    def inputs(self):
        return ["period", "stddev", "lookback", "percentile"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 20))
        stddev = float(kwargs.get("stddev", 2.0))
        lookback = int(kwargs.get("lookback", 50))
        percentile = float(kwargs.get("percentile", 20))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        closes = _get_close_series(symbol, exchange, interval, min_bars=period + lookback)
        if closes is None:
            return 0.0

        mid = closes.rolling(period).mean()
        std = closes.rolling(period).std()
        bandwidth = (2 * stddev * std) / mid
        recent_bandwidth = bandwidth.iloc[-lookback:]
        if recent_bandwidth.isna().all():
            return 0.0
        threshold = recent_bandwidth.quantile(percentile / 100)
        if len(bandwidth) < 3 or pd.isna(bandwidth.iloc[-2]):
            return 0.0
        was_squeezed = bool(bandwidth.iloc[-2] <= threshold)
        if not was_squeezed:
            return 0.0

        upper = float((mid + stddev * std).iloc[-1])
        lower = float((mid - stddev * std).iloc[-1])
        last_close = float(closes.iloc[-1])
        if self.direction == "up":
            return 1.0 if last_close > upper else 0.0
        return 1.0 if last_close < lower else 0.0


class KeltnerChannelIndicator(BaseIndicator):
    """Upper/lower Keltner Channel value (EMA midline +/- ATR multiple) on
    the most recently closed bar."""

    def __init__(self, side: str):
        self.side = side  # "upper" or "lower"

    def name(self):
        return f"KELTNER_{self.side.upper()}"

    def inputs(self):
        return ["ema_period", "atr_period", "atr_multiplier"]

    def calculate(self, symbol, exchange, **kwargs):
        ema_period = int(kwargs.get("ema_period", 20))
        atr_period = int(kwargs.get("atr_period", 10))
        multiplier = float(kwargs.get("atr_multiplier", 2.0))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        df = _get_ohlcv_window(symbol, exchange, interval, min_bars=max(ema_period, atr_period) + 1)
        if df is None:
            return _fallback_ltp(symbol, exchange)

        mid = df["close"].ewm(span=ema_period, adjust=False).mean()
        atr = _atr_series(df, atr_period)
        if pd.isna(mid.iloc[-1]) or pd.isna(atr.iloc[-1]):
            return _fallback_ltp(symbol, exchange)
        band = mid.iloc[-1] + multiplier * atr.iloc[-1] if self.side == "upper" else mid.iloc[-1] - multiplier * atr.iloc[-1]
        return float(band)


class DonchianMidCrossIndicator(BaseIndicator):
    """1.0 if price crossed the Donchian channel midline in the given
    direction on the most recently closed bar, else 0.0. Powers Donchian
    pullback/bounce strategies."""

    def __init__(self, direction: str):
        self.direction = direction  # "up" or "down"

    def name(self):
        return f"DONCHIAN_MID_CROSS_{self.direction.upper()}"

    def inputs(self):
        return ["period"]

    def calculate(self, symbol, exchange, **kwargs):
        period = int(kwargs.get("period", 20))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        df = _get_ohlcv_window(symbol, exchange, interval, min_bars=period + 2)
        if df is None:
            return 0.0

        upper = df["high"].rolling(period).max()
        lower = df["low"].rolling(period).min()
        mid = (upper + lower) / 2
        close = df["close"]
        if len(close) < 2 or pd.isna(mid.iloc[-2]):
            return 0.0
        prev_close, curr_close = float(close.iloc[-2]), float(close.iloc[-1])
        prev_mid = float(mid.iloc[-2])

        if self.direction == "up":
            crossed = prev_close <= prev_mid and curr_close > prev_mid
        else:
            crossed = prev_close >= prev_mid and curr_close < prev_mid
        return 1.0 if crossed else 0.0


class ATRTrailCrossIndicator(BaseIndicator):
    """1.0 if price crossed an EMA-anchored ATR trailing stop in the given
    direction on the most recently closed bar, else 0.0."""

    def __init__(self, direction: str):
        self.direction = direction  # "up" (entry) or "down" (stop-out/exit)

    def name(self):
        return f"ATR_TRAIL_CROSS_{self.direction.upper()}"

    def inputs(self):
        return ["atr_period", "ema_period", "atr_multiplier"]

    def calculate(self, symbol, exchange, **kwargs):
        atr_period = int(kwargs.get("atr_period", 14))
        ema_period = int(kwargs.get("ema_period", 20))
        multiplier = float(kwargs.get("atr_multiplier", 1.5))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        df = _get_ohlcv_window(symbol, exchange, interval, min_bars=max(atr_period, ema_period) + 2)
        if df is None:
            return 0.0

        atr = _atr_series(df, atr_period)
        ema = df["close"].ewm(span=ema_period, adjust=False).mean()
        trail_stop = ema - multiplier * atr
        close = df["close"]
        if len(close) < 2 or pd.isna(trail_stop.iloc[-2]):
            return 0.0
        prev_close, curr_close = float(close.iloc[-2]), float(close.iloc[-1])
        prev_stop, curr_stop = float(trail_stop.iloc[-2]), float(trail_stop.iloc[-1])

        if self.direction == "up":
            crossed = prev_close <= prev_stop and curr_close > prev_stop
        else:
            crossed = curr_close < curr_stop
        return 1.0 if crossed else 0.0


class GapPercentIndicator(BaseIndicator):
    """Today's opening gap vs yesterday's close, as a signed percentage."""

    def name(self):
        return "GAP_PCT"

    def calculate(self, symbol, exchange, **kwargs):
        df = _get_ohlcv_window(symbol, exchange, "D", min_bars=2)
        if df is None:
            return 0.0
        prev_close = float(df["close"].iloc[-2])
        today_open = float(df["open"].iloc[-1])
        if prev_close == 0:
            return 0.0
        return ((today_open - prev_close) / prev_close) * 100.0


class InsideCandleBreakoutIndicator(BaseIndicator):
    """1.0 if the prior closed bar was an inside candle (high/low fully
    within the bar before it) AND the current bar has broken out beyond
    the "mother" candle's range in the given direction, else 0.0."""

    def __init__(self, direction: str):
        self.direction = direction  # "up" or "down"

    def name(self):
        return f"INSIDE_CANDLE_BREAKOUT_{self.direction.upper()}"

    def calculate(self, symbol, exchange, **kwargs):
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        df = _get_ohlcv_window(symbol, exchange, interval, min_bars=3)
        if df is None or len(df) < 3:
            return 0.0

        mother, inside, last = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        is_inside = inside["high"] < mother["high"] and inside["low"] > mother["low"]
        if not is_inside:
            return 0.0

        if self.direction == "up":
            return 1.0 if float(last["close"]) > float(mother["high"]) else 0.0
        return 1.0 if float(last["close"]) < float(mother["low"]) else 0.0


class NR7BreakoutIndicator(BaseIndicator):
    """1.0 if the prior closed bar was an NR7 (narrowest range of the last
    7 bars) AND the current bar has broken out beyond that NR7 bar's
    range in the given direction, else 0.0."""

    def __init__(self, direction: str):
        self.direction = direction  # "up" or "down"

    def name(self):
        return f"NR7_BREAKOUT_{self.direction.upper()}"

    def calculate(self, symbol, exchange, **kwargs):
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        df = _get_ohlcv_window(symbol, exchange, interval, min_bars=9)
        if df is None or len(df) < 9:
            return 0.0

        ranges = df["high"] - df["low"]
        last7 = ranges.iloc[-8:-1]
        is_nr7 = bool(last7.iloc[-1] == last7.min())
        if not is_nr7:
            return 0.0

        nr7_bar = df.iloc[-2]
        latest_close = float(df["close"].iloc[-1])
        if self.direction == "up":
            return 1.0 if latest_close > float(nr7_bar["high"]) else 0.0
        return 1.0 if latest_close < float(nr7_bar["low"]) else 0.0


class VWAPDeviationIndicator(BaseIndicator):
    """1.0 if the most recently closed bar's close deviated from today's
    session VWAP by more than `threshold_pct` in the given direction, else
    0.0. Powers VWAP reversion/scalp strategies (a deviation, not a
    crossover)."""

    def __init__(self, direction: str):
        self.direction = direction  # "below" (oversold vs VWAP) or "above"

    def name(self):
        return f"VWAP_DEVIATION_{self.direction.upper()}"

    def inputs(self):
        return ["threshold_pct"]

    def calculate(self, symbol, exchange, **kwargs):
        threshold_pct = float(kwargs.get("threshold_pct", 0.5))
        interval = kwargs.get("interval", "1m")
        today = time.strftime("%Y-%m-%d")
        df = _fetch_broker_ohlcv_range(symbol, exchange, interval, today, today)

        if df is None or df.empty or df["volume"].sum() <= 0 or len(df) < 2:
            return 0.0

        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
        last_close = float(df["close"].iloc[-1])
        last_vwap = float(vwap.iloc[-1])
        if last_vwap == 0:
            return 0.0
        deviation_pct = (last_close - last_vwap) / last_vwap * 100.0

        if self.direction == "below":
            return 1.0 if deviation_pct < -threshold_pct else 0.0
        return 1.0 if deviation_pct > threshold_pct else 0.0


class VWAPScalpCrossIndicator(BaseIndicator):
    """1.0 if price crossed today's session VWAP in the given direction on
    the most recently closed bar, else 0.0 -- a transition, not merely a
    deviation (that's VWAPDeviationIndicator, a different strategy shape).
    """

    def __init__(self, direction: str):
        self.direction = direction  # "up" or "down"

    def name(self):
        return f"VWAP_CROSS_{self.direction.upper()}"

    def calculate(self, symbol, exchange, **kwargs):
        interval = kwargs.get("interval", "1m")
        today = time.strftime("%Y-%m-%d")
        df = _fetch_broker_ohlcv_range(symbol, exchange, interval, today, today)

        if df is None or df.empty or df["volume"].sum() <= 0 or len(df) < 3:
            return 0.0

        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        vwap = (typical_price * df["volume"]).cumsum() / df["volume"].cumsum()
        close = df["close"]
        prev_close, curr_close = float(close.iloc[-2]), float(close.iloc[-1])
        prev_vwap = float(vwap.iloc[-2])

        if self.direction == "up":
            crossed = prev_close <= prev_vwap and curr_close > prev_vwap
        else:
            crossed = prev_close >= prev_vwap and curr_close < prev_vwap
        return 1.0 if crossed else 0.0


class EMAPullbackIndicator(BaseIndicator):
    """1.0 if price is in an uptrend (trend EMA below the pullback EMA),
    the prior bar's low touched the pullback EMA, and the current close is
    back above it (a pullback-and-bounce entry), else 0.0."""

    def name(self):
        return "EMA_PULLBACK_BOUNCE"

    def inputs(self):
        return ["ema_period", "trend_ema_period"]

    def calculate(self, symbol, exchange, **kwargs):
        ema_period = int(kwargs.get("ema_period", 20))
        trend_ema_period = int(kwargs.get("trend_ema_period", 50))
        interval = kwargs.get("interval", DEFAULT_INTERVAL)
        df = _get_ohlcv_window(symbol, exchange, interval, min_bars=trend_ema_period + 2)
        if df is None:
            return 0.0

        ema = df["close"].ewm(span=ema_period, adjust=False).mean()
        trend_ema = df["close"].ewm(span=trend_ema_period, adjust=False).mean()
        if len(df) < 2:
            return 0.0

        last_close = float(df["close"].iloc[-1])
        last_ema = float(ema.iloc[-1])
        last_trend = float(trend_ema.iloc[-1])
        prev_low = float(df["low"].iloc[-2])

        is_uptrend = last_trend < last_ema
        touched_ema = prev_low <= last_ema
        return 1.0 if (is_uptrend and touched_ema and last_close > last_ema) else 0.0


# --- Options Indicators ---
# Unlike OI (a genuine field on a raw broker quote), IV and Delta are NOT
# broker-supplied -- no broker's get_quotes() response carries them (see
# services/option_greeks_service.py, the platform's real Black-76 Greeks
# engine used by IV Smile/GEX/etc). PCR isn't even a per-symbol concept --
# it's a whole-chain ratio (sum of put OI / sum of call OI across every
# strike of an underlying+expiry). These previously read a "quote['iv']" /
# "quote['delta']" / "quote['pcr']" field that nothing in the codebase
# ever populates, so they always logged a warning and returned 0.0
# regardless of live/headless context -- a dead path, not merely a
# WebSocket-cache gap like the other indicators had.


class IVIndicator(BaseIndicator):
    """Implied volatility for a single OPTION symbol (not the underlying)
    -- symbol must be a real dated option contract, e.g. "NIFTY28JUL2624000CE".
    Computed via services/option_greeks_service.py's Black-76 engine from
    live spot + option LTP, the same call IV Smile's backend makes per
    strike -- not a broker quote field."""

    def name(self):
        return "IV"

    def calculate(self, symbol, exchange, **kwargs):
        api_key = _indicator_api_key_var.get()
        if not api_key:
            logger.debug(f"No api_key in scope for IV({symbol}/{exchange}) -- returning 0.0")
            return 0.0
        try:
            from services.option_greeks_service import get_option_greeks

            success, response, _status = get_option_greeks(symbol, exchange, api_key=api_key)
            if success and isinstance(response, dict):
                return float(response.get("implied_volatility", 0.0))
        except Exception as e:
            logger.warning(f"Error computing IV for {symbol}/{exchange}: {e}")
        return 0.0


class DeltaIndicator(BaseIndicator):
    """Option delta for a single OPTION symbol. Same Black-76 engine as
    IVIndicator (one calculate_greeks call computes both together) -- see
    that class's docstring."""

    def name(self):
        return "Delta"

    def calculate(self, symbol, exchange, **kwargs):
        api_key = _indicator_api_key_var.get()
        if not api_key:
            logger.debug(f"No api_key in scope for Delta({symbol}/{exchange}) -- returning 0.0")
            return 0.0
        try:
            from services.option_greeks_service import get_option_greeks

            success, response, _status = get_option_greeks(symbol, exchange, api_key=api_key)
            if success and isinstance(response, dict):
                greeks = response.get("greeks", {})
                if isinstance(greeks, dict) and "delta" in greeks:
                    return float(greeks["delta"])
        except Exception as e:
            logger.warning(f"Error computing Delta for {symbol}/{exchange}: {e}")
        return 0.0


class PCRIndicator(BaseIndicator):
    """Put-Call Ratio (OI-based) for an underlying's full option chain at a
    given expiry -- NOT a per-symbol value. `symbol` here is the
    UNDERLYING (e.g. "NIFTY"), not a dated contract. Reuses
    services/oi_tracker_service.py::get_oi_data, the same full-chain
    OI-sum/ratio computation the OI Tracker page's backend uses.

    kwargs:
        expiry_type: "current_week" (default) | "next_week" |
            "current_month" | "next_month" -- resolved to a real expiry
            via services/expiry_service.py::resolve_expiry_type, same
            relative-expiry vocabulary the Strategy Builder/deployment
            config already uses elsewhere.
    """

    def name(self):
        return "PCR"

    def inputs(self):
        return ["expiry_type"]

    def calculate(self, symbol, exchange, **kwargs):
        api_key = _indicator_api_key_var.get()
        if not api_key:
            logger.debug(f"No api_key in scope for PCR({symbol}/{exchange}) -- returning 0.0")
            return 0.0
        try:
            from services.expiry_service import resolve_expiry_type
            from services.oi_tracker_service import get_oi_data

            expiry_type = kwargs.get("expiry_type", "current_week")
            options_exchange = exchange.upper()
            if options_exchange in ("NSE_INDEX", "NSE"):
                options_exchange = "NFO"
            elif options_exchange in ("BSE_INDEX", "BSE"):
                options_exchange = "BFO"

            expiry_date = resolve_expiry_type(symbol, options_exchange, expiry_type, api_key)
            if not expiry_date:
                logger.warning(f"Could not resolve expiry for PCR({symbol}/{exchange})")
                return 0.0

            success, response, _status = get_oi_data(symbol, options_exchange, expiry_date, api_key)
            if success and isinstance(response, dict):
                return float(response.get("pcr_oi", 0.0))
        except Exception as e:
            logger.warning(f"Error computing PCR for {symbol}/{exchange}: {e}")
        return 0.0


class OIIndicator(BaseIndicator):
    def name(self):
        return "OI"

    def calculate(self, symbol, exchange, **kwargs):
        from services.market_data_service import get_quote

        # Try the WebSocket-populated cache first (free, no extra broker
        # call, correct for anything running behind a live frontend
        # session). Fall back to a stateless REST quote fetch when it's
        # empty -- same reason/pattern as get_ltp_value's api_key fallback:
        # a headless caller (e.g. services/deployment_service.py's
        # evaluation loop) never populates this cache since it has no
        # WebSocket client of its own. OI is a genuine field on the raw
        # broker quote (see e.g. broker/zebu/api/data.py's get_quotes),
        # unlike IV/Delta/PCR which need real option-chain computation --
        # see IVIndicator/DeltaIndicator/PCRIndicator below for those.
        quote = get_quote(symbol, exchange)
        if quote and "oi" in quote:
            return float(quote["oi"])

        api_key = _indicator_api_key_var.get()
        if api_key:
            from services.quotes_service import get_quotes

            success, response, _status = get_quotes(symbol, exchange, api_key=api_key)
            if success:
                data = response.get("data", {})
                if isinstance(data, dict) and "oi" in data:
                    return float(data["oi"])

        logger.warning(f"No OI in quote for {symbol}/{exchange}; returning 0.0")
        return 0.0


# --- Registry ---


class IndicatorRegistry:
    """Registry to load, store, and look up indicator plugins"""

    _registry = {}

    @classmethod
    def register(cls, name: str, indicator_class):
        cls._registry[name.upper()] = indicator_class()
        logger.info(f"Registered indicator plugin: {name}")

    @classmethod
    def register_instance(cls, name: str, indicator_instance: BaseIndicator):
        """Register an already-constructed indicator instance, for
        indicators that need constructor arguments (e.g. OpeningRangeIndicator's
        side="high"/"low") and so can't use register()'s no-arg
        indicator_class() instantiation."""
        cls._registry[name.upper()] = indicator_instance
        logger.info(f"Registered indicator plugin: {name}")

    @classmethod
    def get(cls, name: str) -> BaseIndicator:
        return cls._registry.get(name.upper())

    @classmethod
    def list_indicators(cls) -> list[str]:
        return list(cls._registry.keys())


# Register all built-in indicator plugins
IndicatorRegistry.register("EMA", EMAIndicator)
IndicatorRegistry.register("SMA", SMAIndicator)
IndicatorRegistry.register("VWAP", VWAPIndicator)
IndicatorRegistry.register("RSI", RSIIndicator)
IndicatorRegistry.register("MACD", MACDIndicator)
IndicatorRegistry.register("ATR", ATRIndicator)
IndicatorRegistry.register("IV", IVIndicator)
IndicatorRegistry.register("DELTA", DeltaIndicator)
IndicatorRegistry.register("PCR", PCRIndicator)
IndicatorRegistry.register("OI", OIIndicator)
IndicatorRegistry.register_instance("ORB_HIGH", OpeningRangeIndicator("high"))
IndicatorRegistry.register_instance("ORB_LOW", OpeningRangeIndicator("low"))
IndicatorRegistry.register_instance("EMA_CROSS_UP", EMACrossIndicator("up"))
IndicatorRegistry.register_instance("EMA_CROSS_DOWN", EMACrossIndicator("down"))
IndicatorRegistry.register_instance("SMA_CROSS_UP", SMACrossIndicator("up"))
IndicatorRegistry.register_instance("SMA_CROSS_DOWN", SMACrossIndicator("down"))
IndicatorRegistry.register_instance("MACD_CROSS_UP", MACDCrossIndicator("up"))
IndicatorRegistry.register_instance("MACD_CROSS_DOWN", MACDCrossIndicator("down"))
IndicatorRegistry.register_instance("RSI_CROSS_UP_THRU", RSIThresholdCrossIndicator("up_thru"))
IndicatorRegistry.register_instance("RSI_CROSS_DOWN_THRU", RSIThresholdCrossIndicator("down_thru"))
IndicatorRegistry.register("ROC", ROCIndicator)
IndicatorRegistry.register_instance("SWING_HIGH", SwingLevelIndicator("high"))
IndicatorRegistry.register_instance("SWING_LOW", SwingLevelIndicator("low"))
IndicatorRegistry.register_instance("PREV_DAY_HIGH", PrevDayLevelIndicator("high"))
IndicatorRegistry.register_instance("PREV_DAY_LOW", PrevDayLevelIndicator("low"))
IndicatorRegistry.register_instance("PREV_DAY_CLOSE", PrevDayLevelIndicator("close"))
IndicatorRegistry.register_instance("TRIPLE_EMA_UP", TripleEMAStackIndicator("up"))
IndicatorRegistry.register_instance("TRIPLE_EMA_DOWN", TripleEMAStackIndicator("down"))
IndicatorRegistry.register_instance("SUPERTREND_FLIP_UP", SupertrendFlipIndicator("up"))
IndicatorRegistry.register_instance("SUPERTREND_FLIP_DOWN", SupertrendFlipIndicator("down"))
IndicatorRegistry.register_instance("ADX_TREND_UP", ADXTrendIndicator("up"))
IndicatorRegistry.register_instance("ADX_TREND_DOWN", ADXTrendIndicator("down"))
IndicatorRegistry.register("VOLUME_SURGE", VolumeSurgeIndicator)
IndicatorRegistry.register_instance("BB_UPPER", BollingerBandIndicator("upper"))
IndicatorRegistry.register_instance("BB_LOWER", BollingerBandIndicator("lower"))
IndicatorRegistry.register_instance("BB_SQUEEZE_BREAKOUT_UP", BollingerSqueezeIndicator("up"))
IndicatorRegistry.register_instance("BB_SQUEEZE_BREAKOUT_DOWN", BollingerSqueezeIndicator("down"))
IndicatorRegistry.register_instance("KELTNER_UPPER", KeltnerChannelIndicator("upper"))
IndicatorRegistry.register_instance("KELTNER_LOWER", KeltnerChannelIndicator("lower"))
IndicatorRegistry.register_instance("DONCHIAN_MID_CROSS_UP", DonchianMidCrossIndicator("up"))
IndicatorRegistry.register_instance("DONCHIAN_MID_CROSS_DOWN", DonchianMidCrossIndicator("down"))
IndicatorRegistry.register_instance("ATR_TRAIL_CROSS_UP", ATRTrailCrossIndicator("up"))
IndicatorRegistry.register_instance("ATR_TRAIL_CROSS_DOWN", ATRTrailCrossIndicator("down"))
IndicatorRegistry.register("GAP_PCT", GapPercentIndicator)
IndicatorRegistry.register_instance("INSIDE_CANDLE_BREAKOUT_UP", InsideCandleBreakoutIndicator("up"))
IndicatorRegistry.register_instance("INSIDE_CANDLE_BREAKOUT_DOWN", InsideCandleBreakoutIndicator("down"))
IndicatorRegistry.register_instance("NR7_BREAKOUT_UP", NR7BreakoutIndicator("up"))
IndicatorRegistry.register_instance("NR7_BREAKOUT_DOWN", NR7BreakoutIndicator("down"))
IndicatorRegistry.register_instance("VWAP_DEVIATION_BELOW", VWAPDeviationIndicator("below"))
IndicatorRegistry.register_instance("VWAP_DEVIATION_ABOVE", VWAPDeviationIndicator("above"))
IndicatorRegistry.register_instance("VWAP_CROSS_UP", VWAPScalpCrossIndicator("up"))
IndicatorRegistry.register_instance("VWAP_CROSS_DOWN", VWAPScalpCrossIndicator("down"))
IndicatorRegistry.register("EMA_PULLBACK_BOUNCE", EMAPullbackIndicator)
