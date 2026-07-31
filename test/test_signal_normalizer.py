"""Regression tests for services/signal_normalizer.py and signal_schema.py.

These prove the extract-and-refactor of blueprints/chartink.py (scan webhook
payload building) and blueprints/tv_json.py (TradingView JSON template
generation) into the shared Signal normalization layer produced byte-for-byte
identical output to the original inline logic, for all four Chartink scan
keywords (BUY/SELL/SHORT/COVER) and both TradingView modes (line/strategy).

The highest-risk regression is the TradingView strategy-alert placeholder
strings ({{strategy.order.action}} etc.) -- these must survive unchanged
end-to-end through Signal construction and back into the response dict.
"""

from types import SimpleNamespace

import pytest
from marshmallow import ValidationError

from services.signal_normalizer import (
    normalize_chartink,
    normalize_tradingview,
    signal_to_order_dict,
)
from services.signal_schema import Signal

# ---------------------------------------------------------------------------
# Helpers mirroring the original inline logic (blueprints/chartink.py:826-846)
# so tests assert against ground truth, not against the extraction itself.
# ---------------------------------------------------------------------------

def _resolve_chartink_action(scan_name: str):
    scan_name = scan_name.upper()
    if "BUY" in scan_name:
        return "BUY", False
    elif "SELL" in scan_name:
        return "SELL", True
    elif "SHORT" in scan_name:
        return "SELL", False
    elif "COVER" in scan_name:
        return "BUY", True
    raise ValueError("no keyword")


def _original_chartink_payload(strategy_name, api_key, mapping, action, use_smart_order):
    """Ground truth: the exact dict-building logic that was inline at
    blueprints/chartink.py:914-941 before this refactor."""
    payload = {
        "apikey": api_key,
        "strategy": strategy_name,
        "symbol": mapping.chartink_symbol,
        "exchange": mapping.exchange,
        "action": action,
        "product": mapping.product_type,
        "pricetype": "MARKET",
    }
    if use_smart_order:
        payload.update(
            {
                "quantity": "0",
                "position_size": "0",
                "price": "0",
                "trigger_price": "0",
                "disclosed_quantity": "0",
            }
        )
        endpoint = "placesmartorder"
    else:
        payload.update({"quantity": str(mapping.quantity)})
        endpoint = "placeorder"
    return payload, endpoint


def _make_mapping(chartink_symbol="SBIN", exchange="NSE", quantity=10, product_type="MIS"):
    return SimpleNamespace(
        chartink_symbol=chartink_symbol,
        exchange=exchange,
        quantity=quantity,
        product_type=product_type,
    )


# ---------------------------------------------------------------------------
# Chartink: BUY / SELL / SHORT / COVER
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "scan_name",
    [
        "Morning BUY Scan",
        "EOD SELL Scan",
        "Intraday SHORT Setup",
        "Intraday COVER Setup",
    ],
)
def test_chartink_normalize_matches_original_for_all_keywords(scan_name):
    action, use_smart_order = _resolve_chartink_action(scan_name)

    strategy = SimpleNamespace(name="MyStrategy")
    mapping = _make_mapping()
    api_key = "test-api-key-123"

    expected_payload, expected_endpoint = _original_chartink_payload(
        strategy.name, api_key, mapping, action, use_smart_order
    )

    signal = normalize_chartink(
        strategy=strategy,
        symbol=mapping.chartink_symbol,
        mapping=mapping,
        action=action,
        use_smart_order=use_smart_order,
    )
    actual_payload, actual_endpoint = signal_to_order_dict(signal, api_key)

    assert actual_endpoint == expected_endpoint
    assert actual_payload == expected_payload


def test_chartink_buy_uses_regular_order_with_configured_quantity():
    strategy = SimpleNamespace(name="BuyStrategy")
    mapping = _make_mapping(quantity=25)
    signal = normalize_chartink(
        strategy=strategy, symbol="SBIN", mapping=mapping, action="BUY", use_smart_order=False
    )
    payload, endpoint = signal_to_order_dict(signal, "key")
    assert endpoint == "placeorder"
    assert payload["quantity"] == "25"
    assert "position_size" not in payload


