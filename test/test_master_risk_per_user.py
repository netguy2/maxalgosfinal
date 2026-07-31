"""Per-user isolation tests for Master SL / Target.

Master SL/Target originally lived on the single global `Settings` row and
the monitor resolved the account with
`Auth.query.filter_by(is_revoked=False).first()`. On a multi-user instance
that meant one trader arming "stop me out at -5000" armed it for EVERY
account, and the monitor closed real positions belonging to whichever user
that query happened to return.

These tests pin the per-user contract so that cannot silently regress.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import database.settings_db as settings_db  # noqa: E402
import services.master_risk_monitor_service as monitor  # noqa: E402

USER_A = "__test_mr_user_a__"
USER_B = "__test_mr_user_b__"


def _purge(*usernames):
    for username in usernames:
        settings_db.db_session.query(settings_db.UserRiskSettings).filter_by(
            username=username
        ).delete()
    settings_db.db_session.commit()


@pytest.fixture(autouse=True)
def _clean():
    _purge(USER_A, USER_B)
    yield
    _purge(USER_A, USER_B)


# ---------------------------------------------------------------------
# Settings isolation
# ---------------------------------------------------------------------


def test_settings_default_to_disabled():
    s = settings_db.get_master_risk_settings(USER_A)
    assert s["enabled"] is False
    assert s["sl_value"] is None
    assert s["target_value"] is None


def test_unknown_user_gets_safe_defaults():
    """No row and no identity must read as "not armed" rather than
    inheriting another account's thresholds."""
    s = settings_db.get_master_risk_settings(None)
    assert s["enabled"] is False
    assert s["sl_value"] is None


def test_one_users_thresholds_do_not_leak_to_another():
    """THE regression test: A arming -5000 must leave B unarmed."""
    settings_db.set_master_risk_settings(USER_A, enabled=True, sl_value=5000.0, target_value=None)

    a = settings_db.get_master_risk_settings(USER_A)
    b = settings_db.get_master_risk_settings(USER_B)

    assert a["enabled"] is True
    assert a["sl_value"] == 5000.0

    assert b["enabled"] is False
    assert b["sl_value"] is None


def test_updating_one_user_does_not_overwrite_the_other():
    settings_db.set_master_risk_settings(USER_A, enabled=True, sl_value=5000.0, target_value=None)
    settings_db.set_master_risk_settings(USER_B, enabled=True, sl_value=None, target_value=250.0)

    a = settings_db.get_master_risk_settings(USER_A)
    b = settings_db.get_master_risk_settings(USER_B)

    assert (a["sl_value"], a["target_value"]) == (5000.0, None)
    assert (b["sl_value"], b["target_value"]) == (None, 250.0)


# ---------------------------------------------------------------------
# The monitor's user enumeration
# ---------------------------------------------------------------------


def test_list_enabled_returns_only_armed_users():
    settings_db.set_master_risk_settings(USER_A, enabled=True, sl_value=5000.0, target_value=None)
    settings_db.set_master_risk_settings(USER_B, enabled=False, sl_value=1000.0, target_value=None)

    enabled = settings_db.list_enabled_master_risk_users()

    assert USER_A in enabled
    assert USER_B not in enabled


def test_trigger_disables_only_the_triggering_user():
    """The breaker trips for the user who crossed their threshold; every
    other armed user stays armed."""
    settings_db.set_master_risk_settings(USER_A, enabled=True, sl_value=5000.0, target_value=None)
    settings_db.set_master_risk_settings(USER_B, enabled=True, sl_value=8000.0, target_value=None)

    settings_db.record_master_risk_trigger(USER_A, "sl", -5200.0)

    a = settings_db.get_master_risk_settings(USER_A)
    b = settings_db.get_master_risk_settings(USER_B)

    assert a["enabled"] is False
    assert a["triggered_reason"] == "sl"
    assert b["enabled"] is True
    assert b["triggered_reason"] is None


