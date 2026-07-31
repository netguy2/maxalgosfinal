"""
Regression tests for: resolve_expiry_type("current_month"/"next_month")
must not return None once the current calendar month's monthly contract
has already expired intraday.

Root cause: NSE's monthly options expiry falls on the last Tuesday of the
month, not the last calendar day. get_expiry_dates() correctly drops
expired contracts from the live list (by design). But
resolve_expiry_type()'s current_month/next_month branches searched for an
expiry literally stamped with today's calendar month/year -- once that
contract lapsed (e.g. expiry was 28-JUL and today is 31-JUL), no row in
the still-live list matches month==7, so the function returned None and
every caller (blueprints/strategy.py config validation, MaxHook's
signal_engine.py live order resolution, flow_executor_service.py options
nodes) either rejected a new config with "Could not resolve 'current_month'
expiry" or silently failed to resolve a live tradable contract for an
already-configured strategy on every webhook signal, with no order placed
and no visible error to the end user.

Fix: fall back to the nearest still-live expiry (current_month) / the one
after that (next_month) when the exact calendar-month match is gone.

All DB/network calls are mocked -- this only tests date-selection logic.
"""

import atexit
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_expiry_rollover.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("APP_KEY", "test-app-key-" + "0" * 52)
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-" + "0" * 52)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

import restx_api  # noqa: F401,E402

from services.expiry_service import resolve_expiry_type  # noqa: E402


def _fake_now(year, month, day):
    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(year, month, day)

    return _FakeDatetime


class TestCurrentMonthRollover:
    def test_falls_back_to_nearest_expiry_when_current_month_contract_expired(self):
        """Today is 31-JUL. NIFTY's monthly expiry (28-JUL) already lapsed
        and was correctly dropped from the live list by get_expiry_dates().
        Only a weekly (04-AUG) and next month's monthly (25-AUG) remain.
        current_month must resolve to the nearest live expiry (04-AUG),
        not None."""
        fake_response = (
            True,
            {"status": "success", "data": ["04-AUG-26", "25-AUG-26"]},
            200,
        )
        with patch("services.expiry_service.get_expiry_dates", return_value=fake_response), \
             patch("services.expiry_service.datetime", _fake_now(2026, 7, 31)):
            result = resolve_expiry_type("NIFTY", "NFO", "current_month", "fake-api-key")

        assert result == "04AUG26"

    def test_current_month_matches_exact_month_when_still_live(self):
        """Today is 10-JUL and the monthly expiry (28-JUL) hasn't happened
        yet -- current_month should resolve to it directly, unaffected by
        the fallback."""
        fake_response = (
            True,
            {"status": "success", "data": ["17-JUL-26", "28-JUL-26", "25-AUG-26"]},
            200,
        )
        with patch("services.expiry_service.get_expiry_dates", return_value=fake_response), \
             patch("services.expiry_service.datetime", _fake_now(2026, 7, 10)):
            result = resolve_expiry_type("NIFTY", "NFO", "current_month", "fake-api-key")

        assert result == "28JUL26"

    def test_next_month_rolls_forward_when_septembers_contract_also_already_lapsed(self):
        """Today is 30-SEP and September's own monthly contract already
        lapsed (last Tuesday, e.g. 24-SEP) -- the nominal 'next month'
        (OCT) has no direct match either since only NOV remains live in
        this fixture; next_month must roll forward to NOV instead of
        returning None."""
        fake_response = (
            True,
            {"status": "success", "data": ["30-SEP-26", "26-NOV-26"]},
            200,
        )
        with patch("services.expiry_service.get_expiry_dates", return_value=fake_response), \
             patch("services.expiry_service.datetime", _fake_now(2026, 9, 30)):
            result = resolve_expiry_type("NIFTY", "NFO", "next_month", "fake-api-key")

        assert result == "26NOV26"

    def test_next_month_matches_exact_month_when_still_live(self):
        fake_response = (
            True,
            {"status": "success", "data": ["17-JUL-26", "28-JUL-26", "25-AUG-26"]},
            200,
        )
        with patch("services.expiry_service.get_expiry_dates", return_value=fake_response), \
             patch("services.expiry_service.datetime", _fake_now(2026, 7, 10)):
            result = resolve_expiry_type("NIFTY", "NFO", "next_month", "fake-api-key")

        assert result == "25AUG26"

    def test_returns_none_when_no_expiries_at_all(self):
        fake_response = (True, {"status": "success", "data": []}, 200)
        with patch("services.expiry_service.get_expiry_dates", return_value=fake_response):
            result = resolve_expiry_type("NIFTY", "NFO", "current_month", "fake-api-key")

        assert result is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
