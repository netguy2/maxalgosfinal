# services/signal_normalizer.py
"""Pure translation functions: external webhook/JSON shapes <-> ``Signal``.

Extracted from ``blueprints/chartink.py`` (Chartink scan webhook payload
building) and ``blueprints/tv_json.py`` (TradingView JSON template
generation) so both share one normalization layer and one place
(``signal_to_order_dict``) that converts a normalized ``Signal`` back into
the flat order-dict shape ``restx_api.schemas.OrderSchema`` /
``SmartOrderSchema`` validate.

This module is a pure refactor: it must not change any runtime behavior of
either caller. See test/test_signal_normalizer.py for byte-for-byte
regression assertions against the original inline logic.
"""

from __future__ import annotations

from services.signal_schema import Signal


def normalize_chartink(strategy, symbol, mapping, action, use_smart_order) -> Signal:
    """Build a normalized ``Signal`` from a Chartink scan webhook symbol entry.

    Mirrors the payload-building block formerly inline at
    ``blueprints/chartink.py:914-941``. ``action`` and ``use_smart_order`` are
    determined by the caller from scan-name keywords (BUY/SELL/SHORT/COVER)
    before this function is invoked -- see the comment in
    ``blueprints/chartink.py`` at that decision point for the exact mapping,
    including the noted SHORT/COVER quirk.

    Args:
        strategy: ChartinkStrategy row (uses ``strategy.name``).
        symbol: The raw Chartink symbol string (unused for payload fields
            directly -- mapping.chartink_symbol is authoritative -- but kept
            as a parameter to mirror the call site's available data).
        mapping: ChartinkSymbolMapping row (chartink_symbol, exchange,
            product_type, quantity).
        action: "BUY" or "SELL", already resolved from scan_name keywords.
        use_smart_order: bool, already resolved from scan_name keywords.

    Returns:
        Signal with instrument_class="EQUITY" (Chartink scans are always
        equity today).
    """
    if use_smart_order:
        # For SELL and COVER, use smart order with quantity=0 / position_size=0.
        quantity = "0"
    else:
        # For BUY and SHORT, use regular order with configured quantity.
        quantity = str(mapping.quantity)

    return Signal(
        source_type="chartink",
        strategy_tag=strategy.name,
        instrument_class="EQUITY",
        symbol=mapping.chartink_symbol,
        exchange=mapping.exchange,
        action=action,
        quantity=quantity,
        use_smart_order=use_smart_order,
        product=mapping.product_type,
        pricetype="MARKET",
        price="0" if use_smart_order else None,
        trigger_price="0" if use_smart_order else None,
        disclosed_quantity="0" if use_smart_order else None,
        raw_extra={"position_size": "0"} if use_smart_order else {},
    )


def normalize_tradingview(request_json, symbol_data, api_key, mode) -> Signal:
    """Build a normalized ``Signal`` from a TradingView JSON-template request.

    Mirrors the two branches formerly inline at
    ``blueprints/tv_json.py:47-94``.

    Args:
        request_json: The incoming ``request.json`` dict (has ``action``,
            ``quantity`` for line mode; unused fields for strategy mode
            beyond what's already resolved by the caller).
        symbol_data: The resolved symbol row from ``enhanced_search_symbols``
            (uses ``.symbol`` and ``.exchange``).
        api_key: The user's TradingView API key string.
        mode: "line" or "strategy" (anything other than "line" is treated as
            strategy mode, matching the original ``if mode == "line" ... else``).

    Returns:
        Signal with instrument_class="EQUITY". In strategy mode, ``action``,
        ``quantity``, and ``raw_extra["position_size"]`` intentionally hold
        TradingView's own unresolved placeholder strings
        (``{{strategy.order.action}}``, ``{{strategy.order.contracts}}``,
        ``{{strategy.position_size}}``) -- these are opaque template strings
        TradingView substitutes client-side, not real values, and must
        survive unchanged.
    """
    product = request_json.get("product")

    if mode == "line":
        action = request_json.get("action")
        quantity = request_json.get("quantity")

        return Signal(
            source_type="tradingview",
            strategy_tag="TradingView Line Alert",
            instrument_class="EQUITY",
            symbol=symbol_data.symbol,
            exchange=symbol_data.exchange,
            action=action.upper(),
            quantity=str(quantity),
            use_smart_order=False,
            product=product,
            pricetype="MARKET",
        )
    else:
        # Strategy Alert Mode - placeholders resolved client-side by TradingView.
        return Signal(
            source_type="tradingview",
            strategy_tag="TradingView Strategy",
            instrument_class="EQUITY",
            symbol=symbol_data.symbol,
            exchange=symbol_data.exchange,
            action="{{strategy.order.action}}",
            quantity="{{strategy.order.contracts}}",
            use_smart_order=True,
            product=product,
            pricetype="MARKET",
            raw_extra={"position_size": "{{strategy.position_size}}"},
        )


def signal_to_order_dict(signal: Signal, api_key: str) -> tuple[dict, str]:
    """Convert a normalized ``Signal`` into the flat order-dict wire shape.

    This is the single place both Chartink and TradingView translators use
    to go from a ``Signal`` to the dict shape expected by
    ``OrderSchema``/``SmartOrderSchema`` (via ``/api/v1/placeorder`` /
    ``placesmartorder``).

    Returns:
        (payload_dict, endpoint) where endpoint is "placeorder" or
        "placesmartorder", matching ``signal.use_smart_order``.
    """
    payload = {
        "apikey": api_key,
        "strategy": signal.strategy_tag,
        "symbol": signal.symbol,
        "exchange": signal.exchange,
        "action": signal.action,
        "product": signal.product,
        "pricetype": signal.pricetype,
    }

    if signal.use_smart_order:
        payload.update(
            {
                "quantity": signal.quantity if signal.quantity is not None else "0",
                "position_size": signal.raw_extra.get("position_size", "0"),
                "price": signal.price if signal.price is not None else "0",
                "trigger_price": signal.trigger_price if signal.trigger_price is not None else "0",
                "disclosed_quantity": (
                    signal.disclosed_quantity if signal.disclosed_quantity is not None else "0"
                ),
            }
        )
        endpoint = "placesmartorder"
    else:
        payload.update({"quantity": signal.quantity})
        endpoint = "placeorder"

    return payload, endpoint
