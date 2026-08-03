"""
Regression tests for: logout() must not silently stop running Python
strategies from placing orders.

Root cause: a running Python strategy authenticates via the user's
permanent Max Algos API key (independent of the browser session), but
every order/quote call it makes still resolves through
get_auth_token_broker(api_key), which reads the SAME Auth row that
blueprints/auth.py's logout() route used to unconditionally revoke
(upsert_auth(..., revoke=True)) on every single app logout. The strategy
process stayed "running" with no error surfaced, but every subsequent
order/quote call from it silently failed once the broker token was wiped.

Fix: logout() now checks has_running_strategies_for_user() (new helper in
blueprints/python_strategy.py, live-PID-verified via cleanup_dead_processes())
before revoking, and skips the revoke entirely when the user has any
strategy genuinely still running. The Flask session/cookie is still
cleared either way -- this only affects whether the BROKER connection
stays live, not whether the user is logged out of the website. Explicit
"Disconnect broker" actions (blueprints/broker_credentials.py) are
untouched and always revoke regardless of running strategies, as does the
unrelated daily ~3 AM IST auto-expiry (utils/session.py's
revoke_user_tokens, a genuine broker-side token-expiry constraint, not an
app-logout action).

All DB/process calls are mocked. Nothing hits a live broker or spawns a
real subprocess.
"""

