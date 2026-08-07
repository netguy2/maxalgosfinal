"""Regression test for a real production incident: webhook strategies in a
Draft/Archived lifecycle state placed REAL broker orders.

services/signal_engine.py::_process_signal_event had exactly ONE gate
between an incoming webhook signal and a live order -- `strategy.is_active`.
There was no `lifecycle_state` check anywhere in the file (grep count: 0),
so a strategy still sitting in "Draft" (created but never reviewed, never
assigned a broker/capital, possibly never authored by a human at all) fired
live orders the moment any signal arrived.

How that shipped: blueprints/strategy.py::_init_mock_marketplace_listings
seeds storefront template strategies on every startup where the listings
table is empty. They were created `is_active=True, lifecycle_state="Ready"`
and owned by a synthetic "MaxAlgosSystem" user -- nobody's real account.
Because they are `platform="webhook"`, they appear in NONE of the UI views
users check for running strategies (Python Studio, Live Deployments, Flow
all showed "Stopped"/"Inactive"/"No deployments"), so there was no way to
see them, let alone stop them. They were seeded against NIFTY/NSE_INDEX --
a quote-only exchange with no order book -- so every attempt reached the
broker and came back "Invalid Trading Symbol", repeatedly, on multiple
users' accounts simultaneously.

Two fixes are pinned here:
  1. The lifecycle gate itself (this file's main subject).
  2. The seeded storefront templates are now inert (is_active=False,
     lifecycle_state="Draft") so they cannot execute even if the gate
     were ever loosened.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Deliberately NOT "sqlite:///:memory:" -- database/master_contract_status_db.py
# does os.makedirs(os.path.dirname(url.replace("sqlite:///", ""))) at import
# time, and ":memory:" has an empty dirname, which raises FileNotFoundError
# on Windows. Because os.environ leaks across test modules in one pytest
# run, setting :memory: here broke unrelated modules collected afterwards.
# A real on-disk temp path is also required by this project's NullPool
# convention (see CLAUDE.md) -- in-memory DBs lose their tables the moment
# the creating connection closes.
if not os.environ.get("DATABASE_URL"):
    import tempfile

    os.environ["DATABASE_URL"] = (
        "sqlite:///" + os.path.join(tempfile.gettempdir(), "maxalgos_lifecycle_gate_test.db")
    )

import pytest  # noqa: E402

import services.signal_engine as se  # noqa: E402


class FakeStrategy:
    def __init__(self, name="S1", user_id="u1", is_active=True, lifecycle_state="Ready"):
        self.name = name
        self.user_id = user_id
        self.is_active = is_active
        self.lifecycle_state = lifecycle_state
        self.enforce_market_hours = False


@pytest.fixture
def outcomes(monkeypatch):
    """Capture the delivery outcome the gate records instead of writing it."""
    recorded = []

    def _record(event, kind, status, reason_code=None, reason_detail=None, **kw):
        recorded.append({"status": status, "reason_code": reason_code})

    monkeypatch.setattr(se, "_record_delivery_outcome", _record)
    return recorded


def _run_gate(monkeypatch, strategy, outcomes):
    """Drive _process_signal_event just far enough to exercise the
    is_active / lifecycle_state gates, then hard-stop so the test never
    reaches real order placement.

    A sentinel raised from the kill-switch check (the very next gate)
    proves execution got PAST the lifecycle gate; no sentinel means the
    lifecycle gate returned early and blocked the signal.
    """

    monkeypatch.setattr(se, "get_strategy_by_webhook_id", lambda wid: strategy)

    # _process_signal_event wraps its body in a broad try/except, so a
    # sentinel exception can't escape. Use a flag instead: the kill-switch
    # check is the very next gate after the lifecycle gate, so it being
    # reached proves the lifecycle gate let the signal through. Returning
    # True from it also stops processing before any real order path.
    reached = {"value": False}

    def _mark_reached(*a, **k):
        reached["value"] = True
        return True  # block here, so nothing downstream executes

    monkeypatch.setattr(se, "_kill_switch_blocks_signal", _mark_reached)

    event = se.SignalEvent(webhook_id="wh-1", signal="BUY")
    se._process_signal_event(event)
    return reached["value"]


class TestLifecycleGateBlocksNonTradableStates:
    def test_draft_strategy_is_blocked(self, monkeypatch, outcomes):
        """THE regression test: a Draft strategy must never place orders."""
        proceeded = _run_gate(monkeypatch, FakeStrategy(lifecycle_state="Draft"), outcomes)

        assert proceeded is False, (
            "A strategy in Draft placed an order -- this is the exact bug that "
            "fired live NIFTY orders from unreviewed, auto-seeded strategies."
        )
        assert any(o["reason_code"] == "strategy_not_live" for o in outcomes)

    def test_archived_strategy_is_blocked(self, monkeypatch, outcomes):
        proceeded = _run_gate(monkeypatch, FakeStrategy(lifecycle_state="Archived"), outcomes)

        assert proceeded is False
        assert any(o["reason_code"] == "strategy_not_live" for o in outcomes)

    def test_inactive_strategy_still_blocked_first(self, monkeypatch, outcomes):
        """The pre-existing is_active gate must keep working unchanged."""
        proceeded = _run_gate(
            monkeypatch, FakeStrategy(is_active=False, lifecycle_state="Ready"), outcomes
        )

        assert proceeded is False
        assert any(o["reason_code"] == "strategy_inactive" for o in outcomes)


class TestLifecycleGateDoesNotBreakWorkingStrategies:
    """The gate must NOT be an allowlist of {"Live"}: nothing in this
    codebase ever promotes a strategy to "Live" (the column is only ever
    set to Draft/Ready/Archived), so requiring it would silently kill every
    working strategy on the platform."""

    def test_ready_strategy_proceeds(self, monkeypatch, outcomes):
        assert _run_gate(monkeypatch, FakeStrategy(lifecycle_state="Ready"), outcomes) is True

    def test_live_strategy_proceeds(self, monkeypatch, outcomes):
        assert _run_gate(monkeypatch, FakeStrategy(lifecycle_state="Live"), outcomes) is True

    def test_paper_strategy_proceeds(self, monkeypatch, outcomes):
        assert _run_gate(monkeypatch, FakeStrategy(lifecycle_state="Paper"), outcomes) is True

    def test_legacy_row_with_null_lifecycle_proceeds(self, monkeypatch, outcomes):
        """Pre-migration rows backfill lifecycle_state as NULL. Those must
        keep trading, not silently stop."""
        assert _run_gate(monkeypatch, FakeStrategy(lifecycle_state=None), outcomes) is True

    def test_row_missing_lifecycle_attribute_entirely_proceeds(self, monkeypatch, outcomes):
        """Rows loaded before the lifecycle_state column existed may not
        carry the attribute at all. The gate must use getattr and let them
        through -- reading it directly raised AttributeError and crashed
        the whole signal path (caught in review by an existing webhook
        test whose fake strategy has no such attribute)."""

        class LegacyRow:
            name = "old"
            user_id = "u1"
            is_active = True
            enforce_market_hours = False

        assert _run_gate(monkeypatch, LegacyRow(), outcomes) is True


class TestSeededMarketplaceTemplatesAreInert:
    """The synthetic MaxAlgosSystem storefront templates must never be
    executable, independent of the gate above."""

    def test_seed_creates_inactive_draft_strategies(self):
        import inspect as _inspect

        import blueprints.strategy as strategy_bp

        source = _inspect.getsource(strategy_bp._init_mock_marketplace_listings)

        assert 'is_active=False' in source, (
            "Seeded marketplace storefront templates must be is_active=False -- "
            "created active they are live webhook listeners owned by no real user."
        )
        assert 'lifecycle_state="Draft"' in source, (
            "Seeded marketplace storefront templates must be lifecycle_state='Draft'."
        )
