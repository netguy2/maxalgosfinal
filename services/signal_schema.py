# services/signal_schema.py
"""Normalized trading-signal schema.

This module defines ``Signal``: a single, formalized in-memory shape that all
external-signal translators (Chartink webhook, TradingView JSON template
generator, and future sources) build before converting to the flat order
dict that ``restx_api.schemas.OrderSchema`` / ``SmartOrderSchema`` validate.

This is a pure normalization layer: it does not place orders, does not touch
the DB, and does not change any wire format. See ``services/signal_normalizer.py``
for the functions that build/consume ``Signal`` instances.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from marshmallow import ValidationError

VALID_SOURCE_TYPES = ("chartink", "tradingview", "generic")
VALID_INSTRUMENT_CLASSES = ("EQUITY", "INDEX", "FUTURES", "OPTIONS", "MCX")
VALID_ACTIONS = ("BUY", "SELL")


@dataclass
class Signal:
    """A normalized trading signal, prior to becoming a wire-format order dict.

    Fields intentionally cover instrument classes (FUTURES/OPTIONS/MCX) that
    no current translator produces yet -- chartink.py and tv_json.py only
    ever build EQUITY signals today -- so that future sources (e.g. an
    options-alert translator) can populate ``strike``/``option_type``/``expiry``
    without a schema change.

    Some fields (``action``, ``quantity``) may legitimately hold TradingView
    placeholder strings like ``"{{strategy.order.action}}"`` for the
    strategy-alert flow -- see ``normalize_tradingview``. Validation is
    deliberately permissive of these opaque template strings; it does not
    attempt to typecheck or coerce them.
    """

    source_type: str
    strategy_tag: str
    instrument_class: str
    symbol: str
    exchange: str
    action: str
    quantity: str | int | float | None = None
    use_smart_order: bool = False
    product: str | None = None
    pricetype: str = "MARKET"
    price: str | None = None
    trigger_price: str | None = None
    disclosed_quantity: str | None = None
    expiry: str | None = None
    strike: str | None = None
    option_type: str | None = None
    raw_extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        validate_signal(self)


def _is_template_placeholder(value: Any) -> bool:
    """True if value is an unresolved TradingView-style ``{{...}}`` placeholder.

    These are opaque strings TradingView substitutes client-side (e.g.
    ``{{strategy.order.action}}``) -- never real typed field values, so
    validation must not reject or coerce them.
    """
    return isinstance(value, str) and value.startswith("{{") and value.endswith("}}")


def validate_signal(signal: Signal) -> None:
    """Validate cross-field consistency rules on a ``Signal``.

    Raises ``marshmallow.ValidationError`` on violation. Permissive of
    ``None``/unset fields for instrument classes that don't need them, and
    permissive of TradingView placeholder strings in any field.

    Rules:
        - OPTIONS requires ``strike`` and ``option_type``.
        - FUTURES / MCX require ``expiry``.
        - EQUITY / INDEX must NOT have ``strike``, ``option_type``, or ``expiry`` set.
    """
    if signal.source_type not in VALID_SOURCE_TYPES:
        raise ValidationError(
            {"source_type": [f"Must be one of {VALID_SOURCE_TYPES}."]}
        )

    if signal.instrument_class not in VALID_INSTRUMENT_CLASSES:
        raise ValidationError(
            {"instrument_class": [f"Must be one of {VALID_INSTRUMENT_CLASSES}."]}
        )

    # Action may be a real BUY/SELL or an unresolved TradingView placeholder
    # string -- do not validate/coerce placeholders.
    if not _is_template_placeholder(signal.action) and signal.action not in VALID_ACTIONS:
        raise ValidationError({"action": [f"Must be one of {VALID_ACTIONS}."]})

    if signal.instrument_class == "OPTIONS":
        if not signal.strike:
            raise ValidationError({"strike": ["Required for OPTIONS instrument_class."]})
        if not signal.option_type:
            raise ValidationError({"option_type": ["Required for OPTIONS instrument_class."]})

    if signal.instrument_class in ("FUTURES", "MCX"):
        if not signal.expiry:
            raise ValidationError({"expiry": ["Required for FUTURES/MCX instrument_class."]})

    if signal.instrument_class in ("EQUITY", "INDEX"):
        if signal.strike:
            raise ValidationError({"strike": ["Must not be set for EQUITY/INDEX instrument_class."]})
        if signal.option_type:
            raise ValidationError(
                {"option_type": ["Must not be set for EQUITY/INDEX instrument_class."]}
            )
        if signal.expiry:
            raise ValidationError({"expiry": ["Must not be set for EQUITY/INDEX instrument_class."]})