def test_audit_is_filtered_per_user():
    settings_db.record_master_risk_audit(
        username=USER_A, reason="sl", combined_pnl_at_trigger=-5200.0, threshold_value=5000.0
    )
    settings_db.record_master_risk_audit(
        username=USER_B, reason="target", combined_pnl_at_trigger=9000.0, threshold_value=8000.0
    )

    try:
        a_entries = settings_db.get_master_risk_audit(USER_A, limit=50)
        a_reasons = {e["reason"] for e in a_entries}
        # A sees their own SL trigger, never B's target trigger or P&L.
        assert "sl" in a_reasons
        assert all(e["combined_pnl_at_trigger"] != 9000.0 for e in a_entries)
    finally:
        settings_db.MasterRiskAudit.query.filter(
            settings_db.MasterRiskAudit.username.in_([USER_A, USER_B])
        ).delete(synchronize_session=False)
        settings_db.db_session.commit()


# ---------------------------------------------------------------------
# The monitor tick itself
# ---------------------------------------------------------------------


def test_tick_evaluates_each_armed_user_independently(monkeypatch):
    """The tick must iterate every armed user, not assume a single account.
    Each user's threshold is checked against THEIR OWN P&L."""
    settings_db.set_master_risk_settings(USER_A, enabled=True, sl_value=5000.0, target_value=None)
    settings_db.set_master_risk_settings(USER_B, enabled=True, sl_value=5000.0, target_value=None)

    # A is deep in the red (should trigger); B is flat (should not).
    pnl_by_user = {USER_A: (-6000.0, 2, [("zerodha", "tok-a")]),
                   USER_B: (10.0, 1, [("dhan", "tok-b")])}
    closed_for = []

    monkeypatch.setattr(monitor, "is_market_open", lambda: True)
    monkeypatch.setattr(monitor, "_get_combined_open_pnl", lambda u: pnl_by_user[u])
    monkeypatch.setattr(
        monitor, "_close_all_positions",
        lambda u, sessions: (closed_for.append(u), (1, ["closed"]))[1],
    )
    monkeypatch.setattr(monitor, "_emit_trigger_events", lambda *a, **k: None)
    monkeypatch.setattr(
        monitor, "list_enabled_master_risk_users", lambda: [USER_A, USER_B]
    )

    monitor._check_and_trigger()

    # Only A's positions were closed -- B's account was never touched.
    assert closed_for == [USER_A]
    assert settings_db.get_master_risk_settings(USER_A)["enabled"] is False
    assert settings_db.get_master_risk_settings(USER_B)["enabled"] is True

    settings_db.MasterRiskAudit.query.filter(
        settings_db.MasterRiskAudit.username.in_([USER_A, USER_B])
    ).delete(synchronize_session=False)
    settings_db.db_session.commit()


def test_tick_continues_after_one_user_raises(monkeypatch):
    """One user's broker failure must not stop the remaining users being
    evaluated -- otherwise a single bad account silently disables everyone
    else's stop-loss."""
    settings_db.set_master_risk_settings(USER_A, enabled=True, sl_value=5000.0, target_value=None)
    settings_db.set_master_risk_settings(USER_B, enabled=True, sl_value=5000.0, target_value=None)

    evaluated = []

    def _pnl(username):
        evaluated.append(username)
        if username == USER_A:
            raise RuntimeError("broker unreachable")
        return (10.0, 1, [])

    monkeypatch.setattr(monitor, "is_market_open", lambda: True)
    monkeypatch.setattr(monitor, "_get_combined_open_pnl", _pnl)
    monkeypatch.setattr(
        monitor, "list_enabled_master_risk_users", lambda: [USER_A, USER_B]
    )

    monitor._check_and_trigger()  # must not raise

    assert evaluated == [USER_A, USER_B]


def test_tick_skips_entirely_when_market_closed(monkeypatch):
    called = []
    monkeypatch.setattr(monitor, "is_market_open", lambda: False)
    monkeypatch.setattr(
        monitor, "list_enabled_master_risk_users", lambda: called.append("listed") or []
    )

    monitor._check_and_trigger()

    assert called == []
