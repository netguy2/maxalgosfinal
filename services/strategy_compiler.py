"""
Strategy Compiler — translates a wizard blueprint's raw strategy_config
(the field values from frontend/src/lib/strategy-schemas.ts's STRATEGY_SCHEMAS)
into a real conditions_tree that services/condition_engine.py can evaluate.

Why this exists: the Strategy Builder wizard (StrategyConfigurator.tsx) lets
a user configure rules (e.g. "Opening Range Breakout, 15 min, both
directions"), but previously never compiled those choices into anything the
background execution engine (services/deployment_service.py's
_evaluation_loop) could actually evaluate -- deployments sat at status
"Waiting" forever, looking healthy, doing nothing. This module is the
missing translation layer.

Trust boundary: this compiler runs SERVER-SIDE only, invoked from
blueprints/deployments.py's create_new_deployment. A client can influence
inputs (periods, thresholds, symbol) but can never hand-author the
executable conditions_tree directly -- blueprints/deployments.py must never
accept a client-supplied conditions_tree for wizard-originated deployments.

Scalability: STRATEGY_TYPE_REGISTRY mirrors strategy-schemas.ts's
STRATEGY_SCHEMAS registry 1:1. Adding a new blueprint later means adding one
compile_* function here and one registry entry -- nothing else in the
execution pipeline (deployment_service.py, condition_engine.py,
risk_engine.py, blueprints/deployments.py's route logic) needs to change.
"""

import logging

logger = logging.getLogger(__name__)


class CompilerError(ValueError):
    """Raised when strategy_config can't compile into a valid conditions_tree.
    Callers (blueprints/deployments.py) must treat this as a 400 and refuse
    to create the deployment -- never fall back to persisting an empty or
    partial conditions_tree, which would silently never trigger (see the
    `if tree and ...` guard in deployment_service.py's _evaluation_loop)."""


# StrategyConfigurator.tsx sends the raw marketplace CATALOG item `id`
# (e.g. "sma-golden", "rsi-rev") as template_id -- NOT the catalog item's
# signalId. Catalog ids bear no naming relationship to their strategy type
# (see frontend/src/lib/marketplace-catalog.ts's own doc comment on this),
# so an exact-match override table is required; substring matching alone
# produces silently wrong results (e.g. "ema-9-21" substring-matching to
# "orb" is wrong, and "rsi-rev" substring-matching "rsi" would wrongly
# resolve to rsi_momentum instead of rsi_reversal). Verified against the
# real catalog file's id -> signalId mappings.
CATALOG_ID_TO_SCHEMA_KEY: dict[str, str] = {
    # Round 1
    "orb-5": "orb",
    "orb-15": "orb",
    "ema-9-21": "ema_cross",
    "ema-20-50": "ema_cross",
    "ema-cross": "ema_cross",
    "ema-scalp": "ema_cross",
    "mtf-ema": "ema_cross",
    "sma-golden": "sma_cross",
    "rsi-mom": "rsi_momentum",
    "rsi-rev": "rsi_reversal",
    "macd-mom": "macd_momentum",
    "macd-vol": "macd_momentum",
    "roc": "roc_momentum",
    "mom-scalp": "roc_momentum",
    "pa-mom": "swing_breakout",
    "swing-high": "swing_breakout",
    "swing-low": "swing_breakout",
    "cpr-breakout": "prev_day_breakout",
    "prev-high": "prev_day_breakout",
    "prev-low": "prev_day_breakout",
    # Round 2
    "triple-ema": "triple_ema",
    "supertrend-trend": "supertrend",
    "st-scalp": "supertrend",
    "st-rsi": "supertrend",
    "adx-trend": "adx_trend",
    "ema-adx": "adx_trend",
    "vol-breakout": "volume_breakout",
    "mom-vol": "volume_breakout",
    "inside-candle": "inside_candle_breakout",
    "nr7": "nr7_breakout",
    "bb-rev": "bollinger_reversal",
    "range-scalp": "bollinger_reversal",
    "ema-vwap": "vwap_reversion",
    "vwap-rev": "vwap_reversion",
    "vwap-cpr": "vwap_reversion",
    "keltner-rev": "keltner_reversion",
    "donchian-pull": "donchian_pullback",
    "trendline-bounce": "donchian_pullback",
    "sr-bounce": "donchian_pullback",
    "ema-pull": "ema_pullback",
    "vwap-scalp": "vwap_scalp",
    "atr-trend": "atr_trend",
    "bb-squeeze": "bollinger_squeeze",
    "vol-expansion": "bollinger_squeeze",
    "opening-gap": "gap_strategy",
    "eq-weight": "basket_strategy",
    "top-vol": "basket_strategy",
    "top-gainers": "basket_strategy",
    "sector-basket": "basket_strategy",
}


