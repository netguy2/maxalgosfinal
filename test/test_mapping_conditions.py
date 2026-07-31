"""Tests for per-rule conditions (time window / indicator gates).

These gate a webhook rule so it only fires inside a time window or when an
indicator agrees -- the "don't trade the opening five minutes" and "don't buy
an overbought market" requests.

Deliberately a small fixed shape rather than the full condition tree the Flow
canvas supports: the platform already has a node editor for arbitrary
IF/AND/OR logic, and a second general-purpose engine here would be one more
thing to keep in sync. See StrategySymbolMapping.conditions.
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest  # noqa: E402

import blueprints.strategy as strategy_bp  # noqa: E402
from database.strategy_db import StrategySymbolMapping  # noqa: E402

validate = strategy_bp._validate_signal_action_config


def _mapping(cfg=None):
    return StrategySymbolMapping(
        quantity=1, conditions=json.dumps(cfg) if cfg else None
    )


def _at(hh, mm):
    return datetime(2026, 7, 27, hh, mm)


# ---------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------


def test_no_conditions_always_fires():
    """Every rule created before this feature must keep firing."""
    passed, reason = _mapping().conditions_pass()
    assert passed is True
    assert reason is None


def test_malformed_json_does_not_block_trading():
    """Corrupt config must not silently halt a strategy -- it degrades to
    'no conditions' and logs, rather than blocking every signal."""
    m = StrategySymbolMapping(quantity=1, conditions="{not json")
    assert m.conditions_pass()[0] is True


# ---------------------------------------------------------------------
# Time window
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "hh,mm,expected",
    [(9, 15, False), (9, 20, True), (12, 0, True), (15, 0, True), (15, 30, False)],
)
def test_time_window_gates_correctly(hh, mm, expected):
    m = _mapping({"time_after": "09:20", "time_before": "15:00"})
    assert m.conditions_pass(now=_at(hh, mm))[0] is expected


def test_blocked_signal_explains_why():
    """A skipped order must be distinguishable from a broken strategy."""
    m = _mapping({"time_after": "09:20"})
    passed, reason = m.conditions_pass(now=_at(9, 0))
    assert passed is False
    assert "09:20" in reason


def test_open_ended_windows():
    after_only = _mapping({"time_after": "09:20"})
    assert after_only.conditions_pass(now=_at(23, 0))[0] is True

    before_only = _mapping({"time_before": "15:00"})
    assert before_only.conditions_pass(now=_at(1, 0))[0] is True


# ---------------------------------------------------------------------
# Indicator gate
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "op,value,current,expected",
    [
        ("<", 70, 65, True),
        ("<", 70, 80, False),
        (">", 30, 45, True),
        (">", 30, 20, False),
        (">=", 50, 50, True),
        ("<=", 50, 50, True),
        ("!=", 50, 51, True),
        ("==", 50, 50, True),
    ],
)
def test_indicator_operators(op, value, current, expected):
    m = _mapping({"indicator": {"name": "RSI", "op": op, "value": value}})
    assert m.conditions_pass(indicator_value=current)[0] is expected


def test_indicator_gate_fails_open_with_no_feed():
    """An unreachable indicator must not silently halt trading -- same
    fail-open posture the engine's other safety checks take."""
    m = _mapping({"indicator": {"name": "RSI", "op": "<", "value": 70}})
    assert m.conditions_pass(indicator_value=None)[0] is True


def test_both_gates_must_pass():
    m = _mapping(
        {"time_after": "09:20", "indicator": {"name": "RSI", "op": "<", "value": 70}}
    )
    assert m.conditions_pass(now=_at(10, 0), indicator_value=60)[0] is True
    assert m.conditions_pass(now=_at(9, 0), indicator_value=60)[0] is False
    assert m.conditions_pass(now=_at(10, 0), indicator_value=80)[0] is False


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------


def test_valid_conditions_are_stored_as_json():
    result = validate(
        {"conditions": {"time_after": "09:20", "indicator": {"name": "RSI", "op": "<", "value": "70"}}}
    )
    stored = json.loads(result["conditions"])
    assert stored["time_after"] == "09:20"
    assert stored["indicator"]["value"] == 70.0


@pytest.mark.parametrize("bad", ["25:00", "9:20", "0920", "abc"])
def test_invalid_times_are_rejected(bad):
    """Catch a typo at configuration time rather than blocking every signal
    silently at runtime."""
    with pytest.raises(ValueError, match="HH:MM"):
        validate({"conditions": {"time_after": bad}})


def test_non_numeric_indicator_value_rejected():
    with pytest.raises(ValueError, match="numeric"):
        validate({"conditions": {"indicator": {"name": "RSI", "value": "high"}}})


def test_empty_conditions_store_nothing():
    """An untouched conditions UI must leave the column NULL."""
    assert "conditions" not in validate({"conditions": {}})
    assert "conditions" not in validate({})
