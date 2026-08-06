"""Regression tests for the pre-flight order-instrument validation and
per-mapping failure circuit breaker in services/signal_engine.py.

Covers a real production incident: a StrategySymbolMapping with
instrument_type="EQ" pointed at "NIFTY" on "NSE_INDEX" (an index -- quote-
only, no order book) was sent straight to place_order() on every single
incoming webhook signal. The broker correctly rejected it every time
("Invalid Trading Symbol"), but only asynchronously (~1.2s after accepting
an order id), so nothing in this app ever stopped retrying -- the same
doomed order fired again on the next signal, forever, hammering both the
broker's API and the user with a repeating red rejection toast.

_validate_order_instrument() closes the gap that let the order reach the
broker at all. record_mapping_order_outcome()/deactivate_mapping() are the
counter + kill-switch that stop a mapping which somehow still fails
(a case validation can't catch, e.g. a genuinely delisted symbol) from
retrying forever once it has clearly demonstrated it cannot succeed.
"""

import os
import sys
import tempfile

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# A real ON-DISK sqlite file, not :memory: -- every DB module in this
# project uses NullPool (see CLAUDE.md's SQLite pooling section), which
# hands out a fresh connection per operation. An in-memory sqlite db is
# scoped to the connection that created it, so init_db()'s tables would
# vanish the instant that connection closed, before any test could use them.
_SCRATCH_DB = os.path.join(tempfile.gettempdir(), "maxalgos_test_order_instrument.db")
if os.path.exists(_SCRATCH_DB):
    os.remove(_SCRATCH_DB)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_SCRATCH_DB}")

import pytest

import services.signal_engine as se
from database.strategy_db import (
    Strategy,
    StrategySymbolMapping,
    db_session,
    deactivate_mapping,
    init_db,
    record_mapping_order_outcome,
)


@pytest.fixture(autouse=True)
def _db():
    init_db()
    yield
    # Tables persist across tests on the shared in-memory engine within one
    # process -- clear rows so each test starts from a known state.
    db_session.query(StrategySymbolMapping).delete()
    db_session.query(Strategy).delete()
    db_session.commit()


def _make_mapping(**overrides):
    strat = Strategy(name="My RSI Momentum", webhook_id=f"wh-{os.urandom(4).hex()}", user_id="u1")
    db_session.add(strat)
    db_session.commit()
    defaults = {
        "strategy_id": strat.id,
        "symbol": "BUY",
        "action": "BUY",
        "exchange": "NSE_INDEX",
        "quantity": 50,
        "product_type": "MIS",
        "instrument": "NIFTY",
        "instrument_type": "EQ",
    }
    defaults.update(overrides)
    mapping = StrategySymbolMapping(**defaults)
    db_session.add(mapping)
    db_session.commit()
    return strat, mapping


class TestValidateOrderInstrument:
    def test_rejects_index_exchange(self):
        # The exact incident: an equity-mapped index symbol.
        reason = se._validate_order_instrument("NIFTY", "NSE_INDEX")
        assert reason is not None
        assert "quote-only" in reason

    def test_rejects_bse_index_too(self):
        reason = se._validate_order_instrument("SENSEX", "BSE_INDEX")
        assert reason is not None
        assert "quote-only" in reason

    def test_rejects_global_index(self):
        reason = se._validate_order_instrument("US30", "GLOBAL_INDEX")
        assert reason is not None

    def test_rejects_empty_symbol(self):
        assert se._validate_order_instrument("", "NSE") is not None

    def test_rejects_empty_exchange(self):
        assert se._validate_order_instrument("RELIANCE", "") is not None

    def test_rejects_unknown_symbol_via_master_contract_lookup(self, monkeypatch):
        # A real tradable-type exchange but a symbol the master contract has
        # never heard of (typo, delisted, unsynced) -- caught via get_token,
        # not the quote-only-exchange shortcut.
        monkeypatch.setattr("database.token_db.get_token", lambda symbol, exchange: None)
        reason = se._validate_order_instrument("NOTAREALSYMBOL", "NSE")
        assert reason is not None
        assert "not found" in reason

    def test_accepts_a_real_known_symbol(self, monkeypatch):
        monkeypatch.setattr("database.token_db.get_token", lambda symbol, exchange: "12345")
        assert se._validate_order_instrument("RELIANCE", "NSE") is None


