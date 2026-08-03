"""Pre-trade Risk Management System (RMS) gate.

Built to satisfy the SEBI/Exchange algo-provider certification checklist
(Annexure 4) pre-trade risk controls that previously had no platform-wide
enforcement:

    1. Price check at individual order level      -> _check_price_band
    2. Quantity limit check at individual order    -> _check_quantity
    3. Order value check at individual order       -> _check_order_value
    5. Automated execution / runaway stoppage      -> _check_velocity

(#4, Market Price Protection, is handled separately by utils/mpp_slab.py at
the broker-mapping layer. #6, fair-play/price-discovery, is a strategy-design
policy matter with no code-level check.)

This module is deliberately a SECOND gate alongside services/order_gate.py's
kill-switch check, not a replacement -- order_gate.py answers "is trading
halted for this user", this module answers "is THIS SPECIFIC order within
policy". Both fail differently on purpose: order_gate.py fails OPEN (a
settings-read fault must not silently halt every strategy), whereas the
limits here fail CLOSED on a config/programming error (a broken risk check
must never look like "no risk was violated" -- see check_pre_trade_risk's
docstring).

Placement rule: call this from the same choke point as check_order_allowed,
immediately before the broker call, after the analyze/sandbox branch. See
order_gate.py's module docstring for the list of order-placement paths that
must both call check_order_allowed() and pass their order(s) through here.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.error(f"risk_gate: {name}={raw!r} is not a valid number, using default {default}")
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.error(f"risk_gate: {name}={raw!r} is not a valid integer, using default {default}")
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# --- Config -----------------------------------------------------------------
# Every limit is env-tunable and independently disableable (set the *_ENABLED
# flag to false, or the limit to 0) -- exchange-mandated freeze quantities and
# circuit-band percentages vary by segment/instrument and change over time, so
# this platform cannot hardcode a single universally-correct number. These
# defaults are conservative placeholders, not exchange-published values --
# the operator is expected to tune them to their own registered limits.


def _max_order_quantity() -> int:
    return _env_int("RMS_MAX_ORDER_QUANTITY", 10000)


def _max_order_value() -> float:
    return _env_float("RMS_MAX_ORDER_VALUE", 10_000_000.0)  # ₹1 crore


def _price_band_pct() -> float:
    return _env_float("RMS_PRICE_BAND_PCT", 10.0)


def _quantity_check_enabled() -> bool:
    return _env_bool("RMS_QUANTITY_CHECK_ENABLED", True)


def _value_check_enabled() -> bool:
    return _env_bool("RMS_ORDER_VALUE_CHECK_ENABLED", True)


def _price_band_check_enabled() -> bool:
    return _env_bool("RMS_PRICE_BAND_CHECK_ENABLED", True)


def _velocity_check_enabled() -> bool:
    return _env_bool("RMS_VELOCITY_CHECK_ENABLED", True)


def _velocity_max_orders() -> int:
    return _env_int("RMS_VELOCITY_MAX_ORDERS", 10)


def _velocity_window_seconds() -> float:
    return _env_float("RMS_VELOCITY_WINDOW_SECONDS", 60.0)


class RiskViolation(Exception):
    """Raised internally to short-circuit to a single rejection response."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.message = message
        self.code = code


def _check_quantity(order: dict[str, Any]) -> None:
    if not _quantity_check_enabled():
        return
    limit = _max_order_quantity()
    if limit <= 0:
        return  # 0 or negative = disabled, same convention as the other limits
    try:
        quantity = abs(int(float(order.get("quantity", 0))))
    except (TypeError, ValueError):
        return  # not this check's job to validate type -- schema layer already does
    if quantity > limit:
        raise RiskViolation(
            f"Order quantity {quantity} exceeds the configured maximum of {limit} "
            f"(RMS_MAX_ORDER_QUANTITY). Adjust the limit if this is expected, or split "
            f"the order.",
            "RMS_MAX_QUANTITY_EXCEEDED",
        )