def _resolve_schema_key(template_id: str | None) -> str:
    """Resolve a marketplace catalog `id` (as sent by
    StrategyConfigurator.tsx's template_id field) to a compiler registry
    key. Exact-match override table first (CATALOG_ID_TO_SCHEMA_KEY);
    substring matching is kept only as a legacy fallback for direct/manual
    URL access with an id not yet in the table."""
    if not template_id:
        return "orb"

    tid = template_id.lower()
    if tid in CATALOG_ID_TO_SCHEMA_KEY:
        return CATALOG_ID_TO_SCHEMA_KEY[tid]

    if "orb" in tid:
        return "orb"
    if "ema" in tid and "cross" in tid:
        return "ema_cross"
    if "supertrend" in tid:
        return "supertrend"
    if "rsi" in tid:
        return "rsi_momentum"
    if any(k in tid for k in ("condor", "straddle", "option", "spread")):
        return "options_strategy"

    return "orb"


def _leaf(indicator: str, condition: str, value=None, value_indicator: str = None,
          value_indicator_params: dict = None, **extra) -> dict:
    """Build one comparison leaf. Every leaf produced by this module carries
    both `indicator` and `condition` -- the two keys condition_engine.py's
    leaf handler requires to not silently auto-pass (see
    _assert_no_malformed_leaves below, which enforces this as a hard
    contract before any tree is persisted)."""
    node = {"indicator": indicator, "condition": condition, **extra}
    if value_indicator is not None:
        node["value_indicator"] = value_indicator
        if value_indicator_params:
            node["value_indicator_params"] = value_indicator_params
    else:
        node["value"] = value
    return node


def _group(operator: str, children: list) -> dict:
    return {"operator": operator, "children": children}


# ---------------------------------------------------------------------------
# Per-blueprint compilers
# ---------------------------------------------------------------------------


def compile_orb(config: dict) -> dict:
    """Opening Range Breakout. See frontend/src/lib/strategy-schemas.ts's
    `orb` schema (fields: orbDuration, breakoutDirection, confirmationMode,
    gapFilter, volumeFilter, allowReentry).

    Uses the ORB_HIGH/ORB_LOW indicators (services/indicator_registry.py)
    compared against live SPOT via the leaf's value_indicator mechanism.

    Known gap: volumeFilter and confirmationMode ("instant" vs
    "candle_close") have no backing indicator/semantics in the engine today
    -- they're accepted from the wizard but NOT enforced by the compiled
    tree. Logged so this is visible, not a silent no-op.
    """
    duration = int(config.get("orbDuration", 15) or 15)
    direction = config.get("breakoutDirection", "both")

    if config.get("volumeFilter"):
        logger.warning(
            "compile_orb: volumeFilter requested but no volume-spike indicator "
            "exists yet -- this filter is NOT enforced in the compiled tree."
        )

    params = {"duration": duration}
    high_breakout = _leaf("SPOT", ">", value_indicator="ORB_HIGH", value_indicator_params=params)
    low_breakout = _leaf("SPOT", "<", value_indicator="ORB_LOW", value_indicator_params=params)

    if direction == "high_only":
        tree = high_breakout
    elif direction == "low_only":
        tree = low_breakout
    else:
        tree = _group("OR", [high_breakout, low_breakout])

    if config.get("gapFilter"):
        # Gap filter needs yesterday's close vs today's open -- no such
        # indicator exists yet either. Same treatment as volumeFilter:
        # accepted, not silently claimed as enforced.
        logger.warning(
            "compile_orb: gapFilter requested but no gap-vs-prev-close "
            "indicator exists yet -- this filter is NOT enforced in the "
            "compiled tree."
        )

    return tree


