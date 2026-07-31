"""Regression tests for deployment order-exchange resolution.

The bug: a wizard-created deployment on NIFTY rejected every order with

    Order REJECTED for NIFTY [My CPR Breakout (Active)]: Unable to fetch live
    market price for NIFTY to place MARKET order ... Error fetching quotes:
    No instrument token found for NIFTY on NFO.

services/deployment_service.py falls back to (symbol="NIFTY",
exchange="NFO") when a config carries no explicit instrument. That pair is
impossible: NFO lists only dated F&O contracts (NIFTY28JUL2623950CE), never
the bare underlying, so the token lookup could never succeed. The order then
died at the broker -- and on Zebu it surfaced as a Market Price Protection
failure, because MPP must convert MARKET -> LIMIT and cannot price an order
it has no quote for.

_to_order_exchange resolves the exchange a symbol is genuinely tradable on,
while leaving real derivative contracts alone.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from services.deployment_service import _to_order_exchange  # noqa: E402

# ---------------------------------------------------------------------
# The reported failure
# ---------------------------------------------------------------------


def test_bare_nifty_on_nfo_is_redirected():
    """THE regression: NIFTY/NFO has no token and always rejected."""
    assert _to_order_exchange("NIFTY", "NFO") == "NSE_INDEX"


@pytest.mark.parametrize("symbol", ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])
def test_every_nse_index_redirects_to_index_segment(symbol):
    assert _to_order_exchange(symbol, "NFO") == "NSE_INDEX"


@pytest.mark.parametrize("symbol", ["SENSEX", "BANKEX"])
def test_bse_indices_redirect_to_bse_index(symbol):
    assert _to_order_exchange(symbol, "BFO") == "BSE_INDEX"


def test_bare_stock_on_nfo_routes_to_cash():
    """A bare equity symbol on the derivatives segment means the underlying,
    which trades on the cash segment."""
    assert _to_order_exchange("SBIN", "NFO") == "NSE"


# ---------------------------------------------------------------------
# Real derivatives must NOT be touched
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "symbol",
    [
        "NIFTY28JUL2623950CE",
        "NIFTY28JUL2623950PE",
        "BANKNIFTY28JUL26FUT",
        "SBIN28JUL26800CE",
    ],
)
def test_real_contracts_keep_their_derivatives_exchange(symbol):
    """These DO exist on NFO -- redirecting them would break working orders,
    which is the failure mode that matters most here."""
    assert _to_order_exchange(symbol, "NFO") == "NFO"


def test_bfo_contract_keeps_bfo():
    assert _to_order_exchange("SENSEX29JUL2680000CE", "BFO") == "BFO"


# ---------------------------------------------------------------------
# Everything else passes through unchanged
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "symbol,exchange",
    [
        ("SBIN", "NSE"),
        ("NIFTY", "NSE_INDEX"),
        ("SENSEX", "BSE_INDEX"),
        ("RELIANCE", "BSE"),
        ("CRUDEOIL", "MCX"),
    ],
)
def test_non_derivative_exchanges_are_untouched(symbol, exchange):
    assert _to_order_exchange(symbol, exchange) == exchange


def test_handles_missing_values_without_raising():
    """Called on every order-placement cycle -- must never be the thing that
    crashes the engine loop."""
    assert _to_order_exchange("", "") == ""
    assert _to_order_exchange(None, None) is None
    assert _to_order_exchange("NIFTY", None) is None


def test_is_case_insensitive():
    assert _to_order_exchange("nifty", "nfo") == "NSE_INDEX"
