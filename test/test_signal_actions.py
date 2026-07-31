"""Tests for the per-signal action model (Signal Actions table).

Covers the three things the feature promises:
  1. every new field is OPT-IN -- a mapping with none of them set behaves
     exactly as it did before the feature existed;
  2. the values that ARE supplied are validated strictly, so a typo fails
     at configuration time rather than mis-trading at signal time;
  3. multi-leg baskets fire in a deterministic, safe order.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import blueprints.strategy as strategy_bp  # noqa: E402
from database.strategy_db import (  # noqa: E402
    ORDER_TYPES,
    SIGNAL_ACTIONS,
    StrategySymbolMapping,
)

validate = strategy_bp._validate_signal_action_config


# ---------------------------------------------------------------------
# Backward compatibility -- the most important property here
# ---------------------------------------------------------------------


def test_empty_payload_sets_nothing():
    """A form that ignores the advanced section must produce no columns,
    so the mapping stays byte-identical to a pre-feature one."""
    assert validate({}) == {}


def test_null_signal_action_means_enter():
    """Every mapping created before signal_action existed placed an entry
    order -- ENTER is the only safe interpretation of NULL."""
    assert StrategySymbolMapping(signal_action=None).get_signal_action() == "ENTER"
    assert StrategySymbolMapping(signal_action="").get_signal_action() == "ENTER"


def test_unknown_signal_action_falls_back_to_enter():
    """Defensive: a value that somehow bypassed validation must not crash
    signal processing."""
    assert StrategySymbolMapping(signal_action="BOGUS").get_signal_action() == "ENTER"


def test_no_risk_fields_means_no_risk_orders():
    assert StrategySymbolMapping(quantity=1).get_risk_config() == {}


def test_raw_quantity_used_when_lots_unset():
    m = StrategySymbolMapping(quantity=25, lots=None)
    assert m.resolve_quantity(75) == 25


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------


@pytest.mark.parametrize("verb", SIGNAL_ACTIONS)
def test_every_documented_verb_is_accepted(verb):
    assert validate({"signal_action": verb})["signal_action"] == verb


def test_signal_action_is_case_insensitive():
    assert validate({"signal_action": "exit"})["signal_action"] == "EXIT"


def test_unknown_verb_is_rejected():
    with pytest.raises(ValueError, match="signal_action must be one of"):
        validate({"signal_action": "YOLO"})


@pytest.mark.parametrize("order_type", ORDER_TYPES)
def test_every_order_type_accepted_with_required_prices(order_type):
    payload = {"order_type": order_type}
    if order_type in ("LIMIT", "SL"):
        payload["limit_price"] = "100"
    if order_type in ("SL", "SL-M"):
        payload["trigger_price"] = "99"
    assert validate(payload)["order_type"] == order_type


def test_limit_order_requires_a_price():
    """A LIMIT with no price would be rejected by the broker at signal
    time -- catch it while the user is still looking at the form."""
    with pytest.raises(ValueError, match="limit_price is required"):
        validate({"order_type": "LIMIT"})


def test_stop_order_requires_a_trigger():
    with pytest.raises(ValueError, match="trigger_price is required"):
        validate({"order_type": "SL-M"})


@pytest.mark.parametrize(
    "payload,message",
    [
        ({"stop_loss_value": "-5"}, "greater than 0"),
        ({"stop_loss_value": "0"}, "greater than 0"),
        ({"stop_loss_value": "abc"}, "must be a number"),
        ({"stop_loss_value": "100", "stop_loss_type": "percent"}, "below 100"),
        ({"stop_loss_value": "5", "stop_loss_type": "rupees"}, "stop_loss_type must be one of"),
        ({"lots": "0"}, "lots must be greater than 0"),
        ({"lots": "two"}, "lots must be a whole number"),
    ],
)
def test_invalid_values_are_rejected(payload, message):
    with pytest.raises(ValueError, match=message):
        validate(payload)


def test_risk_type_defaults_to_percent():
    """A value with no explicit unit is a percentage -- the safer reading,
    since a bare '2' meaning 2 points on a 20000-point index would be a
    near-instant stop-out."""
    result = validate({"stop_loss_value": "2"})
    assert result["stop_loss_type"] == "percent"


def test_points_unit_allows_values_over_100():
    """The <100 ceiling is a percent-only sanity check; 250 points is a
    perfectly ordinary index stop."""
    result = validate({"target_value": "250", "target_type": "points"})
    assert result == {"target_value": 250.0, "target_type": "points"}


def test_long_basket_and_label_are_truncated_not_rejected():
    result = validate({"leg_basket": "b" * 80, "label": "l" * 200})
    assert len(result["leg_basket"]) == 50
    assert len(result["label"]) == 100


# ---------------------------------------------------------------------
# Risk config + sizing
# ---------------------------------------------------------------------


def test_risk_config_shape():
    m = StrategySymbolMapping(
        quantity=1,
        stop_loss_value=2.0,
        stop_loss_type="percent",
        target_value=10.0,
        target_type="points",
    )
    assert m.get_risk_config() == {
        "stop_loss": {"type": "percent", "value": 2.0},
        "target": {"type": "points", "value": 10.0},
    }


def test_lots_multiply_by_lot_size():
    m = StrategySymbolMapping(quantity=1, lots=3)
    assert m.resolve_quantity(75) == 225


def test_lots_fall_back_to_quantity_when_lot_size_unknown():
    """Sending a wrongly-multiplied order is far worse than sending the
    old raw quantity, so an unresolvable lot size degrades rather than
    guesses."""
    m = StrategySymbolMapping(quantity=50, lots=3)
    assert m.resolve_quantity(None) == 50


# ---------------------------------------------------------------------
# Multi-leg basket ordering
# ---------------------------------------------------------------------


def _mapping(**kwargs):
    kwargs.setdefault("quantity", 1)
    return StrategySymbolMapping(**kwargs)


def test_basket_legs_stay_contiguous_and_ordered():
    from services.signal_engine import _mapping_sort_key

    rows = [
        _mapping(id=3, leg_basket="straddle", basket_leg_order=2),
        _mapping(id=1, leg_basket=None),
        _mapping(id=2, leg_basket="straddle", basket_leg_order=1),
    ]
    ordered = sorted(rows, key=_mapping_sort_key)

    # Standalone (empty basket) sorts first, then the basket's legs in the
    # user's explicit order.
    assert [m.id for m in ordered] == [1, 2, 3]


def test_closing_legs_fire_before_opening_ones():
    """A roll must free margin before the replacement leg consumes it."""
    from services.signal_engine import _mapping_sort_key

    rows = [
        _mapping(id=1, leg_basket="roll", signal_action="ENTER"),
        _mapping(id=2, leg_basket="roll", signal_action="EXIT"),
    ]
    ordered = sorted(rows, key=_mapping_sort_key)
    assert [m.get_signal_action() for m in ordered] == ["EXIT", "ENTER"]


def test_sort_is_stable_for_identical_rows():
    """Falls back to id so firing order doesn't depend on however the DB
    happened to return the rows."""
    from services.signal_engine import _mapping_sort_key

    rows = [_mapping(id=9), _mapping(id=4), _mapping(id=7)]
    assert [m.id for m in sorted(rows, key=_mapping_sort_key)] == [4, 7, 9]
