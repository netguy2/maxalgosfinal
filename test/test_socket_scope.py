"""Regression tests for per-user Socket.IO notification scoping.

The bug: `socketio.emit(event, payload)` with no `room=` broadcasts to
EVERY connected client. On a multi-user instance that meant User A
connecting a broker, running a strategy, hitting the kill switch, or
approving an order fired toasts and state refreshes in User B's browser.

These tests pin the two invariants that fix relies on:
  1. a resolvable acting user  -> emit goes to `user_<username>` ONLY
  2. an unresolvable acting user -> emit is DROPPED, never broadcast
"""

import os
import sys

import pytest
from flask import Flask

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import extensions  # noqa: E402
import utils.socket_scope as socket_scope  # noqa: E402


class FakeSocketIO:
    """Records emits. `room=None` here means "broadcast to everyone" --
    which is precisely the bug, so tests assert it never happens."""

    def __init__(self):
        self.emitted = []

    def emit(self, event, payload=None, *args, **kwargs):
        self.emitted.append((event, payload, kwargs.get("room")))

    @property
    def broadcasts(self):
        return [e for e in self.emitted if e[2] is None]


@pytest.fixture
def fake_socketio(monkeypatch):
    fake = FakeSocketIO()
    monkeypatch.setattr(extensions, "socketio", fake)
    return fake


# --------------------------------------------------------------------
# emit_to_user
# --------------------------------------------------------------------


def test_emit_to_user_targets_only_that_users_room(fake_socketio):
    assert socket_scope.emit_to_user("order_event", {"symbol": "SBIN"}, "alice") is True
    assert fake_socketio.emitted == [("order_event", {"symbol": "SBIN"}, "user_alice")]
    assert fake_socketio.broadcasts == []


@pytest.mark.parametrize("username", [None, ""])
def test_emit_to_user_drops_rather_than_broadcasts(fake_socketio, username):
    """The core fail-closed guarantee: no resolvable user means NO emit.
    Broadcasting here is what leaked one user's activity to all others."""
    assert socket_scope.emit_to_user("order_event", {"symbol": "SBIN"}, username) is False
    assert fake_socketio.emitted == []


def test_two_users_never_receive_each_others_events(fake_socketio):
    socket_scope.emit_to_user("order_event", {"symbol": "SBIN"}, "alice")
    socket_scope.emit_to_user("order_event", {"symbol": "INFY"}, "bob")

    rooms = [room for _, _, room in fake_socketio.emitted]
    assert rooms == ["user_alice", "user_bob"]
    assert fake_socketio.broadcasts == []


# --------------------------------------------------------------------
# user_scope / resolve_current_username
# --------------------------------------------------------------------


def test_user_scope_sets_and_restores(monkeypatch):
    assert socket_scope.resolve_current_username() is None
    with socket_scope.user_scope("alice"):
        assert socket_scope.resolve_current_username() == "alice"
        with socket_scope.user_scope("bob"):
            assert socket_scope.resolve_current_username() == "bob"
        assert socket_scope.resolve_current_username() == "alice"
    assert socket_scope.resolve_current_username() is None


def test_user_scope_restores_even_on_exception():
    with pytest.raises(RuntimeError):
        with socket_scope.user_scope("alice"):
            raise RuntimeError("boom")
    assert socket_scope.resolve_current_username() is None


def test_emit_to_current_user_uses_active_scope(fake_socketio):
    with socket_scope.user_scope("alice"):
        socket_scope.emit_to_current_user("master_contract_download", {"status": "success"})
    assert fake_socketio.emitted == [
        ("master_contract_download", {"status": "success"}, "user_alice")
    ]


def test_emit_to_current_user_drops_outside_any_scope(fake_socketio):
    """Startup/scheduled downloads have no acting user -- must not broadcast."""
    assert socket_scope.emit_to_current_user("master_contract_download", {}) is False
    assert fake_socketio.emitted == []