def test_chartink_sell_uses_smart_order_zeroed_fields():
    strategy = SimpleNamespace(name="SellStrategy")
    mapping = _make_mapping(quantity=25)
    signal = normalize_chartink(
        strategy=strategy, symbol="SBIN", mapping=mapping, action="SELL", use_smart_order=True
    )
    payload, endpoint = signal_to_order_dict(signal, "key")
    assert endpoint == "placesmartorder"
    assert payload["quantity"] == "0"
    assert payload["position_size"] == "0"
    assert payload["price"] == "0"
    assert payload["trigger_price"] == "0"
    assert payload["disclosed_quantity"] == "0"


def test_chartink_short_action_is_sell_entry_not_smart_order():
    """SHORT resolves to action=SELL, use_smart_order=False (entry order) --
    preserved exactly per the original scan-name branch, not "fixed"."""
    strategy = SimpleNamespace(name="ShortStrategy")
    mapping = _make_mapping(quantity=5)
    action, use_smart_order = _resolve_chartink_action("SHORT Setup")
    assert action == "SELL"
    assert use_smart_order is False

    signal = normalize_chartink(
        strategy=strategy, symbol="SBIN", mapping=mapping, action=action, use_smart_order=use_smart_order
    )
    payload, endpoint = signal_to_order_dict(signal, "key")
    assert endpoint == "placeorder"
    assert payload["action"] == "SELL"
    assert payload["quantity"] == "5"


def test_chartink_cover_action_is_buy_smart_order():
    """COVER resolves to action=BUY, use_smart_order=True (exit order) --
    preserved exactly per the original scan-name branch."""
    strategy = SimpleNamespace(name="CoverStrategy")
    mapping = _make_mapping(quantity=5)
    action, use_smart_order = _resolve_chartink_action("COVER Setup")
    assert action == "BUY"
    assert use_smart_order is True

    signal = normalize_chartink(
        strategy=strategy, symbol="SBIN", mapping=mapping, action=action, use_smart_order=use_smart_order
    )
    payload, endpoint = signal_to_order_dict(signal, "key")
    assert endpoint == "placesmartorder"
    assert payload["action"] == "BUY"
    assert payload["quantity"] == "0"


# ---------------------------------------------------------------------------
# TradingView: line mode
# ---------------------------------------------------------------------------

def test_tradingview_line_mode_normalize_matches_original():
    request_json = {
        "symbol": "SBIN",
        "exchange": "NSE",
        "product": "MIS",
        "mode": "line",
        "action": "buy",
        "quantity": "10",
    }
    symbol_data = SimpleNamespace(symbol="SBIN", exchange="NSE")
    api_key = "tv-api-key"

    signal = normalize_tradingview(request_json, symbol_data, api_key, "line")

    assert signal.strategy_tag == "TradingView Line Alert"
    assert signal.symbol == "SBIN"
    assert signal.exchange == "NSE"
    assert signal.action == "BUY"
    assert signal.quantity == "10"
    assert signal.product == "MIS"
    assert signal.pricetype == "MARKET"
    assert signal.use_smart_order is False

    # Reconstruct the exact OrderedDict shape the endpoint returns.
    from collections import OrderedDict

    expected = OrderedDict(
        [
            ("apikey", api_key),
            ("strategy", "TradingView Line Alert"),
            ("symbol", "SBIN"),
            ("action", "BUY"),
            ("exchange", "NSE"),
            ("pricetype", "MARKET"),
            ("product", "MIS"),
            ("quantity", "10"),
        ]
    )
    actual = OrderedDict(
        [
            ("apikey", api_key),
            ("strategy", signal.strategy_tag),
            ("symbol", signal.symbol),
            ("action", signal.action),
            ("exchange", signal.exchange),
            ("pricetype", signal.pricetype),
            ("product", signal.product),
            ("quantity", signal.quantity),
        ]
    )
    assert actual == expected
    assert list(actual.keys()) == list(expected.keys())


# ---------------------------------------------------------------------------
# TradingView: strategy mode -- placeholder-preservation is the highest-risk case
# ---------------------------------------------------------------------------

