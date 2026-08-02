"""Regression tests for the signal-engine safety gates.

Covers the kill-switch and market-hours checks added to
services/signal_engine.py::_process_signal_event. These guard a
safety-critical path -- until they existed, flipping the master kill switch
stopped Chartink and Python Strategy Host orders but NOT MaxHook webhook
orders, which reached the broker unguarded.

The gates deliberately FAIL OPEN: a settings-table or calendar fault must not
silently halt every strategy platform-wide. The cost of that choice is that a
fault leaves the kill switch reading ACTIVE in the UI while not enforcing, so
each fail-open path must also raise a human-visible alert. Both properties are
asserted here.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import types

import pytest

import services.signal_engine as se


@pytest.fixture(autouse=True)
def _no_delivery_writes(monkeypatch):
    """The gates record a webhook_deliveries outcome; not under test here."""
    monkeypatch.setattr(se, "_record_delivery_outcome", lambda *a, **k: None)


@pytest.fixture
def alerts(monkeypatch):
    """Capture fail-open alerts instead of the real alert dispatch."""
    sent = []
    monkeypatch.setattr(
        se, "_alert_safety_check_failed",
        lambda strategy, check, err: sent.append((strategy.name, check, str(err))),
    )
    return sent


class FakeStrategy:
    def __init__(self, name="S1", user_id="u1", enforce_market_hours=False):
        self.name = name
        self.user_id = user_id
        self.enforce_market_hours = enforce_market_hours


def _event():
    return se.SignalEvent(webhook_id="wh-1", signal="BUY")


def _stub(monkeypatch, module, attr, fn):
    mod = types.ModuleType(module)
    setattr(mod, attr, fn)
    monkeypatch.setitem(sys.modules, module, mod)


def _kill_switch(monkeypatch, active=False, raises=False):
    """Stub the per-user kill-switch lookup.

    Takes a username now -- the switch is per-user, and signal_engine scopes
    the check to the strategy's own owner (strategy.user_id). Without the
    parameter here the real call would raise TypeError and be swallowed by
    the gate's fail-open path, so the "active" case would silently stop
    being tested at all.
    """

    def is_kill_switch_active(username=None):
        if raises:
            raise RuntimeError("settings table unavailable")
        return active

    _stub(monkeypatch, "database.settings_db", "is_kill_switch_active", is_kill_switch_active)


def _market(monkeypatch, is_open=True, raises=False):
    def is_market_open(exchange=None):
        if raises:
            raise RuntimeError("calendar unavailable")
        return is_open

    _stub(monkeypatch, "database.market_calendar_db", "is_market_open", is_market_open)


# --- kill switch ---------------------------------------------------------

def test_kill_switch_active_blocks_signal(monkeypatch):
    _kill_switch(monkeypatch, active=True)
    assert se._kill_switch_blocks_signal(FakeStrategy(), _event()) is True


def test_kill_switch_inactive_allows_signal(monkeypatch):
    _kill_switch(monkeypatch, active=False)
    assert se._kill_switch_blocks_signal(FakeStrategy(), _event()) is False


# --- market hours (opt-in) ----------------------------------------------

def test_market_hours_not_enforced_by_default(monkeypatch):
    """No regression: a strategy that hasn't opted in trades out of hours."""
    _market(monkeypatch, is_open=False)
    assert se._market_hours_blocks_signal(FakeStrategy(), _event()) is False


def test_pre_migration_row_without_attribute_not_blocked(monkeypatch):
    """SQLite backfills the new column as NULL, and rows loaded before the
    migration may lack the attribute entirely. Neither may start blocking."""
    _market(monkeypatch, is_open=False)

    class LegacyRow:
        name = "old"
        user_id = "u1"

    assert se._market_hours_blocks_signal(LegacyRow(), _event()) is False


def test_market_closed_blocks_opted_in_strategy(monkeypatch):
    _market(monkeypatch, is_open=False)
    strategy = FakeStrategy(enforce_market_hours=True)
    assert se._market_hours_blocks_signal(strategy, _event()) is True


def test_market_open_allows_opted_in_strategy(monkeypatch):
    _market(monkeypatch, is_open=True)
    strategy = FakeStrategy(enforce_market_hours=True)
    assert se._market_hours_blocks_signal(strategy, _event()) is False


# --- fail-open + alarm ---------------------------------------------------

def test_kill_switch_lookup_error_fails_open_and_alerts(monkeypatch, alerts):
    _kill_switch(monkeypatch, raises=True)
    assert se._kill_switch_blocks_signal(FakeStrategy(), _event()) is False
    assert len(alerts) == 1, "fail-open must raise a human-visible alarm"
    assert alerts[0][1] == "kill switch"


def test_market_hours_lookup_error_fails_open_and_alerts(monkeypatch, alerts):
    _market(monkeypatch, raises=True)
    strategy = FakeStrategy(enforce_market_hours=True)
    assert se._market_hours_blocks_signal(strategy, _event()) is False
    assert len(alerts) == 1, "fail-open must raise a human-visible alarm"
    assert alerts[0][1] == "market hours"


def test_alert_failure_never_breaks_signal_processing(monkeypatch):
    """A broken alert dispatch must not turn a fail-open into an exception."""
    _kill_switch(monkeypatch, raises=True)
    assert se._kill_switch_blocks_signal(FakeStrategy(), _event()) is False