def compile_ema_cross(config: dict) -> dict:
    """EMA crossover. See strategy-schemas.ts's `ema_cross` schema
    (fastEma, slowEma, priceSource, trendFilter, exitOnReverse).

    Uses EMA_CROSS_UP/DOWN (services/indicator_registry.py) rather than
    comparing current EMA levels -- a level check ("fast > slow") would
    fire continuously on every 5-second evaluation tick for the entire
    time the EMAs stay crossed, not just the bar where the cross actually
    happened. EMA_CROSS_UP/DOWN detects the transition itself (prev bar
    not-crossed, current bar crossed), computed fresh each call from
    OHLCV history -- no stored cross-tick state.
    """
    fast = int(config.get("fastEma", 9) or 9)
    slow = int(config.get("slowEma", 21) or 21)
    if fast >= slow:
        raise CompilerError(
            f"ema_cross: fastEma ({fast}) must be less than slowEma ({slow})"
        )

    params = {"fast_period": fast, "slow_period": slow}
    cross_up = _leaf("EMA_CROSS_UP", ">", value=0.5, **params)
    if config.get("exitOnReverse", True):
        cross_down = _leaf("EMA_CROSS_DOWN", ">", value=0.5, **params)
        return _group("OR", [cross_up, cross_down])
    return cross_up


def compile_rsi_momentum(config: dict) -> dict:
    """RSI momentum. See strategy-schemas.ts's `rsi_momentum` schema
    (rsiLength, buyAbove, sellBelow, useVwapFilter). Uses the
    already-registered RSI indicator -- no new indicator needed.
    """
    length = int(config.get("rsiLength", 14) or 14)
    buy_above = float(config.get("buyAbove", 60) or 60)
    sell_below = float(config.get("sellBelow", 40) or 40)
    if buy_above <= sell_below:
        raise CompilerError(
            f"rsi_momentum: buyAbove ({buy_above}) must be greater than "
            f"sellBelow ({sell_below})"
        )

    buy_leaf = _leaf("RSI", ">", value=buy_above, period=length)
    sell_leaf = _leaf("RSI", "<", value=sell_below, period=length)
    return _group("OR", [buy_leaf, sell_leaf])


def compile_sma_cross(config: dict) -> dict:
    """SMA golden/death crossover. Same shape as compile_ema_cross but on
    daily bars by default (SMA_CROSS_UP/DOWN indicators default to
    interval="D"), matching the classic 50/200-day golden cross use case.
    """
    fast = int(config.get("fastSma", config.get("fastEma", 50)) or 50)
    slow = int(config.get("slowSma", config.get("slowEma", 200)) or 200)
    if fast >= slow:
        raise CompilerError(
            f"sma_cross: fastSma ({fast}) must be less than slowSma ({slow})"
        )

    params = {"fast_period": fast, "slow_period": slow}
    cross_up = _leaf("SMA_CROSS_UP", ">", value=0.5, **params)
    if config.get("exitOnReverse", True):
        cross_down = _leaf("SMA_CROSS_DOWN", ">", value=0.5, **params)
        return _group("OR", [cross_up, cross_down])
    return cross_up