def _check_order_value(order: dict[str, Any]) -> None:
    if not _value_check_enabled():
        return
    limit = _max_order_value()
    if limit <= 0:
        return
    try:
        quantity = abs(float(order.get("quantity", 0)))
        price = float(order.get("price", 0) or 0)
    except (TypeError, ValueError):
        return

    # MARKET/SL-M orders carry price=0 -- notional can only be estimated from
    # a live quote, not the (absent) order price. Best-effort only: if LTP is
    # unavailable this check is skipped for this order rather than blocking a
    # legitimate market order on a data-fetch failure (see module docstring on
    # fail-closed vs the narrower "we truly cannot evaluate this" case, which
    # intentionally allows through -- an availability gap is not a risk
    # violation, and behaves the same way #4 MPP already does on quote
    # fetch failure).
    if price <= 0:
        symbol = order.get("symbol")
        exchange = order.get("exchange")
        if not symbol or not exchange:
            return
        try:
            from services.market_data_service import get_ltp_value

            ltp = get_ltp_value(symbol, exchange)
        except Exception:
            logger.debug(f"risk_gate: LTP lookup failed for {symbol}/{exchange}, skipping value check")
            return
        if not ltp or ltp <= 0:
            return
        price = ltp

    notional = quantity * price
    if notional > limit:
        raise RiskViolation(
            f"Order value ₹{notional:,.2f} exceeds the configured maximum of "
            f"₹{limit:,.2f} (RMS_MAX_ORDER_VALUE). Adjust the limit if this is "
            f"expected, or reduce quantity.",
            "RMS_MAX_ORDER_VALUE_EXCEEDED",
        )


def _check_price_band(order: dict[str, Any]) -> None:
    """Reject a LIMIT/SL order whose price deviates more than the configured
    percentage from LTP -- a practical proxy for exchange circuit-band
    protection using data this platform already has (live LTP), since a
    uniform, always-current, per-symbol exchange circuit-percentage feed is
    not available to this platform today. Documented as a known
    approximation, not a claim of exact exchange circuit-filter parity."""
    if not _price_band_check_enabled():
        return
    band_pct = _price_band_pct()
    if band_pct <= 0:
        return

    pricetype = str(order.get("pricetype", "MARKET")).upper()
    if pricetype not in ("LIMIT", "SL"):
        return  # MARKET/SL-M carry no caller-supplied price to band-check

    try:
        price = float(order.get("price", 0) or 0)
    except (TypeError, ValueError):
        return
    if price <= 0:
        return

    symbol = order.get("symbol")
    exchange = order.get("exchange")
    if not symbol or not exchange:
        return

    try:
        from services.market_data_service import get_ltp_value

        ltp = get_ltp_value(symbol, exchange)
    except Exception:
        logger.debug(f"risk_gate: LTP lookup failed for {symbol}/{exchange}, skipping price-band check")
        return
    if not ltp or ltp <= 0:
        return  # no reference price available -- skip rather than block

    deviation_pct = abs(price - ltp) / ltp * 100
    if deviation_pct > band_pct:
        raise RiskViolation(
            f"Order price {price} deviates {deviation_pct:.1f}% from LTP {ltp}, "
            f"exceeding the configured band of {band_pct}% (RMS_PRICE_BAND_PCT).",
            "RMS_PRICE_BAND_EXCEEDED",
        )


# --- Velocity / runaway breaker ----------------------------------------------
# In-process, per-user sliding-window order counter. Single-worker Gunicorn/
# eventlet (see CLAUDE.md) makes an in-memory dict safe here, same reasoning
# as place_order_service.py's _recent_order_fingerprints dedup cache.
_velocity_lock = threading.Lock()
_order_timestamps: dict[str, list[float]] = {}