def test_scope_falls_back_to_flask_session(fake_socketio):
    app = Flask(__name__)
    app.secret_key = "test-secret"
    with app.test_request_context("/"):
        from flask import session as flask_session

        flask_session["user"] = "carol"
        socket_scope.emit_to_current_user("active_sessions_update", {"count": 2})
    assert fake_socketio.emitted == [("active_sessions_update", {"count": 2}, "user_carol")]


def test_explicit_scope_wins_over_flask_session(fake_socketio):
    """A background thread acting for alice must not be re-attributed to
    whoever's request context happens to be active."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    with app.test_request_context("/"):
        from flask import session as flask_session

        flask_session["user"] = "carol"
        with socket_scope.user_scope("alice"):
            socket_scope.emit_to_current_user("master_contract_download", {})
    assert fake_socketio.emitted[0][2] == "user_alice"


# --------------------------------------------------------------------
# scoped_socketio proxy (the ~28 broker master_contract_db modules)
# --------------------------------------------------------------------


def test_scoped_proxy_emit_scopes_to_current_user(fake_socketio):
    with socket_scope.user_scope("alice"):
        socket_scope.scoped_socketio.emit(
            "master_contract_download", {"status": "success", "message": "Successfully Downloaded"}
        )
    assert fake_socketio.emitted[0][2] == "user_alice"
    assert fake_socketio.broadcasts == []


def test_scoped_proxy_drops_when_unscoped(fake_socketio):
    """This is the reported symptom: User A connects a broker, User B sees
    "Master Contract: Successfully Downloaded". Unattributed -> dropped."""
    assert socket_scope.scoped_socketio.emit("master_contract_download", {}) is False
    assert fake_socketio.emitted == []


def test_scoped_proxy_honours_explicit_room(fake_socketio):
    socket_scope.scoped_socketio.emit("evt", {"a": 1}, room="user_dave")
    assert fake_socketio.emitted == [("evt", {"a": 1}, "user_dave")]


def test_scoped_proxy_return_value_is_falsy_when_dropped(fake_socketio):
    """Several broker modules `return socketio.emit(...)`; callers treat
    the result as a truthiness signal, so a drop must stay falsy."""
    assert not socket_scope.scoped_socketio.emit("master_contract_download", {})


# --------------------------------------------------------------------
# username_from_api_key
# --------------------------------------------------------------------


def test_username_from_api_key_resolves(monkeypatch):
    monkeypatch.setattr("database.auth_db.verify_api_key", lambda key: "alice")
    assert socket_scope.username_from_api_key("some-key") == "alice"


@pytest.mark.parametrize("bad", [None, ""])
def test_username_from_api_key_handles_missing_key(bad):
    assert socket_scope.username_from_api_key(bad) is None


def test_username_from_api_key_swallows_lookup_errors(monkeypatch):
    def boom(key):
        raise RuntimeError("db down")

    monkeypatch.setattr("database.auth_db.verify_api_key", boom)
    # Must degrade to "unknown user" (-> drop), never raise into the
    # caller's order/notification path.
    assert socket_scope.username_from_api_key("k") is None


def test_unknown_api_key_results_in_dropped_emit(fake_socketio, monkeypatch):
    monkeypatch.setattr("database.auth_db.verify_api_key", lambda key: None)
    username = socket_scope.username_from_api_key("revoked-key")
    assert socket_scope.emit_to_user("analyzer_update", {}, username) is False
    assert fake_socketio.emitted == []


# --------------------------------------------------------------------
# emit failures must not propagate
# --------------------------------------------------------------------


def test_emit_exception_is_contained(monkeypatch):
    class ExplodingSocketIO:
        def emit(self, *args, **kwargs):
            raise RuntimeError("socket gone")

    monkeypatch.setattr(extensions, "socketio", ExplodingSocketIO())
    # A notification failure must never break the order/download path it
    # is reporting on.
    assert socket_scope.emit_to_user("order_event", {}, "alice") is False