def compile_macd_momentum(config: dict) -> dict:
    """MACD line crossing its signal line. See strategy-schemas.ts's
    `macd_momentum` schema (fastPeriod, slowPeriod, signalPeriod).
    Uses MACD_CROSS_UP/DOWN -- a real transition, same reasoning as
    compile_ema_cross.
    """
    fast = int(config.get("fastPeriod", 12) or 12)
    slow = int(config.get("slowPeriod", 26) or 26)
    signal = int(config.get("signalPeriod", 9) or 9)
    if fast >= slow:
        raise CompilerError(
            f"macd_momentum: fastPeriod ({fast}) must be less than slowPeriod ({slow})"
        )

    params = {"fast_period": fast, "slow_period": slow, "signal_period": signal}
    cross_up = _leaf("MACD_CROSS_UP", ">", value=0.5, **params)
    cross_down = _leaf("MACD_CROSS_DOWN", ">", value=0.5, **params)
    return _group("OR", [cross_up, cross_down])


def compile_rsi_reversal(config: dict) -> dict:
    """RSI reversal (oversold bounce / overbought rejection). See
    strategy-schemas.ts's `rsi_reversal` schema (rsiLength,
    oversoldLevel, overboughtLevel). Uses RSI_CROSS_UP_THRU/DOWN_THRU --
    the moment RSI crosses back through the threshold, not merely being
    beyond it (which is compile_rsi_momentum's, a different strategy,
    shape).
    """
    length = int(config.get("rsiLength", 14) or 14)
    oversold = float(config.get("oversoldLevel", 30) or 30)
    overbought = float(config.get("overboughtLevel", 70) or 70)
    if oversold >= overbought:
        raise CompilerError(
            f"rsi_reversal: oversoldLevel ({oversold}) must be less than "
            f"overboughtLevel ({overbought})"
        )

    bounce = _leaf("RSI_CROSS_UP_THRU", ">", value=0.5, period=length, threshold=oversold)
    rejection = _leaf("RSI_CROSS_DOWN_THRU", ">", value=0.5, period=length, threshold=overbought)
    return _group("OR", [bounce, rejection])


def compile_swing_breakout(config: dict) -> dict:
    """Price breaking above/below a recent swing high/low. See
    strategy-schemas.ts's `swing_breakout` schema (lookbackPeriod,
    breakoutDirection). Uses SWING_HIGH/LOW compared against live SPOT.
    """
    period = int(config.get("lookbackPeriod", 20) or 20)
    direction = config.get("breakoutDirection", "both")

    params = {"period": period}
    high_breakout = _leaf("SPOT", ">", value_indicator="SWING_HIGH", value_indicator_params=params)
    low_breakout = _leaf("SPOT", "<", value_indicator="SWING_LOW", value_indicator_params=params)

    if direction == "high_only":
        return high_breakout
    if direction == "low_only":
        return low_breakout
    return _group("OR", [high_breakout, low_breakout])


def compile_roc_momentum(config: dict) -> dict:
    """Rate-of-Change momentum. See strategy-schemas.ts's `roc_momentum`
    schema (rocPeriod, buyAbove, sellBelow). Uses the ROC indicator
    against static thresholds -- same shape as compile_rsi_momentum.
    """
    period = int(config.get("rocPeriod", 12) or 12)
    buy_above = float(config.get("buyAbove", 2) or 2)
    sell_below = float(config.get("sellBelow", -2) or -2)
    if buy_above <= sell_below:
        raise CompilerError(
            f"roc_momentum: buyAbove ({buy_above}) must be greater than "
            f"sellBelow ({sell_below})"
        )

    buy_leaf = _leaf("ROC", ">", value=buy_above, period=period)
    sell_leaf = _leaf("ROC", "<", value=sell_below, period=period)
    return _group("OR", [buy_leaf, sell_leaf])


def compile_prev_day_breakout(config: dict) -> dict:
    """Price breaking above/below the previous trading day's high/low.
    See strategy-schemas.ts's `prev_day_breakout` schema
    (breakoutDirection). Uses PREV_DAY_HIGH/LOW compared against live
    SPOT.
    """
    direction = config.get("breakoutDirection", "both")

    high_breakout = _leaf("SPOT", ">", value_indicator="PREV_DAY_HIGH")
    low_breakout = _leaf("SPOT", "<", value_indicator="PREV_DAY_LOW")

    if direction == "high_only":
        return high_breakout
    if direction == "low_only":
        return low_breakout
    return _group("OR", [high_breakout, low_breakout])


