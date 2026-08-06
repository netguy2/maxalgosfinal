"""Per-user isolation tests for Analyze (sandbox) Mode.

Analyze Mode used to live on the single global `Settings.analyze_mode` row,
read/written by a zero-argument get_analyze_mode()/set_analyze_mode() pair.
Any user flipping it switched sandbox/live execution for EVERY account on
the instance, and toggling it also started/stopped the shared
execution-engine and square-off background threads platform-wide. A second
user logging into a different account could see Analyze Mode "randomly"
enabled because some other user (or a stale admin session) had flipped the
global flag.

This moved analyze_mode onto the per-user UserRiskSettings table (same
table that already holds kill_switch_active and master_risk_enabled), and
get_analyze_mode()/set_analyze_mode() now take an explicit `username` (with
a Flask-session fallback for the ~52 call sites that run inside a request).
The execution engine and square-off scheduler now run unconditionally at
startup and internally iterate list_analyze_mode_users() instead of a
single global on/off switch.

These tests pin the per-user contract so it cannot silently regress back to
a shared global flag.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from flask import Flask, session  # noqa: E402

import database.settings_db as settings_db  # noqa: E402

USER_A = "__test_am_user_a__"
USER_B = "__test_am_user_b__"


def _purge(*usernames):
    for username in usernames:
        settings_db.db_session.query(settings_db.UserRiskSettings).filter_by(
            username=username
        ).delete()
    settings_db.db_session.commit()


def _app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    return app


@pytest.fixture(autouse=True)
def _clean():
    _purge(USER_A, USER_B)
    settings_db._settings_cache.clear()
    yield
    _purge(USER_A, USER_B)
    settings_db._settings_cache.clear()


# ---------------------------------------------------------------------
# get_analyze_mode / set_analyze_mode isolation
# ---------------------------------------------------------------------


def test_defaults_to_live_mode_for_new_user():
    assert settings_db.get_analyze_mode(USER_A) is False


def test_no_resolvable_username_defaults_to_live_mode():
    """No explicit username and no Flask request context to fall back to
    must read as Live (the safer mode), never crash and never silently
    inherit some other user's setting."""
    assert settings_db.get_analyze_mode(None) is False


def test_one_users_toggle_does_not_leak_to_another():
    """THE regression test: A enabling Analyze Mode must leave B on Live."""
    settings_db.set_analyze_mode(True, USER_A)

    assert settings_db.get_analyze_mode(USER_A) is True
    assert settings_db.get_analyze_mode(USER_B) is False


def test_disabling_one_user_does_not_affect_the_other():
    settings_db.set_analyze_mode(True, USER_A)
    settings_db.set_analyze_mode(True, USER_B)

    settings_db.set_analyze_mode(False, USER_A)

    assert settings_db.get_analyze_mode(USER_A) is False
    assert settings_db.get_analyze_mode(USER_B) is True


def test_set_analyze_mode_without_username_raises_outside_request_context():
    """A write with no resolvable identity must fail loudly, not silently
    no-op while looking like it succeeded in the UI."""
    with pytest.raises(ValueError):
        settings_db.set_analyze_mode(True, None)


def test_set_analyze_mode_falls_back_to_flask_session_user():
    """The ~52 call sites across services/blueprints never pass a username
    explicitly for reads inside a request -- they rely on the session
    fallback. Confirm both get and set use it correctly."""
    with _app().test_request_context("/"):
        session["user"] = USER_A
        settings_db.set_analyze_mode(True)
        assert settings_db.get_analyze_mode() is True

    # Outside that request context, USER_A's row is still per-user, not global.
    assert settings_db.get_analyze_mode(USER_B) is False
    assert settings_db.get_analyze_mode(USER_A) is True


def test_cache_is_scoped_per_user():
    """The 1-hour TTL cache key must include the username -- otherwise the
    second user's read would return the first user's cached value."""
    settings_db.set_analyze_mode(True, USER_A)
    settings_db.get_analyze_mode(USER_A)  # warm the cache for A

    assert settings_db.get_analyze_mode(USER_B) is False


def test_list_analyze_mode_users_returns_only_enabled_users():
    settings_db.set_analyze_mode(True, USER_A)
    settings_db.set_analyze_mode(False, USER_B)

    enabled = settings_db.list_analyze_mode_users()

    assert USER_A in enabled
    assert USER_B not in enabled


# ---------------------------------------------------------------------
# Migration: legacy global Settings.analyze_mode adoption
# ---------------------------------------------------------------------


class TestLegacyMigrationIsOneShot:
    """_migrate_analyze_mode_to_user_risk_settings() adopts the old global
    Settings.analyze_mode value for the account that owned the legacy
    global toggle, then must flip the legacy flag off so it never
    re-adopts on a later cold start after the user has explicitly turned
    Analyze Mode back off.

    The adoption target is resolved via `Auth.query.filter_by(is_revoked=
    False).first()` (mirrors _migrate_user_risk_settings' existing-account
    resolution) -- monkeypatched here rather than touching the real `auth`
    table, to keep this test isolated from actual broker accounts.
    """

    def test_migration_is_idempotent_and_does_not_resurrect_after_disable(self, monkeypatch):
        from database.auth_db import Auth

        class _FakeOwner:
            name = USER_A

        monkeypatch.setattr(
            Auth, "query", type("Q", (), {"filter_by": lambda *a, **k: type(
                "F", (), {"first": staticmethod(lambda: _FakeOwner())}
            )()})()
        )

        # Simulate: legacy global flag was ON.
        legacy = settings_db._get_settings_row(create=True)
        legacy.analyze_mode = True
        settings_db.db_session.commit()

        settings_db._migrate_analyze_mode_to_user_risk_settings()

        # Adopted onto the resolved owner's per-user row.
        assert settings_db.get_analyze_mode(USER_A) is True

        # Legacy marker must be consumed (flipped off) so a second run is a no-op.
        settings_db.db_session.refresh(legacy)
        assert legacy.analyze_mode is False

        # Now simulate the user explicitly disabling Analyze Mode after adoption.
        settings_db.set_analyze_mode(False, USER_A)

        # A second cold-start run of the migration must NOT resurrect it --
        # this is the in-memory-cache-as-marker bug that was caught and fixed
        # before ever shipping.
        settings_db._migrate_analyze_mode_to_user_risk_settings()
        assert settings_db.get_analyze_mode(USER_A) is False
