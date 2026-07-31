"""Unit tests for the kill switch: decorator enforcement and state
management in database/settings_db.py.

See docs/plans/2026-04-24-kill-switch-implementation-plan.md for the full
design this implements.

The kill switch is PER-USER. It originally lived on the single global
`Settings` row, which meant one user's activation blocked live order
placement for every account on the instance and ran cleanup against an
arbitrary account's brokers. These tests pin the per-user behaviour so that
regression cannot come back silently.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import database.settings_db as settings_db  # noqa: E402
from utils.kill_switch import KILL_SWITCH_ERROR_CODE, enforce_kill_switch  # noqa: E402

USER_A = "__test_ks_user_a__"
USER_B = "__test_ks_user_b__"


def _purge(*usernames):
    for username in usernames:
        settings_db.db_session.query(settings_db.UserRiskSettings).filter_by(
            username=username
        ).delete()
    settings_db.db_session.commit()


@pytest.fixture(autouse=True)
def _clean_kill_switch_state():
    """Remove this test file's synthetic users before and after every test,
    and clear the cache so no state leaks between tests. Uses the real dev
    DB (same convention as the rest of this file) but touches only the
    __test_ks_* rows, so a developer's own settings are never disturbed."""
    settings_db.clear_settings_cache()
    _purge(USER_A, USER_B)
    settings_db.clear_settings_cache()

    yield

    settings_db.clear_settings_cache()
    _purge(USER_A, USER_B)
    settings_db.clear_settings_cache()


def test_is_kill_switch_active_defaults_false():
    assert settings_db.is_kill_switch_active(USER_A) is False


def test_unknown_user_is_not_blocked():
    """An unresolvable identity must fail OPEN, not inherit someone
    else's flag -- see is_kill_switch_active's docstring."""
    assert settings_db.is_kill_switch_active(None) is False
    assert settings_db.is_kill_switch_active("") is False


def test_set_kill_switch_persists_to_db():
    state = settings_db.set_kill_switch(USER_A, True, "ui", "testuser", "manual test")

    assert state["kill_switch_active"] is True
    assert state["activated_by"] == "ui"
    assert state["reason"] == "manual test"
    assert state["min_unlock_at"] is not None

    # Independently re-read from DB (bypassing cache) to confirm it was
    # actually written, not just returned from the in-memory call.
    settings_db.clear_settings_cache()
    assert settings_db.is_kill_switch_active(USER_A) is True


def test_cache_invalidation_on_set():
    assert settings_db.is_kill_switch_active(USER_A) is False  # warms the cache as False

    settings_db.set_kill_switch(USER_A, True, "ui", "testuser", None)

    # Without cache invalidation this would still read the stale False.
    assert settings_db.is_kill_switch_active(USER_A) is True


def test_deactivate_clears_flag():
    settings_db.set_kill_switch(USER_A, True, "ui", "testuser", "test")
    assert settings_db.is_kill_switch_active(USER_A) is True

    state = settings_db.set_kill_switch(USER_A, False, "ui", "testuser", None)
    assert state["kill_switch_active"] is False
    assert settings_db.is_kill_switch_active(USER_A) is False


def test_get_kill_switch_state_full_record():
    settings_db.set_kill_switch(USER_A, True, "telegram", "12345", "panic test")
    state = settings_db.get_kill_switch_state(USER_A)

    assert state["kill_switch_active"] is True
    assert state["activated_by"] == "telegram"
    assert state["reason"] == "panic test"
    assert state["activated_at"] is not None
    assert state["min_unlock_at"] is not None


# ---------------------------------------------------------------------
# Per-user isolation -- the actual bug this refactor fixes
# ---------------------------------------------------------------------


def test_one_users_kill_switch_does_not_affect_another():
    """THE regression test. User A activating their kill switch must leave
    User B able to trade."""
    settings_db.set_kill_switch(USER_A, True, "ui", USER_A, "A panics")

    assert settings_db.is_kill_switch_active(USER_A) is True
    assert settings_db.is_kill_switch_active(USER_B) is False


def test_per_user_cache_keys_do_not_collide():
    settings_db.is_kill_switch_active(USER_A)  # warm A as False
    settings_db.is_kill_switch_active(USER_B)  # warm B as False

    settings_db.set_kill_switch(USER_A, True, "ui", USER_A, None)

    # A's write must not be readable as B's state via a shared cache key.
    assert settings_db.is_kill_switch_active(USER_A) is True
    assert settings_db.is_kill_switch_active(USER_B) is False


def test_scope_is_per_user():
    settings_db.set_kill_switch_scope(
        USER_A, cancel_orders_enabled=False, close_positions_enabled=False
    )

    a_scope = settings_db.get_kill_switch_scope(USER_A)
    b_scope = settings_db.get_kill_switch_scope(USER_B)

    assert a_scope == {"cancel_orders_enabled": False, "close_positions_enabled": False}
    # B keeps the safe defaults rather than inheriting A's narrowed scope.
    assert b_scope == {"cancel_orders_enabled": True, "close_positions_enabled": True}


