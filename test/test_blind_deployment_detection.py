"""Regression test: a deployment whose symbol doesn't exist must not run blind.

Production case: a "VWAP Reversion" deployment was configured for ZOMATO on
NSE. Zomato Ltd had been renamed ETERNAL on NSE, so the symbol no longer
existed in the master contract. Every indicator's history fetch failed with
"Symbol 'ZOMATO' not found for exchange 'NSE'", and every failure path in
_fetch_broker_ohlcv_range returns None, which indicators convert to 0.0.

The result was a deployment that looked completely healthy -- status
"Waiting", heartbeat "Healthy", health 100%, Active Workers 5 -- with a
trigger timeline reporting, every two minutes for hours:

    Checked conditions on ZOMATO (NSE): not yet met --
    VWAP_DEVIATION_BELOW (0.0) > 0.5

That is byte-identical to a healthy strategy patiently waiting for a setup.
Nothing anywhere distinguished "no signal yet" from "I cannot see the market
at all", so the strategy could sit blind indefinitely while its owner
believed it was armed and working.

Symbol existence was only ever validated at ORDER time
(_resolve_tradeable_symbol), which never runs when conditions can never
match -- so the one check that would have caught it was unreachable by
construction.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault(
    "DATABASE_URL", "sqlite:///" + os.path.join(tempfile.gettempdir(), "blind_dep_test.db")
)

import pytest  # noqa: E402

import database.token_db as token_db  # noqa: E402
import services.deployment_service as dsvc  # noqa: E402


class FakeDeployment:
    id = 1
    name = "My VWAP Reversion (Active)"
    user_id = "u1"


@pytest.fixture
def statuses(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        dsvc, "update_deployment_status", lambda i, s, m=None: recorded.append((s, m))
    )
    return recorded


class TestUnresolvableSymbolIsQuarantined:
    def test_missing_symbol_stops_the_deployment(self, monkeypatch, statuses):
        """THE regression test: ZOMATO no longer exists, so this deployment
        must be stopped rather than left evaluating blind forever."""
        monkeypatch.setattr(token_db, "get_token", lambda s, e: None)

        assert dsvc._symbol_exists_for_evaluation(FakeDeployment(), "ZOMATO", "NSE") is False
        assert statuses and statuses[-1][0] == "Error"

    def test_error_message_is_actionable(self, monkeypatch, statuses):
        """The user must learn WHY, not just that it stopped -- a rename is
        invisible otherwise."""
        monkeypatch.setattr(token_db, "get_token", lambda s, e: None)
        dsvc._symbol_exists_for_evaluation(FakeDeployment(), "ZOMATO", "NSE")

        msg = statuses[-1][1]
        assert "ZOMATO" in msg and "NSE" in msg
        assert "renamed or delisted" in msg
        assert "ETERNAL" in msg, "should name the concrete real-world example"


class TestWorkingDeploymentsAreUntouched:
    def test_valid_symbol_passes(self, monkeypatch, statuses):
        monkeypatch.setattr(token_db, "get_token", lambda s, e: "12345")
        assert dsvc._symbol_exists_for_evaluation(FakeDeployment(), "ETERNAL", "NSE") is True
        assert statuses == []

    @pytest.mark.parametrize(
        "exchange", ["NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX"]
    )
    def test_bare_index_is_exempt(self, monkeypatch, statuses, exchange):
        """Indices are not ordinary instruments; _resolve_tradeable_symbol
        maps them to a tradable future at order time. Quarantining them
        would break every index strategy on the platform."""
        monkeypatch.setattr(token_db, "get_token", lambda s, e: None)
        assert dsvc._symbol_exists_for_evaluation(FakeDeployment(), "NIFTY", exchange) is True
        assert statuses == []

    def test_lookup_failure_fails_open(self, monkeypatch, statuses):
        """A transient master-contract/DB fault must NOT mass-quarantine
        every deployment. Cost of a missed detection is one more cycle of
        the status quo; cost of a false positive is stopping strategies
        that were working fine."""

        def boom(s, e):
            raise RuntimeError("master contract DB unavailable")

        monkeypatch.setattr(token_db, "get_token", boom)

        assert dsvc._symbol_exists_for_evaluation(FakeDeployment(), "ETERNAL", "NSE") is True
        assert statuses == [], "must not quarantine on a faulty check"