class TestMappingFailureCircuitBreaker:
    def test_counter_increments_on_failure(self):
        _, mapping = _make_mapping()
        assert mapping.consecutive_failures == 0

        for expected in (1, 2, 3):
            count = record_mapping_order_outcome(mapping.id, succeeded=False)
            assert count == expected

    def test_counter_resets_on_success(self):
        _, mapping = _make_mapping()
        record_mapping_order_outcome(mapping.id, succeeded=False)
        record_mapping_order_outcome(mapping.id, succeeded=False)
        assert record_mapping_order_outcome(mapping.id, succeeded=True) == 0

    def test_deactivate_mapping_flips_is_active_false(self):
        _, mapping = _make_mapping()
        assert mapping.is_active is True
        assert deactivate_mapping(mapping.id) is True

        refreshed = db_session.get(StrategySymbolMapping, mapping.id)
        assert refreshed.is_active is False

    def test_deactivate_unknown_mapping_returns_false(self):
        assert deactivate_mapping(999999) is False

    def test_circuit_breaker_trips_at_threshold_and_stays_off_below_it(self, monkeypatch):
        """End-to-end: _record_mapping_outcome_and_maybe_disable must not
        deactivate the mapping before MAPPING_FAILURE_CIRCUIT_BREAKER_THRESHOLD
        consecutive failures, and must deactivate it exactly at that point --
        this is the actual mechanism that stops the reported infinite retry."""
        strat, mapping = _make_mapping()
        activities = []
        monkeypatch.setattr(
            "database.auth_db.record_activity",
            lambda username, category, title, message: activities.append(
                (username, title, message)
            ),
        )
        emitted = []
        monkeypatch.setattr(
            se, "_emit_scoped", lambda event, payload, user_id: emitted.append(payload)
        )

        threshold = se.MAPPING_FAILURE_CIRCUIT_BREAKER_THRESHOLD
        for i in range(1, threshold):
            se._record_mapping_outcome_and_maybe_disable(
                mapping, strat, False, "Invalid Trading Symbol"
            )
            refreshed = db_session.get(StrategySymbolMapping, mapping.id)
            assert refreshed.is_active is True, f"tripped too early at failure #{i}"

        se._record_mapping_outcome_and_maybe_disable(
            mapping, strat, False, "Invalid Trading Symbol"
        )
        refreshed = db_session.get(StrategySymbolMapping, mapping.id)
        assert refreshed.is_active is False, "circuit breaker did not trip at threshold"
        assert len(activities) == 1
        assert "Auto-Disabled" in activities[0][1]
        assert len(emitted) == 1

    def test_a_success_in_the_middle_prevents_the_trip(self, monkeypatch):
        """A mapping that fails, then succeeds, then fails again should never
        reach the threshold from the first failure streak alone -- confirms
        the breaker tracks CONSECUTIVE failures, not a lifetime total."""
        strat, mapping = _make_mapping()
        monkeypatch.setattr("database.auth_db.record_activity", lambda *a, **k: None)
        monkeypatch.setattr(se, "_emit_scoped", lambda *a, **k: None)

        threshold = se.MAPPING_FAILURE_CIRCUIT_BREAKER_THRESHOLD
        for _ in range(threshold - 1):
            se._record_mapping_outcome_and_maybe_disable(mapping, strat, False, "x")
        se._record_mapping_outcome_and_maybe_disable(
            mapping, strat, True, None
        )  # breaks the streak

        refreshed = db_session.get(StrategySymbolMapping, mapping.id)
        assert refreshed.consecutive_failures == 0
        assert refreshed.is_active is True