import atexit
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Same DATABASE_URL bootstrap as test_auth_resume.py -- several database/*.py
# modules build their engine from this env var at import time. APP_KEY/
# API_KEY_PEPPER are required (fail-fast) by database/auth_db.py at import
# time too -- setdefault with throwaway values so this file is runnable
# standalone without depending on the ambient shell's .env.
TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_logout_preserves_broker.db"
TEST_DB.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("APP_KEY", "test-app-key-" + "0" * 52)
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-" + "0" * 52)
atexit.register(lambda: TEST_DB.unlink(missing_ok=True))

import restx_api  # noqa: F401,E402 -- same circular-import dodge as other test files

import blueprints.auth as auth_bp_module  # noqa: E402


@pytest.fixture()
def app_context():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    with app.test_request_context("/auth/logout", method="POST"):
        yield


def _make_config(user_id, is_running):
    return {"user_id": user_id, "is_running": is_running, "pid": 12345 if is_running else None}


class TestHasRunningStrategiesForUser:
    def test_counts_only_this_users_running_strategies(self):
        import blueprints.python_strategy as pystrat

        with patch.object(pystrat, "cleanup_dead_processes"), \
             patch.object(pystrat, "STRATEGY_CONFIGS", {
                 "s1": _make_config("alice", True),
                 "s2": _make_config("alice", False),
                 "s3": _make_config("bob", True),
             }):
            count = pystrat.has_running_strategies_for_user("alice")

        assert count == 1

    def test_returns_zero_for_user_with_no_strategies(self):
        import blueprints.python_strategy as pystrat

        with patch.object(pystrat, "cleanup_dead_processes"), \
             patch.object(pystrat, "STRATEGY_CONFIGS", {}):
            count = pystrat.has_running_strategies_for_user("alice")

        assert count == 0

    def test_returns_zero_for_empty_username(self):
        import blueprints.python_strategy as pystrat

        count = pystrat.has_running_strategies_for_user("")
        assert count == 0

    def test_reconciles_stale_flags_via_cleanup_before_counting(self):
        """cleanup_dead_processes() must run BEFORE the count so a
        crashed-but-still-flagged-running strategy doesn't falsely
        preserve the broker token forever."""
        import blueprints.python_strategy as pystrat

        call_order = []

        def fake_cleanup():
            call_order.append("cleanup")
            # Simulate cleanup flipping the stale flag to False.
            pystrat.STRATEGY_CONFIGS["s1"]["is_running"] = False

        with patch.object(pystrat, "cleanup_dead_processes", side_effect=fake_cleanup), \
             patch.object(pystrat, "STRATEGY_CONFIGS", {"s1": _make_config("alice", True)}):
            count = pystrat.has_running_strategies_for_user("alice")

        assert call_order == ["cleanup"]
        assert count == 0


class TestLogoutPreservesBrokerToken:
    def test_logout_skips_revoke_when_strategies_running(self, app_context):
        session["logged_in"] = True
        session["user"] = "alice"

        with patch("blueprints.auth.auth_cache", {}), \
             patch("blueprints.auth.feed_token_cache", {}), \
             patch("database.master_contract_cache_hook.clear_cache_on_logout"), \
             patch("blueprints.python_strategy.has_running_strategies_for_user", return_value=2), \
             patch.object(auth_bp_module, "upsert_auth") as mock_upsert, \
             patch("database.auth_db.clear_user_sessions"), \
             patch("blueprints.auth.socketio"):
            auth_bp_module.logout()

        mock_upsert.assert_not_called()

    def test_logout_still_revokes_when_no_strategies_running(self, app_context):
        session["logged_in"] = True
        session["user"] = "alice"

        fake_auth_row = SimpleNamespace(broker="zerodha")

        with patch("blueprints.auth.auth_cache", {}), \
             patch("blueprints.auth.feed_token_cache", {}), \
             patch("database.master_contract_cache_hook.clear_cache_on_logout"), \
             patch("blueprints.python_strategy.has_running_strategies_for_user", return_value=0), \
             patch("database.auth_db.get_auth_token_dbquery", return_value=fake_auth_row), \
             patch.object(auth_bp_module, "upsert_auth") as mock_upsert, \
             patch("database.auth_db.clear_user_sessions"), \
             patch("blueprints.auth.socketio"):
            mock_upsert.return_value = 1
            auth_bp_module.logout()

        mock_upsert.assert_called_once()
        args, kwargs = mock_upsert.call_args
        assert kwargs.get("revoke") is True or (len(args) >= 4 and args[3] is True)

    def test_flask_session_is_cleared_regardless_of_running_strategies(self, app_context):
        """The website logout itself must still happen even when the
        broker token is preserved -- only the broker-token revocation is
        conditional, not the session clear."""
        session["logged_in"] = True
        session["user"] = "alice"

        with patch("blueprints.auth.auth_cache", {}), \
             patch("blueprints.auth.feed_token_cache", {}), \
             patch("database.master_contract_cache_hook.clear_cache_on_logout"), \
             patch("blueprints.python_strategy.has_running_strategies_for_user", return_value=3), \
             patch.object(auth_bp_module, "upsert_auth"), \
             patch("database.auth_db.clear_user_sessions"), \
             patch("blueprints.auth.socketio"):
            auth_bp_module.logout()

        assert "logged_in" not in session
        assert "user" not in session

    def test_logout_removes_only_this_devices_session_row(self, app_context):
        """Regression test: logout() must remove ONLY the calling device's
        ActiveSession row and force_logout ONLY that device's socket room --
        not every session/device the user is logged in from. The previous
        behaviour called clear_user_sessions() (deletes every row for the
        user) and emitted force_logout to room=f"user_{username}" (every
        connected socket for that user), so logging out on one laptop
        force-logged out every other device too."""
        session["logged_in"] = True
        session["user"] = "alice"
        session["session_id"] = "this-device-session-id"

        with patch("blueprints.auth.auth_cache", {}), \
             patch("blueprints.auth.feed_token_cache", {}), \
             patch("database.master_contract_cache_hook.clear_cache_on_logout"), \
             patch("blueprints.python_strategy.has_running_strategies_for_user", return_value=0), \
             patch("database.auth_db.get_auth_token_dbquery", return_value=None), \
             patch.object(auth_bp_module, "upsert_auth", return_value=1), \
             patch("database.auth_db.clear_user_sessions") as mock_clear_all, \
             patch("database.auth_db.remove_session") as mock_remove_one, \
             patch("database.auth_db.get_active_sessions", return_value=[]), \
             patch("blueprints.auth.socketio") as mock_socketio:
            auth_bp_module.logout()

        # The old blanket wipe must never be called from this route anymore.
        mock_clear_all.assert_not_called()
        # Only this device's own session row is removed.
        mock_remove_one.assert_called_once_with("this-device-session-id")

        # force_logout must be scoped to this device's own room only.
        force_logout_calls = [
            call for call in mock_socketio.emit.call_args_list
            if call.args and call.args[0] == "force_logout"
        ]
        assert len(force_logout_calls) == 1
        assert force_logout_calls[0].kwargs.get("room") == "session_this-device-session-id"


class TestTotpLoginRegistersSession:
    """Regression test for: 2FA-enabled accounts never got an ActiveSession
    row or the new-device security email, because login_totp() (the step
    that actually promotes session["user"]/session["logged_in"] for those
    accounts) never called register_session()/is_known_device() at all --
    only the password-only login() path did. blueprints/auth.py now shares
    that logic via _register_session_and_alert(), called from both places.
    """

    def test_login_totp_registers_session_and_sends_new_device_email(self, app_context):
        from datetime import datetime

        session["pending_totp_user"] = "alice"
        session["pending_totp_started_at"] = datetime.utcnow().isoformat()

        fake_user = SimpleNamespace(
            username="alice", email="alice@example.com", is_admin=True, totp_enabled=True
        )
        fake_user.verify_totp = lambda code: code == "123456"

        with patch("blueprints.auth.SUBSCRIPTION_GATE_ENABLED", False), \
             patch.object(auth_bp_module, "find_user_by_exact_username", return_value=fake_user), \
             patch.object(auth_bp_module, "find_user_by_login_identifier", return_value=fake_user), \
             patch("database.auth_db.log_login_attempt"), \
             patch("database.auth_db.is_known_device", return_value=False) as mock_is_known, \
             patch("database.auth_db.register_session", return_value=True) as mock_register, \
             patch(
                 "services.session_intelligence_service.build_session_intelligence",
                 return_value=None,
             ), \
             patch("utils.email_utils.send_new_device_login_email") as mock_send_email, \
             patch.object(auth_bp_module, "_try_resume_broker_session", return_value=None):
            request_data = {"totp_code": "123456", "client_hints": {"timezone": "Asia/Kolkata"}}
            with patch.object(auth_bp_module.request, "get_json", return_value=request_data):
                auth_bp_module.login_totp()

        assert session.get("user") == "alice"
        assert session.get("logged_in") is True
        mock_is_known.assert_called_once()
        mock_register.assert_called_once()
        assert mock_register.call_args.kwargs.get("username") == "alice"
        mock_send_email.assert_called_once()
        assert mock_send_email.call_args.kwargs.get("recipient_email") == "alice@example.com"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
