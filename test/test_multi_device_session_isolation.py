"""Regression tests for a real incident: two devices/users legitimately
sharing one Max Algos account (the default, supported deployment mode --
SINGLE_SESSION_PER_USER defaults to "false" in database/auth_db.py) were
force-logging each other out, and the shared account-wide broker token was
being revoked, whenever ONE device's session_id was evicted from the
ActiveSession table (e.g. the 5th device logging in evicts the oldest under
MAX_SESSIONS_PER_USER, or any other churn of that table).

Root cause: is_session_valid() collapsed two structurally different
invalidity reasons into a single bool:
  - "superseded": this device's session_id row is gone, but the shared
    broker token is still perfectly valid -- other devices are actively
    using it.
  - "daily_expiry": the broker token has genuinely died account-wide (the
    ~3 AM IST rollover) -- every device really does need to re-auth.

app.py's check_session_expiry before_request hook then called
revoke_user_tokens(revoke_db_tokens=True) for EITHER reason, which revokes
the ONE shared broker token for the whole account and wipes every device's
ActiveSession row (see revoke_user_tokens -> clear_user_sessions). One
device's routine session-table churn nuked every other device's still-good
session.

check_session_validity_reason() is the fix: it returns WHY a session is
invalid, so callers can revoke the shared token only for "daily_expiry" and
otherwise just clear the one affected device's own local session.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, session

import database.auth_db as auth_db
import utils.session as session_utils


def _app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    return app


class TestCheckSessionValidityReason:
    def test_not_logged_in(self):
        with _app().test_request_context("/"):
            valid, reason = session_utils.check_session_validity_reason()
            assert valid is False
            assert reason == "not_logged_in"

    def test_missing_login_time(self):
        with _app().test_request_context("/"):
            session["logged_in"] = True
            valid, reason = session_utils.check_session_validity_reason()
            assert valid is False
            assert reason == "no_login_time"

    def test_superseded_by_another_device(self, monkeypatch):
        """This is the exact incident: session_id no longer active in the
        DB (evicted by session-cap churn, NOT a real token expiry) must be
        distinguishable from a real daily expiry."""
        monkeypatch.setattr(auth_db, "is_session_id_active", lambda username, sid: False)

        with _app().test_request_context("/"):
            session["logged_in"] = True
            session["login_time"] = "2026-08-06T10:00:00+05:30"
            session["user"] = "trader1"
            session["session_id"] = "sess-device-a"

            valid, reason = session_utils.check_session_validity_reason()
            assert valid is False
            assert reason == "superseded"

    def test_valid_session_with_active_session_id(self, monkeypatch):
        monkeypatch.setattr(auth_db, "is_session_id_active", lambda username, sid: True)
        from datetime import datetime

        import pytz

        now_ist = datetime.now(pytz.timezone("Asia/Kolkata"))

        with _app().test_request_context("/"):
            session["logged_in"] = True
            session["login_time"] = now_ist.isoformat()
            session["user"] = "trader1"
            session["session_id"] = "sess-device-a"

            valid, reason = session_utils.check_session_validity_reason()
            assert valid is True
            assert reason is None

    def test_daily_expiry_when_login_before_rollover_and_now_after(self, monkeypatch):
        monkeypatch.setattr(auth_db, "is_session_id_active", lambda username, sid: True)
        monkeypatch.setenv("SESSION_EXPIRY_TIME", "03:00")

        with _app().test_request_context("/"):
            session["logged_in"] = True
            # Logged in yesterday afternoon, well before today's 3 AM rollover.
            session["login_time"] = "2026-08-05T14:00:00+05:30"
            session["user"] = "trader1"
            session["session_id"] = "sess-device-a"

            valid, reason = session_utils.check_session_validity_reason()
            assert valid is False
            assert reason == "daily_expiry"

    def test_is_session_valid_still_returns_plain_bool(self, monkeypatch):
        """Every pre-existing caller of is_session_valid() must keep working
        unchanged -- it's now a thin wrapper, not removed."""
        monkeypatch.setattr(auth_db, "is_session_id_active", lambda username, sid: False)
        with _app().test_request_context("/"):
            session["logged_in"] = True
            session["login_time"] = "2026-08-06T10:00:00+05:30"
            session["user"] = "trader1"
            session["session_id"] = "sess-device-a"
            assert session_utils.is_session_valid() is False


class TestRevokeUserTokensScoping:
    """revoke_user_tokens(revoke_db_tokens=False) must never touch the
    shared broker token or wipe other devices' sessions -- this is the
    branch app.py now takes for reason="superseded"."""

    def test_revoke_db_tokens_false_does_not_clear_other_sessions(self, monkeypatch):
        cleared_sessions = []
        upserted = []
        emitted = []

        monkeypatch.setattr(auth_db, "clear_user_sessions", lambda u: cleared_sessions.append(u))
        monkeypatch.setattr(auth_db, "upsert_auth", lambda *a, **k: upserted.append((a, k)) or 1)
        monkeypatch.setattr(
            "database.cache_invalidation.publish_all_cache_invalidation", lambda u: None
        )
        monkeypatch.setattr(
            "database.master_contract_cache_hook.clear_cache_on_logout", lambda: None
        )
        monkeypatch.setattr("database.settings_db.clear_settings_cache", lambda: None)
        monkeypatch.setattr("database.strategy_db.clear_strategy_cache", lambda: None)

        import extensions

        class FakeSocketIO:
            def emit(self, event, payload, room=None):
                emitted.append((event, payload, room))

        monkeypatch.setattr(extensions, "socketio", FakeSocketIO())

        with _app().test_request_context("/"):
            session["user"] = "trader1"
            session_utils.revoke_user_tokens(revoke_db_tokens=False)

        assert cleared_sessions == [], (
            "revoke_db_tokens=False must NOT clear other devices' sessions -- "
            "this is the exact bug that force-logged out a second device sharing "
            "the same account"
        )
        assert upserted == [], "revoke_db_tokens=False must NOT revoke the shared broker token"
        assert emitted == [], "revoke_db_tokens=False must NOT broadcast force_logout"

    def test_revoke_db_tokens_true_does_clear_sessions_and_broadcast(self, monkeypatch):
        """Sanity check the other branch still works: a genuine daily
        expiry SHOULD revoke the shared token and notify every device."""
        cleared_sessions = []
        emitted = []

        monkeypatch.setattr(auth_db, "clear_user_sessions", lambda u: cleared_sessions.append(u))
        monkeypatch.setattr(auth_db, "upsert_auth", lambda *a, **k: 1)
        monkeypatch.setattr(
            "database.cache_invalidation.publish_all_cache_invalidation", lambda u: None
        )
        monkeypatch.setattr(
            "database.master_contract_cache_hook.clear_cache_on_logout", lambda: None
        )
        monkeypatch.setattr("database.settings_db.clear_settings_cache", lambda: None)
        monkeypatch.setattr("database.strategy_db.clear_strategy_cache", lambda: None)

        import extensions

        class FakeSocketIO:
            def emit(self, event, payload, room=None):
                emitted.append((event, payload, room))

        monkeypatch.setattr(extensions, "socketio", FakeSocketIO())

        with _app().test_request_context("/"):
            session["user"] = "trader1"
            session_utils.revoke_user_tokens(revoke_db_tokens=True)

        assert cleared_sessions == ["trader1"]
        assert any(event == "force_logout" for event, _payload, _room in emitted)