def compile_supertrend(config: dict) -> dict:
    """Supertrend. See strategy-schemas.ts's `supertrend` schema
    (atrPeriod, multiplier). Uses SUPERTREND_FLIP_UP/DOWN -- a real trend
    flip (transition), not a level check.
    """
    atr_period = int(config.get("atrPeriod", 10) or 10)
    multiplier = float(config.get("multiplier", 3.0) or 3.0)

    params = {"atr_period": atr_period, "atr_multiplier": multiplier}
    flip_up = _leaf("SUPERTREND_FLIP_UP", ">", value=0.5, **params)
    flip_down = _leaf("SUPERTREND_FLIP_DOWN", ">", value=0.5, **params)
    return _group("OR", [flip_up, flip_down])


def compile_triple_ema(config: dict) -> dict:
    """Triple EMA stack. See python-strategy-generator.ts's `triple-ema`
    signal (fastPeriod, midPeriod, slowPeriod). Uses TRIPLE_EMA_UP/DOWN.
    """
    fast = int(config.get("fastPeriod", 5) or 5)
    mid = int(config.get("midPeriod", 13) or 13)
    slow = int(config.get("slowPeriod", 34) or 34)
    if not (fast < mid < slow):
        raise CompilerError(
            f"triple_ema: periods must satisfy fast ({fast}) < mid ({mid}) < slow ({slow})"
        )

    params = {"fast_period": fast, "mid_period": mid, "slow_period": slow}
    return _leaf("TRIPLE_EMA_UP", ">", value=0.5, **params)


def compile_adx_trend(config: dict) -> dict:
    """ADX-filtered trend. See python-strategy-generator.ts's `adx-trend`
    signal (adxPeriod, adxThreshold). Uses ADX_TREND_UP -- requires ADX
    above threshold AND +DI > -DI, matching the reference implementation's
    "only trade when ADX confirms trend strength" semantics.
    """
    period = int(config.get("adxPeriod", 14) or 14)
    threshold = float(config.get("adxThreshold", 25) or 25)

    return _leaf("ADX_TREND_UP", ">", value=0.5, period=period, threshold=threshold)


def compile_volume_breakout(config: dict) -> dict:
    """Volume-confirmed breakout. See python-strategy-generator.ts's
    `volume-breakout` signal (volumeMultiplier). Uses VOLUME_SURGE
    combined (AND) with a rising-price confirmation via SPOT vs EMA,
    matching the reference's "surge + close above prior close" shape --
    approximated here as SPOT above a short EMA (a proxy for "price
    rising"), since a single-leaf prior-close comparison isn't directly
    expressible as a value_indicator without extra state.
    """
    period = int(config.get("volumeLookback", 20) or 20)
    multiplier = float(config.get("volumeMultiplier", 2.0) or 2.0)

    surge = _leaf("VOLUME_SURGE", ">", value=0.5, period=period, multiplier=multiplier)
    rising = _leaf("SPOT", ">", value_indicator="EMA", value_indicator_params={"period": 5})
    return _group("AND", [surge, rising])


def compile_inside_candle_breakout(config: dict) -> dict:
    """Inside-candle (mother/inside bar) breakout. See
    python-strategy-generator.ts's `inside-candle-breakout` signal (no
    configurable params). Uses INSIDE_CANDLE_BREAKOUT_UP/DOWN.
    """
    up = _leaf("INSIDE_CANDLE_BREAKOUT_UP", ">", value=0.5)
    down = _leaf("INSIDE_CANDLE_BREAKOUT_DOWN", ">", value=0.5)
    return _group("OR", [up, down])


