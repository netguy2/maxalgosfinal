"""Unit tests for the pre-trade RMS gate (services/risk_gate.py).

Covers the SEBI/Exchange Annexure 4 pre-trade risk controls this module
implements: quantity ceiling, order-value ceiling, price-band/LTP-deviation
check, and the automated order-velocity runaway breaker. Each check's
enable/disable toggle and limit=0 "disabled" convention is also verified,
since these are meant to be operator-tunable, not fixed platform behavior.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import database.settings_db as settings_db  # noqa: E402
import services.risk_gate as risk_gate  # noqa: E402

USER_A = "__test_rms_user_a__"


def _purge(*usernames):
    for username in usernames:
        settings_db.db_session.query(settings_db.UserRiskSettings).filter_by(
            username=username
        ).delete()
    settings_db.db_session.commit()


@pytest.fixture(autouse=True)
def _clean_state():
    settings_db.clear_settings_cache()
    _purge(USER_A)
    risk_gate._order_timestamps.clear()
    settings_db.clear_settings_cache()

    yield

    settings_db.clear_settings_cache()
    _purge(USER_A)
    risk_gate._order_timestamps.clear()
    settings_db.clear_settings_cache()


def _env(**overrides):
    """Patch os.environ for the duration of a `with` block."""
    return patch.dict(os.environ, overrides)


# --- Quantity ceiling ---------------------------------------------------


def test_quantity_within_limit_allowed():
    with _env(RMS_MAX_ORDER_QUANTITY="10000"):
        allowed, error, status = risk_gate.check_pre_trade_risk(
            orders=[{"quantity": "500"}], username=USER_A
        )
    assert allowed is True
    assert error is None


def test_quantity_over_limit_blocked():
    with _env(RMS_MAX_ORDER_QUANTITY="1000"):
        allowed, error, status = risk_gate.check_pre_trade_risk(
            orders=[{"quantity": "5000"}], username=USER_A
        )
    assert allowed is False
    assert error["code"] == "RMS_MAX_QUANTITY_EXCEEDED"
    assert status == 403


def test_quantity_check_disabled_via_flag():
    with _env(RMS_MAX_ORDER_QUANTITY="1000", RMS_QUANTITY_CHECK_ENABLED="False"):
        allowed, error, _ = risk_gate.check_pre_trade_risk(
            orders=[{"quantity": "999999"}], username=USER_A
        )
    assert allowed is True


def test_quantity_check_disabled_via_zero_limit():
    with _env(RMS_MAX_ORDER_QUANTITY="0"):
        allowed, error, _ = risk_gate.check_pre_trade_risk(
            orders=[{"quantity": "999999"}], username=USER_A
        )
    assert allowed is True


# --- Order value ceiling ------------------------------------------------


def test_order_value_within_limit_allowed():
    with _env(RMS_MAX_ORDER_VALUE="10000000"):
        allowed, error, _ = risk_gate.check_pre_trade_risk(
            orders=[{"quantity": "10", "price": "100"}], username=USER_A
        )
    assert allowed is True


def test_order_value_over_limit_blocked():
    with _env(RMS_MAX_ORDER_VALUE="1000"):
        allowed, error, status = risk_gate.check_pre_trade_risk(
            orders=[{"quantity": "100", "price": "50"}], username=USER_A  # notional = 5000
        )
    assert allowed is False
    assert error["code"] == "RMS_MAX_ORDER_VALUE_EXCEEDED"
    assert status == 403


def test_order_value_market_order_with_no_price_falls_back_to_ltp():
    """price=0 (MARKET order) should attempt an LTP lookup, not silently
    skip the check -- but must not block if the lookup fails/is
    unavailable (fail-open on a genuine data gap, not the risk check
    itself -- see module docstring)."""
    with _env(RMS_MAX_ORDER_VALUE="1000"):
        with patch(
            "services.market_data_service.get_ltp_value", side_effect=Exception("no quote")
        ):
            allowed, error, _ = risk_gate.check_pre_trade_risk(
                orders=[{"quantity": "100", "price": "0", "symbol": "SBIN", "exchange": "NSE"}],
                username=USER_A,
            )
    assert allowed is True  # LTP unavailable -> skip, not block


def test_order_value_market_order_blocked_when_ltp_shows_large_notional():
    with _env(RMS_MAX_ORDER_VALUE="1000"):
        with patch("services.market_data_service.get_ltp_value", return_value=500.0):
            allowed, error, _ = risk_gate.check_pre_trade_risk(
                orders=[{"quantity": "100", "price": "0", "symbol": "SBIN", "exchange": "NSE"}],
                username=USER_A,
            )
    assert allowed is False
    assert error["code"] == "RMS_MAX_ORDER_VALUE_EXCEEDED"


# --- Price band ----------------------------------------------------------


def test_price_band_within_band_allowed():
    with _env(RMS_PRICE_BAND_PCT="10"):
        with patch("services.market_data_service.get_ltp_value", return_value=100.0):
            allowed, error, _ = risk_gate.check_pre_trade_risk(
                orders=[
                    {
                        "pricetype": "LIMIT",
                        "price": "105",
                        "symbol": "SBIN",
                        "exchange": "NSE",
                        "quantity": "1",
                    }
                ],
                username=USER_A,
            )
    assert allowed is True


def test_price_band_exceeded_blocked():
    with _env(RMS_PRICE_BAND_PCT="10"):
        with patch("services.market_data_service.get_ltp_value", return_value=100.0):
            allowed, error, status = risk_gate.check_pre_trade_risk(
                orders=[
                    {
                        "pricetype": "LIMIT",
                        "price": "150",  # 50% away from LTP 100
                        "symbol": "SBIN",
                        "exchange": "NSE",
                        "quantity": "1",
                    }
                ],
                username=USER_A,
            )
    assert allowed is False
    assert error["code"] == "RMS_PRICE_BAND_EXCEEDED"
    assert status == 403


def test_price_band_skipped_for_market_orders():
    """MARKET orders carry no caller price to band-check against LTP --
    this is MPP's job (utils/mpp_slab.py), not this check's."""
    with _env(RMS_PRICE_BAND_PCT="10"):
        with patch("services.market_data_service.get_ltp_value", return_value=100.0):
            allowed, error, _ = risk_gate.check_pre_trade_risk(
                orders=[{"pricetype": "MARKET", "price": "0", "symbol": "SBIN", "exchange": "NSE", "quantity": "1"}],
                username=USER_A,
            )
    assert allowed is True


def test_price_band_skipped_when_ltp_unavailable():
    with _env(RMS_PRICE_BAND_PCT="10"):
        with patch("services.market_data_service.get_ltp_value", return_value=None):
            allowed, error, _ = risk_gate.check_pre_trade_risk(
                orders=[
                    {
                        "pricetype": "LIMIT",
                        "price": "99999",
                        "symbol": "SBIN",
                        "exchange": "NSE",
                        "quantity": "1",
                    }
                ],
                username=USER_A,
            )
    assert allowed is True  # can't evaluate -> don't block


# --- Velocity / runaway breaker -----------------------------------------


def test_velocity_under_threshold_allowed():
    with _env(RMS_VELOCITY_MAX_ORDERS="10", RMS_VELOCITY_WINDOW_SECONDS="60"):
        for _ in range(5):
            allowed, error, _ = risk_gate.check_pre_trade_risk(orders=[], username=USER_A)
            assert allowed is True
    assert settings_db.is_kill_switch_active(USER_A) is False


def test_velocity_over_threshold_auto_activates_kill_switch():
    with _env(RMS_VELOCITY_MAX_ORDERS="3", RMS_VELOCITY_WINDOW_SECONDS="60"):
        results = [
            risk_gate.check_pre_trade_risk(orders=[], username=USER_A) for _ in range(5)
        ]
    # First 3 (at or under the limit) allowed, then blocked once the count
    # exceeds RMS_VELOCITY_MAX_ORDERS.
    assert results[0][0] is True
    assert results[1][0] is True
    assert results[2][0] is True
    assert results[3][0] is False
    assert results[3][1]["code"] == "RMS_VELOCITY_HALT"

    settings_db.clear_settings_cache()
    assert settings_db.is_kill_switch_active(USER_A) is True


def test_velocity_check_disabled_via_flag():
    with _env(RMS_VELOCITY_MAX_ORDERS="1", RMS_VELOCITY_CHECK_ENABLED="False"):
        for _ in range(10):
            allowed, error, _ = risk_gate.check_pre_trade_risk(orders=[], username=USER_A)
            assert allowed is True
    assert settings_db.is_kill_switch_active(USER_A) is False


def test_velocity_skipped_for_unresolvable_username():
    """No identity to attribute the order to -> nothing to rate-limit
    against, matching order_gate.py's existing fail-open convention for
    unattributable internal calls."""
    with _env(RMS_VELOCITY_MAX_ORDERS="1"):
        for _ in range(10):
            allowed, error, _ = risk_gate.check_pre_trade_risk(orders=[], username=None)
            assert allowed is True


# --- Multiple orders in one call (basket/split) -------------------------


def test_multiple_orders_each_checked_independently():
    with _env(RMS_MAX_ORDER_QUANTITY="1000"):
        allowed, error, _ = risk_gate.check_pre_trade_risk(
            orders=[{"quantity": "500"}, {"quantity": "5000"}],  # second leg breaches
            username=USER_A,
        )
    assert allowed is False
    assert error["code"] == "RMS_MAX_QUANTITY_EXCEEDED"


# --- Fail-closed on internal error --------------------------------------


def test_unexpected_internal_error_fails_closed():
    """A bug in a check must block the order, not silently pass it --
    this module's whole reason for existing is a compliance control, so
    an internal error must never look like 'no violation found'."""
    with patch.object(risk_gate, "_check_quantity", side_effect=RuntimeError("boom")):
        allowed, error, status = risk_gate.check_pre_trade_risk(
            orders=[{"quantity": "1"}], username=USER_A
        )
    assert allowed is False
    assert error["code"] == "RMS_CHECK_ERROR"
    assert status == 500
