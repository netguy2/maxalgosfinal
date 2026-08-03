"""
Regression test for: resolve_expiry_type() ignored instrument_type and
always queried options expiries (CE/PE/OPTFUT/...), even for a FUT leg.

Root cause: a futures-only underlying (e.g. MCX's GOLDPETAL, which has no
options chain) has real, live SymToken rows under FUTCOM, but zero rows
under OPTFUT/CE/PE. resolve_expiry_type() was hardcoded to
get_expiry_dates(..., instrumenttype="options"), so for such an underlying
the options query always returned an empty list regardless of what
expiry_type was requested, and the function returned None -- which every
caller (blueprints/strategy.py's Add Symbol validation, MaxHook's live
signal_engine.py order resolution) surfaced as "Could not resolve
'<expiry_type>' expiry for <underlying> on <exchange>. Check the underlying
symbol and exchange are correct." -- even though a live FUTCOM expiry
existed and the underlying/exchange were both correct.

Fix: resolve_expiry_type() now accepts instrument_type ("OPT", default, or
"FUT") and passes the matching get_expiry_dates() instrumenttype
("options"/"futures") through, so a FUT leg resolves against FUTCOM/FUTSTK/
FUT rows instead of CE/PE/OPTFUT rows. blueprints/strategy.py and
services/signal_engine.py now both thread their already-known
instrument_type through instead of always querying "options".

All DB/network calls are mocked -- this only tests that the right
get_expiry_dates() instrumenttype is requested and that resolution
succeeds against a futures-only expiry list.
"""

import atexit
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_expiry_resolution_instrument_type.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("APP_KEY", "test-app-key-" + "0" * 52)
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-" + "0" * 52)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

import restx_api  # noqa: F401,E402

from services.expiry_service import resolve_expiry_type  # noqa: E402


def test_futures_only_underlying_resolves_when_instrument_type_is_fut():
    """GOLDPETAL-on-MCX-shaped case: options query is empty, futures query
    has live expiries. instrument_type='FUT' must succeed."""

    def fake_get_expiry_dates(symbol, exchange, instrumenttype, api_key):
        if instrumenttype == "futures":
            return True, {"status": "success", "data": ["30-SEP-26"]}, 200
        return True, {"status": "success", "data": []}, 200

    with patch("services.expiry_service.get_expiry_dates", side_effect=fake_get_expiry_dates):
        result = resolve_expiry_type(
            "GOLDPETAL", "MCX", "current_month", "fake-api-key", instrument_type="FUT"
        )

    assert result == "30SEP26"


def test_futures_only_underlying_fails_without_instrument_type_fix():
    """Same data as above, but calling with the old default (OPT/options)
    must still fail -- this pins the actual bug behavior so a future
    regression that silently reverts the default is caught."""

    def fake_get_expiry_dates(symbol, exchange, instrumenttype, api_key):
        if instrumenttype == "futures":
            return True, {"status": "success", "data": ["30-SEP-26"]}, 200
        return True, {"status": "success", "data": []}, 200

    with patch("services.expiry_service.get_expiry_dates", side_effect=fake_get_expiry_dates):
        result = resolve_expiry_type("GOLDPETAL", "MCX", "current_month", "fake-api-key")

    assert result is None


def test_default_instrument_type_is_opt_unchanged_for_existing_callers():
    """Every pre-existing caller omits instrument_type -- confirm the
    default still queries 'options', preserving current behavior for
    NIFTY/BANKNIFTY-style underlyings that DO have options chains."""
    captured = {}

    def fake_get_expiry_dates(symbol, exchange, instrumenttype, api_key):
        captured["instrumenttype"] = instrumenttype
        return True, {"status": "success", "data": ["30-SEP-26"]}, 200

    with patch("services.expiry_service.get_expiry_dates", side_effect=fake_get_expiry_dates):
        resolve_expiry_type("NIFTY", "NFO", "current_month", "fake-api-key")

    assert captured["instrumenttype"] == "options"


def test_explicit_opt_instrument_type_queries_options():
    captured = {}

    def fake_get_expiry_dates(symbol, exchange, instrumenttype, api_key):
        captured["instrumenttype"] = instrumenttype
        return True, {"status": "success", "data": ["30-SEP-26"]}, 200

    with patch("services.expiry_service.get_expiry_dates", side_effect=fake_get_expiry_dates):
        resolve_expiry_type("NIFTY", "NFO", "current_month", "fake-api-key", instrument_type="OPT")

    assert captured["instrumenttype"] == "options"


def test_fut_instrument_type_queries_futures():
    captured = {}

    def fake_get_expiry_dates(symbol, exchange, instrumenttype, api_key):
        captured["instrumenttype"] = instrumenttype
        return True, {"status": "success", "data": ["30-SEP-26"]}, 200

    with patch("services.expiry_service.get_expiry_dates", side_effect=fake_get_expiry_dates):
        resolve_expiry_type("GOLDPETAL", "MCX", "current_month", "fake-api-key", instrument_type="FUT")

    assert captured["instrumenttype"] == "futures"
