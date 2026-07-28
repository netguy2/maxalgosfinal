# services/indicator_series_service.py
"""
Indicator time-series computation for chart overlays.

services/indicator_registry.py already has correct, live-vetted formulas
for EMA/SMA/VWAP/RSI/MACD/ATR (used by Flow's Indicator Check node), but
each plugin's calculate() only returns the latest scalar value (.iloc[-1])
for condition-checking. Charts need the whole computed series to draw an
overlay line. This module reuses the exact same pandas expressions and
returns every bar instead of just the last one.

Every compute function takes a pandas DataFrame directly (columns:
timestamp, open, high, low, close, volume) rather than fetching it itself
-- this keeps the math decoupled from where the bars came from. The Charts
page (pages/Charts.tsx) fetches bars live from the broker on demand (any
symbol works immediately, no pre-download step) and sends them straight to
these functions; nothing here depends on Historify's stored DB.
"""

import numpy as np
import pandas as pd

from utils.logging import get_logger

logger = get_logger(__name__)

SeriesPoint = dict  # {"time": int, "value": float}


def _series_to_points(timestamps: pd.Series, values: pd.Series) -> list[SeriesPoint]:
    """Pairs timestamps with values, dropping any row where the value is
    NaN (e.g. the warm-up bars before a rolling/ewm window is full) so the
    frontend never has to special-case NaN in chart data."""
    points = []
    for ts, val in zip(timestamps, values, strict=True):
        if pd.isna(val):
            continue
        points.append({"time": int(ts), "value": float(val)})
    return points


def compute_ema(df: pd.DataFrame, period: int = 20) -> list[SeriesPoint]:
    """Same formula as EMAIndicator.calculate() in indicator_registry.py:
    closes.ewm(span=period, adjust=False).mean() — returned as a full
    series instead of just the last value."""
    if df is None or df.empty or len(df) < period:
        return []
    ema = df["close"].ewm(span=period, adjust=False).mean()
    return _series_to_points(df["timestamp"], ema)


def compute_sma(df: pd.DataFrame, period: int = 20) -> list[SeriesPoint]:
    """Same formula as SMAIndicator.calculate(): a rolling mean."""
    if df is None or df.empty or len(df) < period:
        return []
    sma = df["close"].rolling(window=period).mean()
    return _series_to_points(df["timestamp"], sma)


def compute_vwap(df: pd.DataFrame) -> list[SeriesPoint]:
    """Same formula as VWAPIndicator.calculate(): cumulative volume-weighted
    typical price. Computed over whatever bars are given — callers wanting
    a same-session-only VWAP should pass only today's bars."""
    if df is None or df.empty or df["volume"].sum() <= 0:
        return []

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_pv = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum().replace(0, pd.NA)
    vwap = cum_pv / cum_vol
    return _series_to_points(df["timestamp"], vwap)


def compute_rsi(df: pd.DataFrame, period: int = 14) -> list[SeriesPoint]:
    """Same formula as RSIIndicator.calculate(): Wilder's smoothing
    (EMA with alpha = 1/period) over gains/losses."""
    if df is None or df.empty or len(df) < period + 1:
        return []

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + rs))
    # Where avg_loss is exactly 0 (all gains, no losses in the window),
    # RSI is defined as 100 rather than the NaN that avg_loss.replace(0, NA)
    # would otherwise produce.
    rsi = rsi.where(avg_loss != 0, 100.0)
    return _series_to_points(df["timestamp"], rsi)