def compile_nr7_breakout(config: dict) -> dict:
    """NR7 (narrowest-range-7) volatility-contraction breakout. See
    python-strategy-generator.ts's `nr7-breakout` signal (no configurable
    params). Uses NR7_BREAKOUT_UP/DOWN.
    """
    up = _leaf("NR7_BREAKOUT_UP", ">", value=0.5)
    down = _leaf("NR7_BREAKOUT_DOWN", ">", value=0.5)
    return _group("OR", [up, down])


def compile_bollinger_reversal(config: dict) -> dict:
    """Bollinger Band mean-reversion. See python-strategy-generator.ts's
    `bollinger-reversal` signal (bbPeriod, bbStdDev). Uses BB_UPPER/LOWER
    compared against live SPOT -- a touch of either band.
    """
    period = int(config.get("bbPeriod", 20) or 20)
    stddev = float(config.get("bbStdDev", 2.0) or 2.0)

    params = {"period": period, "stddev": stddev}
    lower_touch = _leaf("SPOT", "<", value_indicator="BB_LOWER", value_indicator_params=params)
    upper_touch = _leaf("SPOT", ">", value_indicator="BB_UPPER", value_indicator_params=params)
    return _group("OR", [lower_touch, upper_touch])


def compile_vwap_reversion(config: dict) -> dict:
    """VWAP mean-reversion. See python-strategy-generator.ts's
    `vwap-reversion` signal (deviation threshold, fixed at 0.5% in the
    reference). Uses VWAP_DEVIATION_BELOW/ABOVE -- a deviation, not a
    crossover (see compile_vwap_scalp for the crossover variant).
    """
    threshold = float(config.get("deviationPercent", 0.5) or 0.5)

    below = _leaf("VWAP_DEVIATION_BELOW", ">", value=0.5, threshold_pct=threshold)
    above = _leaf("VWAP_DEVIATION_ABOVE", ">", value=0.5, threshold_pct=threshold)
    return _group("OR", [below, above])


def compile_keltner_reversion(config: dict) -> dict:
    """Keltner Channel mean-reversion. See python-strategy-generator.ts's
    `keltner-reversion` signal (emaPeriod, atrPeriod, atrMultiplier). Uses
    KELTNER_UPPER/LOWER compared against live SPOT.
    """
    ema_period = int(config.get("emaPeriod", 20) or 20)
    atr_period = int(config.get("atrPeriod", 10) or 10)
    multiplier = float(config.get("atrMultiplier", 2.0) or 2.0)

    params = {"ema_period": ema_period, "atr_period": atr_period, "atr_multiplier": multiplier}
    lower_touch = _leaf("SPOT", "<", value_indicator="KELTNER_LOWER", value_indicator_params=params)
    upper_touch = _leaf("SPOT", ">", value_indicator="KELTNER_UPPER", value_indicator_params=params)
    return _group("OR", [lower_touch, upper_touch])


def compile_donchian_pullback(config: dict) -> dict:
    """Donchian channel midline pullback/bounce. See
    python-strategy-generator.ts's `donchian-pullback` signal
    (donchianPeriod). Uses DONCHIAN_MID_CROSS_UP/DOWN -- a real crossing
    of the midline, not a level check.
    """
    period = int(config.get("donchianPeriod", 20) or 20)

    up = _leaf("DONCHIAN_MID_CROSS_UP", ">", value=0.5, period=period)
    down = _leaf("DONCHIAN_MID_CROSS_DOWN", ">", value=0.5, period=period)
    return _group("OR", [up, down])


def compile_ema_pullback(config: dict) -> dict:
    """EMA pullback-and-bounce in an established uptrend. See
    python-strategy-generator.ts's `ema-pullback` signal (emaPeriod,
    trendEmaPeriod). Uses EMA_PULLBACK_BOUNCE.
    """
    ema_period = int(config.get("emaPeriod", 20) or 20)
    trend_period = int(config.get("trendEmaPeriod", 50) or 50)
    if ema_period >= trend_period:
        raise CompilerError(
            f"ema_pullback: emaPeriod ({ema_period}) must be less than "
            f"trendEmaPeriod ({trend_period})"
        )

    return _leaf(
        "EMA_PULLBACK_BOUNCE", ">", value=0.5,
        ema_period=ema_period, trend_ema_period=trend_period,
    )