def test_audit_is_filtered_per_user():
    marker_a = "__test_ks_audit_a__"
    marker_b = "__test_ks_audit_b__"
    settings_db.record_kill_switch_audit(
        username=USER_A, event_type="activated", actor_type="ui",
        actor_id=USER_A, reason=marker_a,
    )
    settings_db.record_kill_switch_audit(
        username=USER_B, event_type="activated", actor_type="ui",
        actor_id=USER_B, reason=marker_b,
    )

    try:
        a_reasons = [e["reason"] for e in settings_db.get_kill_switch_audit(USER_A, limit=50)]
        assert marker_a in a_reasons
        # A must never see B's activation history.
        assert marker_b not in a_reasons
    finally:
        settings_db.KillSwitchAudit.query.filter(
            settings_db.KillSwitchAudit.reason.in_([marker_a, marker_b])
        ).delete(synchronize_session=False)
        settings_db.db_session.commit()


def test_record_and_read_kill_switch_audit():
    # Marker reason lets us find-and-delete exactly this test's row after
    # assertions, so this test (which runs against the real dev DB, not an
    # isolated fixture DB -- see module docstring) leaves zero residue.
    marker = "__test_kill_switch_audit_marker__"
    settings_db.record_kill_switch_audit(
        username=USER_A,
        event_type="activated",
        actor_type="ui",
        actor_id="testuser",
        reason=marker,
        live_orders_cancelled=3,
        live_positions_closed=1,
        strategies_stopped=2,
    )

    try:
        entries = settings_db.get_kill_switch_audit(USER_A, limit=5)
        matching = [e for e in entries if e["reason"] == marker]
        assert len(matching) >= 1
        latest = matching[0]
        assert latest["event_type"] == "activated"
        assert latest["actor_type"] == "ui"
        assert latest["live_orders_cancelled"] == 3
        assert latest["strategies_stopped"] == 2
    finally:
        settings_db.KillSwitchAudit.query.filter_by(reason=marker).delete()
        settings_db.db_session.commit()


# ---------------------------------------------------------------------
# Decorator enforcement
# ---------------------------------------------------------------------


def test_enforce_decorator_rejects_when_active(monkeypatch):
    monkeypatch.setattr(
        "utils.socket_scope.username_from_api_key", lambda key: USER_A if key else None
    )
    settings_db.set_kill_switch(USER_A, True, "ui", "testuser", None)

    @enforce_kill_switch("order")
    def fake_place_order(order_data, api_key=None):
        return True, {"status": "success"}, 200

    success, response, status_code = fake_place_order({"symbol": "SBIN"}, api_key="k")

    assert success is False
    assert status_code == 403
    assert response["code"] == KILL_SWITCH_ERROR_CODE


def test_enforce_decorator_allows_other_user_when_active(monkeypatch):
    """User A's active switch must not block an order placed by User B."""
    monkeypatch.setattr(
        "utils.socket_scope.username_from_api_key", lambda key: USER_B
    )
    settings_db.set_kill_switch(USER_A, True, "ui", USER_A, None)

    @enforce_kill_switch("order")
    def fake_place_order(order_data, api_key=None):
        return True, {"status": "success"}, 200

    success, _response, status_code = fake_place_order({"symbol": "SBIN"}, api_key="b-key")

    assert success is True
    assert status_code == 200


def test_enforce_decorator_allows_when_inactive():
    @enforce_kill_switch("order")
    def fake_place_order(order_data, api_key=None):
        return True, {"status": "success"}, 200

    success, response, status_code = fake_place_order({"symbol": "SBIN"})

    assert success is True
    assert status_code == 200


def test_enforce_decorator_allows_cancel_op_even_when_active():
    settings_db.set_kill_switch(USER_A, True, "ui", "testuser", None)

    @enforce_kill_switch("cancel")
    def fake_cancel_all_orders():
        return True, {"status": "success"}, 200

    success, response, status_code = fake_cancel_all_orders()

    assert success is True
    assert status_code == 200


def test_enforce_decorator_reads_api_key_positionally(monkeypatch):
    """The decorator binds against the real signature, so an api_key passed
    positionally resolves the same as one passed by keyword."""
    monkeypatch.setattr(
        "utils.socket_scope.username_from_api_key", lambda key: USER_A
    )
    settings_db.set_kill_switch(USER_A, True, "ui", USER_A, None)

    @enforce_kill_switch("order")
    def fake_place_order(order_data, api_key=None):
        return True, {"status": "success"}, 200

    success, _resp, status = fake_place_order({"symbol": "SBIN"}, "positional-key")

    assert success is False
    assert status == 403


def test_activate_is_idempotent_at_service_layer():
    """activate_kill_switch() must not re-run cleanup on a second call while
    already active -- verified narrowly here at the flag level (full
    orchestrator cleanup is exercised via manual QA / integration testing
    per the design doc, since it calls out to broker/sandbox/strategy
    subsystems that aren't meaningfully unit-testable without a live
    broker stub)."""
    first = settings_db.set_kill_switch(USER_A, True, "ui", "testuser", "first")
    assert first["kill_switch_active"] is True

    # A second activation attempt should see it's already active via
    # get_kill_switch_state() before any cleanup would run -- this is the
    # check services/kill_switch_service.py::activate_kill_switch performs.
    already_active = settings_db.get_kill_switch_state(USER_A)["kill_switch_active"]
    assert already_active is True