def compute_macd(
    df: pd.DataFrame,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> dict[str, list[SeriesPoint]]:
    """Same MACD-line formula as MACDIndicator.calculate() (fast EMA - slow
    EMA), plus the signal line and histogram — the scalar-only registry
    plugin never computed these since Flow's Indicator Check only ever
    compared the raw MACD line against a threshold, but a chart needs all
    three for a standard MACD panel."""
    if df is None or df.empty or len(df) < slow_period:
        return {"macd": [], "signal": [], "histogram": []}

    ema_fast = df["close"].ewm(span=fast_period, adjust=False).mean()
    ema_slow = df["close"].ewm(span=slow_period, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line

    return {
        "macd": _series_to_points(df["timestamp"], macd_line),
        "signal": _series_to_points(df["timestamp"], signal_line),
        "histogram": _series_to_points(df["timestamp"], histogram),
    }


def compute_atr(df: pd.DataFrame, period: int = 14) -> list[SeriesPoint]:
    """Same formula as ATRIndicator.calculate(): true range smoothed with
    Wilder's EMA (alpha = 1/period)."""
    if df is None or df.empty or len(df) < period + 1:
        return []

    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    true_range = (
        (high - low)
        .to_frame("hl")
        .assign(hc=(high - prev_close).abs(), lc=(low - prev_close).abs())
        .max(axis=1)
    )
    atr = true_range.ewm(alpha=1 / period, adjust=False).mean()
    return _series_to_points(df["timestamp"], atr)


def compute_bollinger(
    df: pd.DataFrame, period: int = 20, mult: float = 2.0
) -> dict[str, list[SeriesPoint]]:
    """Standard Bollinger Bands: a rolling SMA basis line with upper/lower
    bands at basis +/- mult standard deviations. Not in indicator_registry.py
    yet — this is new math, following the textbook definition (not derived
    from an existing plugin like the others above)."""
    if df is None or df.empty or len(df) < period:
        return {"basis": [], "upper": [], "lower": []}

    basis = df["close"].rolling(window=period).mean()
    std = df["close"].rolling(window=period).std()
    upper = basis + mult * std
    lower = basis - mult * std

    return {
        "basis": _series_to_points(df["timestamp"], basis),
        "upper": _series_to_points(df["timestamp"], upper),
        "lower": _series_to_points(df["timestamp"], lower),
    }


def compute_stochastic(
    df: pd.DataFrame, k_period: int = 14, k_smooth: int = 3, d_period: int = 3
) -> dict[str, list[SeriesPoint]]:
    """Standard Stochastic Oscillator (%K/%D), textbook definition, not in
    indicator_registry.py yet — new math, following the same flat-range
    guard style as compute_rsi's avg_loss.replace(0, pd.NA) above."""
    min_len = k_period + k_smooth + d_period
    if df is None or df.empty or len(df) < min_len:
        return {"k": [], "d": []}

    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()
    price_range = (high_max - low_min).replace(0, np.nan)
    fast_k = 100 * (df["close"] - low_min) / price_range
    k = fast_k.rolling(window=k_smooth).mean()
    d = k.rolling(window=d_period).mean()

    return {
        "k": _series_to_points(df["timestamp"], k),
        "d": _series_to_points(df["timestamp"], d),
    }


_COMBINE_OPS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b if b != 0 else None,
}


def combine_series(
    op: str, series_a: list[SeriesPoint], series_b: list[SeriesPoint]
) -> list[SeriesPoint]:
    """Arithmetically combines two time-aligned series (e.g. EMA(20) minus
    SMA(50), for a custom indicator overlay). `op` must be one of
    "+", "-", "*", "/" -- always a caller-supplied, hardcoded whitelist
    value (see services/custom_indicator_service.py), never arbitrary
    user-supplied code, so this stays a fixed, safe set of operations.
    Uses the same time-alignment approach as detect_crossover_signals:
    only timestamps present in both series produce a point; a "/" by zero
    is dropped rather than raising or emitting inf/NaN."""
    if not series_a or not series_b:
        return []
    fn = _COMBINE_OPS.get(op)
    if fn is None:
        raise ValueError(f"Unsupported combine op: {op!r}")

    b_by_time = {p["time"]: p["value"] for p in series_b}
    result = []
    for point in series_a:
        t = point["time"]
        if t not in b_by_time:
            continue
        val = fn(point["value"], b_by_time[t])
        if val is not None:
            result.append({"time": t, "value": float(val)})
    return result


def detect_crossover_signals(
    series_a: list[SeriesPoint], series_b: list[SeriesPoint]
) -> list[dict]:
    """Generic crossover detector: given two time-aligned series (e.g. a
    fast line and a slow line, or a value line and a fixed threshold line),
    returns a BUY marker wherever series_a crosses from below to above
    series_b, and a SELL marker wherever it crosses from above to below.
    Both inputs must already share the same `time` values in the same
    order (callers are responsible for aligning them, e.g. by only
    comparing bars present in both series)."""
    if not series_a or not series_b:
        return []

    b_by_time = {p["time"]: p["value"] for p in series_b}
    signals = []
    prev_diff = None
    for point in series_a:
        t = point["time"]
        if t not in b_by_time:
            continue
        diff = point["value"] - b_by_time[t]
        if prev_diff is not None:
            if prev_diff <= 0 < diff:
                signals.append({"time": t, "side": "BUY"})
            elif prev_diff >= 0 > diff:
                signals.append({"time": t, "side": "SELL"})
        prev_diff = diff
    return signals


def detect_threshold_crossover_signals(
    series: list[SeriesPoint], threshold: float, invert: bool = False
) -> list[dict]:
    """Crossover detector against a fixed threshold rather than a second
    series (e.g. RSI crossing 30/70). By default a cross from below to
    above the threshold is a BUY (e.g. RSI recovering above 30); pass
    invert=True for the opposite convention (e.g. RSI dropping below 70
    is the SELL side, not a BUY on the way up through 70)."""
    if not series:
        return []

    signals = []
    prev_val = None
    for point in series:
        val = point["value"]
        if prev_val is not None:
            crossed_up = prev_val <= threshold < val
            crossed_down = prev_val >= threshold > val
            if crossed_up:
                signals.append({"time": point["time"], "side": "SELL" if invert else "BUY"})
            elif crossed_down:
                signals.append({"time": point["time"], "side": "BUY" if invert else "SELL"})
        prev_val = val
    return signals


def _find_swing_points(series: pd.Series, left: int, right: int, kind: str) -> list[int]:
    """Fractal-style swing high/low detector: returns the integer
    positions (not timestamps) where `series` is strictly the max ('high')
    or min ('low') within a window of `left` bars before and `right` bars
    after. This is the standard definition of a swing point used by most
    charting platforms -- a real local extreme confirmed by price action
    on both sides, not just any bar-to-bar wiggle."""
    n = len(series)
    values = series.to_numpy()
    points = []
    for i in range(left, n - right):
        window = values[i - left : i + right + 1]
        center = values[i]
        if kind == "high" and center == window.max() and (window == center).sum() == 1:
            points.append(i)
        elif kind == "low" and center == window.min() and (window == center).sum() == 1:
            points.append(i)
    return points


def compute_support_resistance(
    df: pd.DataFrame,
    swing_window: int = 5,
    cluster_tolerance_pct: float = 0.3,
    max_levels: int = 6,
) -> dict[str, list[dict]]:
    """
    Detects support/resistance levels from real swing highs/lows in the
    given OHLCV bars, not a fixed formula -- these are levels price has
    actually reversed at, ranked by how often price touched near them.

    Algorithm:
      1. Find swing highs (local maxima in `high`) and swing lows (local
         minima in `low`) using a `swing_window`-bar fractal window on
         each side.
      2. Cluster swing prices that are within `cluster_tolerance_pct`% of
         each other into a single level (price rarely reverses at the
         exact same tick twice; nearby touches represent the same zone).
      3. Rank clusters by touch count (more touches = stronger level) and
         keep the top `max_levels` per side.
      4. Classify each level as resistance if it sits above the most
         recent close, support if below -- a level's role can flip once
         price crosses it, which is standard technical-analysis behavior,
         not a bug in the classification.

    Returns:
        {"resistance": [{"price": float, "touches": int}, ...],
         "support": [{"price": float, "touches": int}, ...]}
        both sorted strongest (most touches) first.
    """
    if df is None or df.empty or len(df) < swing_window * 2 + 1:
        return {"resistance": [], "support": []}

    swing_high_idx = _find_swing_points(df["high"], swing_window, swing_window, "high")
    swing_low_idx = _find_swing_points(df["low"], swing_window, swing_window, "low")

    swing_high_prices = [float(df["high"].iloc[i]) for i in swing_high_idx]
    swing_low_prices = [float(df["low"].iloc[i]) for i in swing_low_idx]

    def cluster(prices: list[float]) -> list[dict]:
        """Greedy clustering: sort ascending, group consecutive prices
        within cluster_tolerance_pct of the cluster's running average."""
        if not prices:
            return []
        prices_sorted = sorted(prices)
        clusters: list[list[float]] = [[prices_sorted[0]]]
        for p in prices_sorted[1:]:
            cluster_avg = sum(clusters[-1]) / len(clusters[-1])
            if abs(p - cluster_avg) / cluster_avg * 100 <= cluster_tolerance_pct:
                clusters[-1].append(p)
            else:
                clusters.append([p])
        return [{"price": sum(c) / len(c), "touches": len(c)} for c in clusters]

    last_close = float(df["close"].iloc[-1])
    all_levels = cluster(swing_high_prices) + cluster(swing_low_prices)
    # Merge across the high/low clustering pass too -- a level touched by
    # both a swing high and a swing low nearby (common at a real
    # support/resistance flip zone) should count as one stronger level,
    # not two separate weak ones.
    merged = cluster([lvl["price"] for lvl in all_levels for _ in range(lvl["touches"])])

    resistance = sorted(
        (lvl for lvl in merged if lvl["price"] > last_close),
        key=lambda lvl: lvl["touches"],
        reverse=True,
    )[:max_levels]
    support = sorted(
        (lvl for lvl in merged if lvl["price"] <= last_close),
        key=lambda lvl: lvl["touches"],
        reverse=True,
    )[:max_levels]

    return {
        "resistance": sorted(resistance, key=lambda lvl: lvl["price"]),
        "support": sorted(support, key=lambda lvl: lvl["price"], reverse=True),
    }


def compute_support_resistance_from_bars(bars: list[dict]) -> dict[str, list[dict]]:
    """Same as compute_support_resistance, but takes raw bar dicts (as
    received from a request body) and handles the DataFrame conversion --
    the counterpart to how custom_indicator_service.py's
    compute_custom_indicator builds its DataFrame from caller-supplied bars."""
    df = pd.DataFrame(bars)
    if df.empty:
        return {"resistance": [], "support": []}
    df = df.sort_values("timestamp").reset_index(drop=True)
    return compute_support_resistance(df)