def compile_vwap_scalp(config: dict) -> dict:
    """Fast VWAP-cross scalp. See python-strategy-generator.ts's
    `vwap-scalp` signal (no configurable params). Uses VWAP_CROSS_UP/DOWN
    -- a crossover, distinct from compile_vwap_reversion's deviation
    check.
    """
    up = _leaf("VWAP_CROSS_UP", ">", value=0.5)
    down = _leaf("VWAP_CROSS_DOWN", ">", value=0.5)
    return _group("OR", [up, down])


def compile_gap_strategy(config: dict) -> dict:
    """Opening-gap continuation. See python-strategy-generator.ts's
    `gap-strategy` signal (gapThresholdPercent). Uses GAP_PCT against a
    static threshold -- simplified from the reference (which also checks
    same-direction continuation vs the day's open); the gap itself is the
    entry trigger here.
    """
    threshold = float(config.get("gapThresholdPercent", 1.0) or 1.0)

    gap_up = _leaf("GAP_PCT", ">", value=threshold)
    gap_down = _leaf("GAP_PCT", "<", value=-threshold)
    return _group("OR", [gap_up, gap_down])


def compile_bollinger_squeeze(config: dict) -> dict:
    """Volatility-squeeze breakout. See python-strategy-generator.ts's
    `bollinger-squeeze` signal (bbPeriod, bbStdDev, squeezeLookback,
    squeezePercentile). Uses BB_SQUEEZE_BREAKOUT_UP/DOWN.
    """
    period = int(config.get("bbPeriod", 20) or 20)
    stddev = float(config.get("bbStdDev", 2.0) or 2.0)
    lookback = int(config.get("squeezeLookback", 50) or 50)
    percentile = float(config.get("squeezePercentile", 20) or 20)

    params = {"period": period, "stddev": stddev, "lookback": lookback, "percentile": percentile}
    up = _leaf("BB_SQUEEZE_BREAKOUT_UP", ">", value=0.5, **params)
    down = _leaf("BB_SQUEEZE_BREAKOUT_DOWN", ">", value=0.5, **params)
    return _group("OR", [up, down])


def compile_atr_trend(config: dict) -> dict:
    """ATR-based trailing-stop trend system. See
    python-strategy-generator.ts's `atr-trend` signal (atrPeriod,
    emaPeriod, atrMultiplier). Uses ATR_TRAIL_CROSS_UP/DOWN.
    """
    atr_period = int(config.get("atrPeriod", 14) or 14)
    ema_period = int(config.get("emaPeriod", 20) or 20)
    multiplier = float(config.get("atrMultiplier", 1.5) or 1.5)

    params = {"atr_period": atr_period, "ema_period": ema_period, "atr_multiplier": multiplier}
    up = _leaf("ATR_TRAIL_CROSS_UP", ">", value=0.5, **params)
    down = _leaf("ATR_TRAIL_CROSS_DOWN", ">", value=0.5, **params)
    return _group("OR", [up, down])


def compile_basket_strategy(config: dict) -> dict:
    """Multi-symbol basket strategies (equal-weight, top-movers ranking).
    NOT YET SUPPORTED -- a single conditions_tree evaluates against ONE
    symbol/exchange (see condition_engine.py's evaluate_conditions_tree
    signature and _evaluation_loop's per-Deployment symbol resolution);
    it has no way to express "rank N symbols and trade the top movers" or
    "enter equal-weight positions across a symbol list" -- that needs a
    different execution model entirely (multi-symbol iteration + ranking,
    more like the Options Strategy Builder's basket-order flow than a
    single boolean tree). Fails loudly rather than silently deploying a
    strategy that only ever evaluates one arbitrary symbol from the
    basket.
    """
    raise CompilerError(
        "Basket strategies are not yet supported for live deployment via "
        "this wizard (they require multi-symbol ranking/execution, which "
        "the current single-symbol rule engine doesn't support). This is "
        "tracked as a future, separately-designed feature."
    )


