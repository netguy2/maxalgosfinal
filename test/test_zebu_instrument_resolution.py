"""Regression tests for Zebu instrument-token resolution.

The bug: placing a MARKET order on an index (e.g. NIFTY) was rejected with

    Order REJECTED for NIFTY: Unable to fetch live market price for NIFTY to
    place MARKET order (Zebu requires MARKET orders to be converted to LIMIT
    with a real price via Market Price Protection): Error from Zebu API:
    Invalid Input : One or more input parameters are not in string format

Chain of causation:
  * indices live under the *_INDEX exchanges (NIFTY is at NSE_INDEX), but an
    index order arrives from the strategy engine as symbol=NIFTY exchange=NSE;
  * get_token("NIFTY", "NSE") therefore returned None;
  * None serialized into the Noren JSON payload as `null`, a non-string, so
    Zebu rejected the request with its "not in string format" error;
  * Zebu requires MARKET -> LIMIT conversion via Market Price Protection, and
    MPP cannot price an order without a quote, so the order was rejected.

resolve_zebu_instrument fixes the root: fall back to the index segment, and
guarantee every payload value is a string.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import broker.zebu.api.data as zebu_data  # noqa: E402

resolve = zebu_data.resolve_zebu_instrument


@pytest.fixture
def fake_tokens(monkeypatch):
    """Model the real table: indices exist ONLY under *_INDEX."""
    table = {
        ("NIFTY", "NSE_INDEX"): "26000",
        ("BANKNIFTY", "NSE_INDEX"): "26009",
        ("SENSEX", "BSE_INDEX"): "1",
        ("SBIN", "NSE"): "3045",
        ("NIFTY28JUL2623950CE", "NFO"): "63937",
    }
    monkeypatch.setattr(zebu_data, "get_token", lambda s, e: table.get((s, e)))
    return table


# ---------------------------------------------------------------------
# The reported failure
# ---------------------------------------------------------------------


def test_index_on_plain_exchange_resolves(fake_tokens):
    """THE regression: NIFTY/NSE previously yielded token=None."""
    token, api_exchange = resolve("NIFTY", "NSE")
    assert token == "26000"
    assert api_exchange == "NSE"


@pytest.mark.parametrize(
    "symbol,exchange,expected",
    [
        ("NIFTY", "NSE", "26000"),
        ("BANKNIFTY", "NSE", "26009"),
        ("SENSEX", "BSE", "1"),
    ],
)
def test_every_index_resolves_from_plain_exchange(fake_tokens, symbol, exchange, expected):
    token, _ = resolve(symbol, exchange)
    assert token == expected


def test_payload_values_are_all_strings(fake_tokens):
    """Zebu rejects ANY non-string JSON value -- that is the literal text of
    the error this bug produced."""
    import json

    token, api_exchange = resolve("NIFTY", "NSE")
    payload = {"exch": api_exchange, "token": token}

    assert all(isinstance(v, str) for v in payload.values())
    assert "null" not in json.dumps(payload)


# ---------------------------------------------------------------------
# Existing behaviour must not change
# ---------------------------------------------------------------------


def test_explicit_index_exchange_still_works(fake_tokens):
    """Callers already passing NSE_INDEX keep working, and the exchange is
    still translated to what Zebu expects."""
    token, api_exchange = resolve("NIFTY", "NSE_INDEX")
    assert token == "26000"
    assert api_exchange == "NSE"


def test_bse_index_maps_to_bse(fake_tokens):
    _token, api_exchange = resolve("SENSEX", "BSE_INDEX")
    assert api_exchange == "BSE"


def test_equity_is_unaffected(fake_tokens):
    """A normal equity resolves on its own exchange with no fallback."""
    token, api_exchange = resolve("SBIN", "NSE")
    assert token == "3045"
    assert api_exchange == "NSE"


def test_option_contract_is_unaffected(fake_tokens):
    token, api_exchange = resolve("NIFTY28JUL2623950CE", "NFO")
    assert token == "63937"
    assert api_exchange == "NFO"


# ---------------------------------------------------------------------
# Failure mode
# ---------------------------------------------------------------------


def test_unknown_symbol_raises_a_useful_error(fake_tokens):
    """Must name the real problem rather than letting a None token reach
    Zebu and come back as its opaque format error."""
    with pytest.raises(ValueError, match="No instrument token found"):
        resolve("NOTAREALSYMBOL", "NSE")


def test_no_index_fallback_for_derivative_segments(fake_tokens):
    """NFO/MCX have no *_INDEX variant -- don't invent one, just fail."""
    with pytest.raises(ValueError, match="No instrument token found"):
        resolve("NIFTY", "NFO")


def test_numeric_token_is_coerced_to_string(monkeypatch):
    """Defensive: even if a lookup ever returns an int, it must not reach
    the payload as one."""
    monkeypatch.setattr(zebu_data, "get_token", lambda s, e: 26000)
    token, _ = resolve("NIFTY", "NSE")
    assert token == "26000"
    assert isinstance(token, str)
