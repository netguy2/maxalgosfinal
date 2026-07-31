"""Tests for platform-managed trailing stops.

Why this exists: the first version of the Trailing Stop field stored a value
and logged "enforced by the broker where supported". Most Indian brokers
don't support it, so the field looked configured while protecting nothing --
the worst possible failure for a risk control, because the trader sizes their
position believing they are covered.

These tests pin the properties that make the real implementation trustworthy:
the stop RATCHETS (never loosens), it fires at the right moment, and a
failed exit is retried rather than silently dropped.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# These tests exercise pure model/monitor logic and never touch a real
# database, but importing database.strategy_db builds an engine at module
# scope -- so give it an in-memory URL rather than requiring a configured
# .env just to run unit tests.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest  # noqa: E402

from database.strategy_db import TrailingStop  # noqa: E402


def _long(entry=100.0, trail_value=10.0, trail_type="percent"):
    ts = TrailingStop(
        username="u", symbol="X", exchange="NFO", quantity=1,
        entry_side="BUY", entry_price=entry,
        trail_type=trail_type, trail_value=trail_value,
        peak_price=entry, stop_price=0.0, status="active",
    )
    ts.stop_price = ts.compute_stop(entry)
    return ts


def _short(entry=100.0, trail_value=10.0, trail_type="percent"):
    ts = TrailingStop(
        username="u", symbol="Y", exchange="NFO", quantity=1,
        entry_side="SELL", entry_price=entry,
        trail_type=trail_type, trail_value=trail_value,
        peak_price=entry, stop_price=0.0, status="active",
    )
    ts.stop_price = ts.compute_stop(entry)
    return ts


# ---------------------------------------------------------------------
# Initial placement
# ---------------------------------------------------------------------


def test_long_stop_starts_below_entry():
    assert _long(100.0, 10.0).stop_price == 90.0


def test_short_stop_starts_above_entry():
    assert _short(100.0, 10.0).stop_price == 110.0


def test_points_trail_is_absolute_not_percent():
    assert _long(100.0, 10.0, "points").stop_price == 90.0
    assert _long(500.0, 10.0, "points").stop_price == 490.0


# ---------------------------------------------------------------------
# The ratchet -- the defining property of a trailing stop
# ---------------------------------------------------------------------


def test_long_stop_rises_with_price():
    ts = _long(100.0, 10.0)
    ts.update_peak(120.0)
    assert ts.peak_price == 120.0
    assert ts.stop_price == 108.0


def test_long_stop_never_falls_on_a_pullback():
    """THE critical property: a stop that loosens is not a stop."""
    ts = _long(100.0, 10.0)
    ts.update_peak(120.0)
    ts.update_peak(110.0)  # pullback
    assert ts.peak_price == 120.0
    assert ts.stop_price == 108.0


def test_short_stop_falls_with_price_and_never_rises():
    ts = _short(100.0, 10.0, "points")
    ts.update_peak(80.0)
    assert ts.stop_price == 90.0
    ts.update_peak(90.0)  # pullback against the short
    assert ts.stop_price == 90.0


def test_update_reports_whether_it_moved():
    ts = _long(100.0, 10.0)
    assert ts.update_peak(110.0) is True
    assert ts.update_peak(105.0) is False


@pytest.mark.parametrize("bad", [None, 0, -5])
def test_invalid_prices_never_move_the_stop(bad):
    """A missing/zero LTP must not be read as a crash to zero."""
    ts = _long(100.0, 10.0)
    before = ts.stop_price
    assert ts.update_peak(bad) is False
    assert ts.stop_price == before


# ---------------------------------------------------------------------
# Firing
# ---------------------------------------------------------------------


def test_long_fires_at_or_below_stop():
    ts = _long(100.0, 10.0)
    assert ts.is_hit(91.0) is False
    assert ts.is_hit(90.0) is True
    assert ts.is_hit(89.0) is True


def test_short_fires_at_or_above_stop():
    ts = _short(100.0, 10.0)
    assert ts.is_hit(109.0) is False
    assert ts.is_hit(110.0) is True


def test_fires_against_the_ratcheted_level_not_the_original():
    """After trailing up, the stop must fire in profit -- that is the whole
    point of trailing rather than a fixed stop."""
    ts = _long(100.0, 10.0)
    ts.update_peak(150.0)
    assert ts.stop_price == 135.0
    assert ts.is_hit(140.0) is False
    assert ts.is_hit(135.0) is True
    # Would NOT have fired under the original 90.0 stop.
    assert 135.0 > ts.entry_price


@pytest.mark.parametrize("bad", [None, 0, -1])
def test_invalid_price_never_fires_the_stop(bad):
    assert _long(100.0, 10.0).is_hit(bad) is False


# ---------------------------------------------------------------------
# Monitor behaviour
# ---------------------------------------------------------------------


def test_breach_wins_over_ratchet_within_one_tick(monkeypatch):
    """If a tick both improves the peak and breaches the stop, the exit must
    win -- ratcheting first could move the stop past the breaching price."""
    import services.trailing_stop_service as svc

    ts = _long(100.0, 10.0)
    ts.id = 1
    ts.update_peak(150.0)  # stop now 135
    exited = []

    monkeypatch.setattr(svc, "_exit_position", lambda t, k: exited.append(t.symbol) or True)
    monkeypatch.setattr(svc, "close_trailing_stop", lambda *a, **k: None)
    monkeypatch.setattr(svc, "_notify", lambda *a, **k: None)

    svc._process_one(ts, "key", 130.0)
    assert exited == ["X"]


def test_failed_exit_leaves_the_stop_active(monkeypatch):
    """A stop that was hit but failed to exit is still live risk -- it must
    be retried, never silently dropped."""
    import services.trailing_stop_service as svc

    ts = _long(100.0, 10.0)
    ts.id = 1
    closed = []

    monkeypatch.setattr(svc, "_exit_position", lambda t, k: False)
    monkeypatch.setattr(svc, "close_trailing_stop", lambda *a, **k: closed.append(a))
    monkeypatch.setattr(svc, "_notify", lambda *a, **k: None)

    svc._process_one(ts, "key", 80.0)
    assert closed == [], "must not close a stop whose exit failed"


def test_missing_price_is_a_no_op(monkeypatch):
    import services.trailing_stop_service as svc

    ts = _long(100.0, 10.0)
    ts.id = 1
    exited = []
    monkeypatch.setattr(svc, "_exit_position", lambda t, k: exited.append(1) or True)

    svc._process_one(ts, "key", None)
    assert exited == []


def test_tick_survives_a_failing_stop(monkeypatch):
    """One bad position must not stop every other trailing stop being
    checked -- and must never raise out of the APScheduler job."""
    import services.trailing_stop_service as svc

    good = _long(100.0, 10.0)
    good.id = 2
    bad = _long(100.0, 10.0)
    bad.id = 1

    monkeypatch.setattr(svc, "get_active_trailing_stops", lambda: [bad, good])
    monkeypatch.setattr(svc, "_get_ltp", lambda s, e, k: 105.0)
    monkeypatch.setattr("database.auth_db.get_api_key_for_tradingview", lambda u: "k")

    seen = []

    def _process(ts, api_key, ltp):
        if ts.id == 1:
            raise RuntimeError("broker down")
        seen.append(ts.id)

    monkeypatch.setattr(svc, "_process_one", _process)

    svc._tick()  # must not raise
    assert seen == [2]