def _check_velocity(username: str | None) -> None:
    """Auto-activate the kill switch for `username` if they've placed more
    than RMS_VELOCITY_MAX_ORDERS orders within RMS_VELOCITY_WINDOW_SECONDS --
    the automated-execution/runaway-stoppage control (#5). Unlike the manual
    kill switch, this requires no human to notice and react."""
    if not _velocity_check_enabled() or not username:
        return
    max_orders = _velocity_max_orders()
    window = _velocity_window_seconds()
    if max_orders <= 0 or window <= 0:
        return

    now = time.monotonic()
    with _velocity_lock:
        timestamps = _order_timestamps.setdefault(username, [])
        timestamps[:] = [ts for ts in timestamps if now - ts <= window]
        timestamps.append(now)
        count = len(timestamps)

    if count > max_orders:
        logger.error(
            f"risk_gate: RUNAWAY DETECTED for user '{username}' -- {count} orders in "
            f"{window}s exceeds RMS_VELOCITY_MAX_ORDERS={max_orders}. Auto-activating "
            f"kill switch."
        )
        try:
            from database.settings_db import record_kill_switch_audit, set_kill_switch

            set_kill_switch(
                username,
                True,
                actor_type="system",
                actor_id="risk_gate.velocity_check",
                reason=(
                    f"Automatic halt: {count} orders placed within {window}s "
                    f"(limit {max_orders}) -- possible runaway/loop."
                ),
            )
            record_kill_switch_audit(
                username,
                event_type="auto_activate",
                actor_type="system",
                actor_id="risk_gate.velocity_check",
                reason=f"{count} orders in {window}s exceeded limit {max_orders}",
                notes="Automated runaway/loop breaker (Annexure 4 item 5)",
            )
        except Exception:
            # Must not let audit/flag-write failure suppress the rejection
            # below -- this order is blocked either way.
            logger.exception(
                f"risk_gate: failed to persist auto kill-switch activation for '{username}'"
            )
        raise RiskViolation(
            f"Automatic risk halt: more than {max_orders} orders placed within "
            f"{window} seconds. The kill switch has been activated for this account. "
            "Deactivate it manually once you've confirmed the strategy is not "
            "malfunctioning.",
            "RMS_VELOCITY_HALT",
        )


def check_pre_trade_risk(
    orders: list[dict[str, Any]] | None = None,
    username: str | None = None,
    context: str = "order",
) -> tuple[bool, dict[str, Any] | None, int]:
    """Run all enabled pre-trade RMS checks. Call once per order-placement
    request, passing every individual order it's about to submit (a basket
    with 5 legs passes all 5; a single order passes a 1-element list).

    Fails CLOSED on an unexpected internal error in a check (not on a
    resolvable data-availability gap, which each check already handles by
    skipping itself -- see the LTP-unavailable branches above). A bug in this
    module must never silently behave as "no violation found"; that would be
    worse than not having the check, on a document being shown to a
    compliance auditor as evidence this control exists and works.

    Returns:
        (allowed, error_response, status_code) -- same shape as
        order_gate.check_order_allowed, so callers add exactly one more
        `if not allowed: return ...` block identical to the existing one.
    """
    try:
        _check_velocity(username)

        for order in orders or []:
            _check_quantity(order)
            _check_order_value(order)
            _check_price_band(order)

        return True, None, 0

    except RiskViolation as v:
        logger.warning(f"risk_gate: blocked {context} for user '{username}': {v.message}")
        return (
            False,
            {"status": "error", "message": v.message, "code": v.code},
            403,
        )
    except Exception as e:
        # Fail CLOSED: an unexpected exception in a risk check must not be
        # allowed to look like "risk check passed". See docstring above.
        logger.exception(f"risk_gate: internal error evaluating {context} for user '{username}': {e}")
        return (
            False,
            {
                "status": "error",
                "message": "Risk check could not be completed; order blocked as a precaution.",
                "code": "RMS_CHECK_ERROR",
            },
            500,
        )
