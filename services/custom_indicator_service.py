# services/custom_indicator_service.py
"""
Custom indicator formula validation + computation.

Formulas are built entirely from a fixed, whitelisted menu (indicator
name + period as an operand, a whitelisted arithmetic operator or a
threshold comparison) -- never arbitrary user-supplied code or an eval()
of free text. This module is the single place that both validates a
formula against that whitelist (before it's ever saved) and evaluates one
against a caller-supplied set of OHLCV bars (before it's ever rendered).

Reuses services/historify_service.py's existing _INDICATOR_SPECS dispatch
table for computing each operand's series -- the same dispatch the
built-in Charts indicators already go through -- and
services/indicator_series_service.py's combine_series/
detect_threshold_crossover_signals for the combining step.
"""

from typing import Any

import pandas as pd

from utils.logging import get_logger

logger = get_logger(__name__)

# Operand indicators a custom formula may reference. MACD and multi-output
# indicators in general are excluded here -- a formula operand must
# resolve to a single numeric series, and MACD's compute function returns
# a dict of three sub-series with no single obvious "the value" choice.
# BOLLINGER is single-output-eligible for reuse here (its basis line) --
# see _resolve_operand_series below.
ALLOWED_OPERAND_INDICATORS = {"EMA", "SMA", "VWAP", "RSI", "ATR", "BOLLINGER"}
ALLOWED_COMBINE_OPS = {"+", "-", "*", "/"}


class FormulaValidationError(ValueError):
    pass


def validate_formula(formula: dict[str, Any]) -> None:
    """Raises FormulaValidationError with a clear message if the formula
    doesn't match the fixed whitelist shape. Called before a formula is
    ever saved to the database."""
    kind = formula.get("kind")
    if kind not in ("combine", "threshold"):
        raise FormulaValidationError("formula.kind must be 'combine' or 'threshold'")

    operand_a = formula.get("a")
    _validate_operand(operand_a, "a")

    if kind == "combine":
        operand_b = formula.get("b")
        _validate_operand(operand_b, "b")
        op = formula.get("op")
        if op not in ALLOWED_COMBINE_OPS:
            raise FormulaValidationError(f"op must be one of {sorted(ALLOWED_COMBINE_OPS)}")
    else:  # threshold
        threshold = formula.get("threshold")
        if not isinstance(threshold, (int, float)):
            raise FormulaValidationError("threshold must be a number")
        if not isinstance(formula.get("invert", False), bool):
            raise FormulaValidationError("invert must be a boolean")


def _validate_operand(operand: Any, field_name: str) -> None:
    if not isinstance(operand, dict):
        raise FormulaValidationError(f"{field_name} must be an object")
    indicator = operand.get("indicator")
    if indicator not in ALLOWED_OPERAND_INDICATORS:
        raise FormulaValidationError(
            f"{field_name}.indicator must be one of {sorted(ALLOWED_OPERAND_INDICATORS)}"
        )
    period = operand.get("period")
    if indicator != "VWAP" and not isinstance(period, int):
        raise FormulaValidationError(f"{field_name}.period must be an integer")


def _resolve_operand_series(df: pd.DataFrame, operand: dict[str, Any]) -> list[dict]:
    """Computes the single numeric series for one formula operand, reusing
    the exact same compute_* functions the built-in indicators use."""
    from services import indicator_series_service as iss

    indicator = operand["indicator"]
    period = operand.get("period")

    if indicator == "EMA":
        return iss.compute_ema(df, period=period)
    if indicator == "SMA":
        return iss.compute_sma(df, period=period)
    if indicator == "VWAP":
        return iss.compute_vwap(df)
    if indicator == "RSI":
        return iss.compute_rsi(df, period=period)
    if indicator == "ATR":
        return iss.compute_atr(df, period=period)
    if indicator == "BOLLINGER":
        # A Bollinger operand resolves to its basis (middle) line -- the
        # upper/lower bands aren't meaningful as a single-value operand in
        # a combine/threshold formula.
        return iss.compute_bollinger(df, period=period or 20).get("basis", [])
    raise FormulaValidationError(f"Unsupported operand indicator: {indicator}")


def compute_custom_indicator(bars: list[dict[str, Any]], formula: dict[str, Any]) -> dict[str, Any]:
    """
    Evaluates one already-validated formula against the given OHLCV bars.

    Returns:
        {"series": [...]} for a combine formula (a plottable overlay line),
        or {"signals": [...]} for a threshold formula (BUY/SELL crossover
        markers, same shape as the built-in indicators' signal output).
    """
    from services import indicator_series_service as iss

    df = pd.DataFrame(bars)
    if df.empty:
        return {"series": [], "signals": []}
    df = df.sort_values("timestamp").reset_index(drop=True)

    series_a = _resolve_operand_series(df, formula["a"])

    if formula["kind"] == "combine":
        series_b = _resolve_operand_series(df, formula["b"])
        combined = iss.combine_series(formula["op"], series_a, series_b)
        return {"series": combined}
    else:  # threshold
        signals = iss.detect_threshold_crossover_signals(
            series_a, threshold=formula["threshold"], invert=formula.get("invert", False)
        )
        return {"series": series_a, "signals": signals}


def compute_custom_indicators_from_bars(
    bars: list[dict[str, Any]], formulas: list[dict[str, Any]]
) -> tuple[bool, dict[str, Any], int]:
    """Computes multiple custom indicators in one call -- same "send the
    bars you're already rendering" pattern as
    historify_service.get_indicator_overlays_from_bars. `formulas` is a
    list of {"id": <custom_indicator_id>, "formula": {...}}."""
    try:
        results: dict[str, Any] = {}
        for entry in formulas:
            indicator_id = str(entry.get("id"))
            formula = entry.get("formula")
            try:
                validate_formula(formula)
                results[indicator_id] = compute_custom_indicator(bars, formula)
            except FormulaValidationError as e:
                results[indicator_id] = {"error": str(e)}
        return True, {"status": "success", "data": results}, 200
    except Exception as e:
        logger.exception(f"Error computing custom indicators: {e}")
        return False, {"status": "error", "message": str(e)}, 500
