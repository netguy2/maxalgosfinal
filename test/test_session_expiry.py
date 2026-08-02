"""Regression tests for session expiry side effects."""

import os
import sys

import pytest
from flask import Flask, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database.auth_db as auth_db  # noqa: E402
import extensions  # noqa: E402
import utils.session as session_utils  # noqa: E402


def test_auto_expiry_broadcasts_force_logout_to_all_devices(monkeypatch):
    """3 AM auto-expiry should notify the expiring user's other browser
    sessions immediately -- scoped to that user's own room, not broadcast
    to every connected client on the platform (see room= on the emit
    calls in utils/session.py)."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    emitted = []

    class FakeSocketIO:
        def emit(self, event, payload, room=None):
            emitted.append((event, payload, room))

    monkeypatch.setattr(auth_db, "upsert_auth", lambda *args, **kwargs: 1)
    monkeypatch.setattr(auth_db, "clear_user_sessions", lambda username: None)
    monkeypatch.setattr(extensions, "socketio", FakeSocketIO())
    monkeypatch.setattr(
        "database.cache_invalidation.publish_all_cache_invalidation",
        lambda username: None,
    )
    monkeypatch.setattr("database.master_contract_cache_hook.clear_cache_on_logout", lambda: None)
    monkeypatch.setattr("database.settings_db.clear_settings_cache", lambda: None)
    monkeypatch.setattr("database.strategy_db.clear_strategy_cache", lambda: None)

    with app.test_request_context("/"):
        session["user"] = "rajandran"
        session_utils.revoke_user_tokens(revoke_db_tokens=True)

    assert ("active_sessions_update", {"count": 0, "sessions": []}, "user_rajandran") in emitted
    force_logout_events = [
        (payload, room) for event, payload, room in emitted if event == "force_logout"
    ]
    assert force_logout_events
    payload, room = force_logout_events[0]
    assert "Session expired" in payload["message"]
    # Scoped to the expiring user's own room -- NOT broadcast to every
    # connected client (that was the bug: any one user's daily token
    # rollover force-logged out every other logged-in user too).
    assert room == "user_rajandran"


def test_single_session_displacement_emits_force_logout_and_invalidates_old_session(monkeypatch):
    """Registering a new session for a user should displace the previous session
    and send a targeted force_logout event to the displaced session's room."""
    app = Flask(__name__)
    app.secret_key = "test-secret"
    emitted = []

    class FakeSocketIO:
        def emit(self, event, payload, room=None):
            emitted.append((event, payload, room))

    class FakeQuery:
        def __init__(self, items):
            self.items = items

        def filter_by(self, **kwargs):
            filtered = self.items
            if "username" in kwargs:
                filtered = [i for i in filtered if getattr(i, "username", None) == kwargs["username"]]
            if "session_id" in kwargs:
                filtered = [i for i in filtered if getattr(i, "session_id", None) == kwargs["session_id"]]
            return FakeQuery(filtered)

        def all(self):
            return self.items

        def first(self):
            return self.items[0] if self.items else None

        def count(self):
            return len(self.items)

        def delete(self):
            count = len(self.items)
            self.items.clear()
            return count

    class FakeActiveSessionItem:
        def __init__(self, username, session_id):
            self.username = username
            self.session_id = session_id

    sessions_db = [FakeActiveSessionItem("testuser", "sess_device_1")]

    monkeypatch.setattr(auth_db, "SINGLE_SESSION_PER_USER", True)
    monkeypatch.setattr(extensions, "socketio", FakeSocketIO())
    monkeypatch.setattr(auth_db.ActiveSession, "query", FakeQuery(sessions_db))
    monkeypatch.setattr(auth_db.db_session, "add", lambda item: sessions_db.append(item))
    monkeypatch.setattr(auth_db.db_session, "commit", lambda: None)
    monkeypatch.setattr(auth_db.db_session, "delete", lambda item: sessions_db.remove(item) if item in sessions_db else None)

    # Register new session from Device 2
    auth_db.register_session("testuser", "sess_device_2", device_info="Device 2", ip_address="1.2.3.4")

    # Verify force_logout was emitted to session_sess_device_1 room
    displaced_events = [
        (event, payload, room)
        for event, payload, room in emitted
        if event == "force_logout" and room == "session_sess_device_1"
    ]
    assert displaced_events
    payload = displaced_events[0][1]
    assert payload["reason"] == "logged_in_another_device"