def test_tradingview_strategy_mode_preserves_placeholders_end_to_end():
    request_json = {
        "symbol": "SBIN",
        "exchange": "NSE",
        "product": "MIS",
        "mode": "strategy",
    }
    symbol_data = SimpleNamespace(symbol="SBIN", exchange="NSE")
    api_key = "tv-api-key"

    signal = normalize_tradingview(request_json, symbol_data, api_key, "strategy")

    # Placeholders must survive unchanged into the Signal.
    assert signal.action == "{{strategy.order.action}}"
    assert signal.quantity == "{{strategy.order.contracts}}"
    assert signal.raw_extra["position_size"] == "{{strategy.position_size}}"
    assert signal.use_smart_order is True
    assert signal.strategy_tag == "TradingView Strategy"

    from collections import OrderedDict

    expected = OrderedDict(
        [
            ("apikey", api_key),
            ("strategy", "TradingView Strategy"),
            ("symbol", "SBIN"),
            ("action", "{{strategy.order.action}}"),
            ("exchange", "NSE"),
            ("pricetype", "MARKET"),
            ("product", "MIS"),
            ("quantity", "{{strategy.order.contracts}}"),
            ("position_size", "{{strategy.position_size}}"),
        ]
    )
    actual = OrderedDict(
        [
            ("apikey", api_key),
            ("strategy", signal.strategy_tag),
            ("symbol", signal.symbol),
            ("action", signal.action),
            ("exchange", signal.exchange),
            ("pricetype", signal.pricetype),
            ("product", signal.product),
            ("quantity", signal.quantity),
            ("position_size", signal.raw_extra["position_size"]),
        ]
    )
    assert actual == expected
    assert list(actual.keys()) == list(expected.keys())

    # Placeholders must also survive through signal_to_order_dict unresolved.
    payload, endpoint = signal_to_order_dict(signal, api_key)
    assert endpoint == "placesmartorder"
    assert payload["action"] == "{{strategy.order.action}}"
    assert payload["quantity"] == "{{strategy.order.contracts}}"
    assert payload["position_size"] == "{{strategy.position_size}}"


def test_tradingview_placeholder_signal_does_not_raise_validation_error():
    """Signal validation must not reject/coerce TradingView's opaque
    template strings -- they are not real action/quantity values."""
    signal = Signal(
        source_type="tradingview",
        strategy_tag="TradingView Strategy",
        instrument_class="EQUITY",
        symbol="SBIN",
        exchange="NSE",
        action="{{strategy.order.action}}",
        quantity="{{strategy.order.contracts}}",
        use_smart_order=True,
        product="MIS",
        pricetype="MARKET",
        raw_extra={"position_size": "{{strategy.position_size}}"},
    )
    assert signal.action == "{{strategy.order.action}}"


# ---------------------------------------------------------------------------
# Signal schema validation rules
# ---------------------------------------------------------------------------

def test_signal_equity_rejects_strike_option_type_expiry():
    with pytest.raises(ValidationError):
        Signal(
            source_type="chartink",
            strategy_tag="s",
            instrument_class="EQUITY",
            symbol="SBIN",
            exchange="NSE",
            action="BUY",
            strike="100",
        )


def test_signal_options_requires_strike_and_option_type():
    with pytest.raises(ValidationError):
        Signal(
            source_type="generic",
            strategy_tag="s",
            instrument_class="OPTIONS",
            symbol="NIFTY",
            exchange="NFO",
            action="BUY",
        )


def test_signal_futures_requires_expiry():
    with pytest.raises(ValidationError):
        Signal(
            source_type="generic",
            strategy_tag="s",
            instrument_class="FUTURES",
            symbol="NIFTY",
            exchange="NFO",
            action="BUY",
        )


def test_signal_valid_options_signal_does_not_raise():
    signal = Signal(
        source_type="generic",
        strategy_tag="s",
        instrument_class="OPTIONS",
        symbol="NIFTY28MAR2420800CE",
        exchange="NFO",
        action="BUY",
        strike="20800",
        option_type="CE",
    )
    assert signal.strike == "20800"