def compile_options_strategy(config: dict) -> dict:
    """Options structure entry trigger. NOT YET SUPPORTED -- true options
    execution semantics (which leg/strike to trade) exceed what a single
    conditions_tree can express; this needs its own design pass. Fails
    loudly rather than silently deploying an unenforceable strategy.
    """
    raise CompilerError(
        "Options strategies are not yet supported for rule-based live "
        "deployment via this wizard. Use the Options Strategy Builder's "
        "immediate-execution flow instead."
    )


# ---------------------------------------------------------------------------
# Registry + entry point
# ---------------------------------------------------------------------------

# Mirrors frontend/src/lib/strategy-schemas.ts's STRATEGY_SCHEMAS registry
# 1:1. Adding a new blueprint later: add one compile_* function above, one
# entry here, and (only if it needs a genuinely new calculation) one new
# indicator class in services/indicator_registry.py. Nothing else in the
# execution pipeline needs to change.
STRATEGY_TYPE_REGISTRY = {
    "orb": compile_orb,
    "ema_cross": compile_ema_cross,
    "supertrend": compile_supertrend,
    "rsi_momentum": compile_rsi_momentum,
    "options_strategy": compile_options_strategy,
    "sma_cross": compile_sma_cross,
    "macd_momentum": compile_macd_momentum,
    "rsi_reversal": compile_rsi_reversal,
    "swing_breakout": compile_swing_breakout,
    "roc_momentum": compile_roc_momentum,
    "prev_day_breakout": compile_prev_day_breakout,
    "triple_ema": compile_triple_ema,
    "adx_trend": compile_adx_trend,
    "volume_breakout": compile_volume_breakout,
    "inside_candle_breakout": compile_inside_candle_breakout,
    "nr7_breakout": compile_nr7_breakout,
    "bollinger_reversal": compile_bollinger_reversal,
    "vwap_reversion": compile_vwap_reversion,
    "keltner_reversion": compile_keltner_reversion,
    "donchian_pullback": compile_donchian_pullback,
    "ema_pullback": compile_ema_pullback,
    "vwap_scalp": compile_vwap_scalp,
    "gap_strategy": compile_gap_strategy,
    "bollinger_squeeze": compile_bollinger_squeeze,
    "atr_trend": compile_atr_trend,
    "basket_strategy": compile_basket_strategy,
}


def _assert_no_malformed_leaves(node: dict) -> None:
    """Recursively verify every leaf carries both `indicator` and
    `condition`. condition_engine.py's leaf handler treats a leaf missing
    either key as an automatic pass (`return True`) rather than a failure --
    a landmine for a live-trading system. This compiler's contract is that
    it NEVER emits such a leaf; this assertion catches a compiler bug before
    it ever reaches the database."""
    if not node:
        return
    if "operator" in node:
        for child in node.get("children", []):
            _assert_no_malformed_leaves(child)
        return
    if not node.get("indicator") or not node.get("condition"):
        raise CompilerError(
            f"Compiler produced a malformed leaf missing indicator/condition: {node}"
        )


def compile_strategy_config(template_id: str | None, config: dict) -> dict:
    """Entry point. Raises CompilerError if the blueprint isn't registered,
    the config fails blueprint-specific validation, or (as a defensive
    check) the compiled tree contains a malformed leaf."""
    if config is None:
        config = {}

    schema_key = _resolve_schema_key(template_id)
    compiler = STRATEGY_TYPE_REGISTRY.get(schema_key)
    if compiler is None:
        raise CompilerError(f"No compiler registered for strategy type '{schema_key}'")

    tree = compiler(config)
    _assert_no_malformed_leaves(tree)
    return tree
