"""
Regression tests for the WebSocket proxy's auto-recovery fix.

Root cause: every login/re-login publishes a ZeroMQ cache-invalidation
message that websocket_proxy/server.py's _handle_cache_invalidation
unconditionally tears down the user's live broker adapter for (needed so
the next broker call uses the fresh token). Previously nothing ever
rebuilt that adapter for a browser tab that was ALREADY authenticated and
streaming -- authenticate_client only rebuilds on a fresh "authenticate"
message from the browser, which an already-open tab never sends on its
own. Net effect: after any broker re-login (including the routine ~3 AM
IST daily token rollover), live ticks silently stopped updating forever,
with the UI still showing "Live"/"Connected", until the user manually
reloaded the page.

Fix: _handle_cache_invalidation now triggers
_rebuild_adapter_and_resubscribe (fire-and-forget background task, so it
never blocks the shared tick-processing loop for other users) which
rebuilds the adapter and replays every affected client's stored
subscriptions -- fully server-side, no user action, no message the
frontend needs to react to. It explicitly refuses to reconnect a
logged-out (is_revoked) session.

No pytest-asyncio plugin is installed in this project (confirmed absent),
so async methods are driven directly via asyncio.run() inside plain sync
test functions, matching this repo's other async code (see
utils/broker_context.py's contextvars pattern used the same way elsewhere).

All broker/network calls are mocked. Nothing hits a live broker or a real
ZMQ/WebSocket connection.
"""

import asyncio
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import restx_api  # noqa: F401 -- same circular-import dodge as other test files
import websocket_proxy  # noqa: F401

from websocket_proxy.server import WebSocketProxy


def make_proxy():
    """A WebSocketProxy-shaped object with only the state the methods under
    test touch, avoiding __init__'s real ZMQ socket connect / port-in-use
    check. Bind the real unbound methods so we're testing actual
    production code, not reimplemented logic."""
    proxy = SimpleNamespace()
    proxy.clients = {}
    proxy.broker_adapters = {}
    proxy.adapter_token_hashes = {}
    proxy.user_mapping = {}
    proxy.user_broker_mapping = {}
    proxy.subscriptions = {}
    proxy._run_broker_call = WebSocketProxy._run_broker_call
    proxy._rebuild_adapter_and_resubscribe = WebSocketProxy._rebuild_adapter_and_resubscribe.__get__(proxy)
    proxy._handle_cache_invalidation = WebSocketProxy._handle_cache_invalidation.__get__(proxy)
    proxy.authenticate_client = WebSocketProxy.authenticate_client.__get__(proxy)
    proxy.send_message = WebSocketProxy.send_message.__get__(proxy)
    proxy.send_error = WebSocketProxy.send_error.__get__(proxy)
    proxy._is_auth_error_exception = WebSocketProxy._is_auth_error_exception.__get__(proxy)
    proxy._clear_auth_cache_for_user = WebSocketProxy._clear_auth_cache_for_user.__get__(proxy)
    return proxy


def make_client_socket():
    """A fake client websocket whose .send() is a real awaitable coroutine
    (unlike a bare MagicMock, which can't be awaited) so authenticate_client's
    send_message/send_error calls succeed instead of raising inside the
    except websockets.exceptions.ConnectionClosed handler."""
    ws = MagicMock()
    ws.send = AsyncMock()
    return ws


def make_subscription(symbol="SBIN", exchange="NSE", mode=2, depth_level=5):
    return json.dumps({
        "symbol": symbol, "exchange": exchange, "mode": mode,
        "depth_level": depth_level, "broker": "zerodha",
    })


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. Core fix: adapter is rebuilt and subscriptions replayed automatically
# ---------------------------------------------------------------------------

class TestAutoRecoveryRebuildsAdapterAndResubscribes:
    def test_rebuild_recreates_adapter_and_replays_subscriptions(self):
        proxy = make_proxy()
        client_id = "client-1"
        user_id = "testuser"
        proxy.user_mapping[client_id] = user_id
        proxy.subscriptions[client_id] = {make_subscription("SBIN"), make_subscription("INFY")}

        mock_adapter = MagicMock()
        mock_adapter.initialize.return_value = {"status": "success"}
        mock_adapter.connect.return_value = {"status": "success"}
        mock_adapter.subscribe.return_value = {"status": "success"}

        fake_auth_row = SimpleNamespace(is_revoked=False)

        with patch("websocket_proxy.server.create_broker_adapter", return_value=mock_adapter), \
             patch("database.auth_db.Auth") as mock_auth_model, \
             patch("database.auth_db.get_auth_token", return_value="fresh-token-xyz"):
            mock_auth_model.query.filter_by.return_value.first.return_value = fake_auth_row

            result = run(proxy._rebuild_adapter_and_resubscribe(user_id, "zerodha"))

        assert result is True
        assert proxy.broker_adapters[user_id] is mock_adapter
        mock_adapter.initialize.assert_called_once()
        mock_adapter.connect.assert_called_once()
        assert mock_adapter.subscribe.call_count == 2, (
            "Expected both stored subscriptions (SBIN, INFY) to be replayed "
            "against the freshly rebuilt adapter."
        )

    def test_rebuild_replays_subscriptions_for_multiple_clients_of_same_user(self):
        """A user with two open browser tabs (two client_ids) must have
        BOTH tabs' subscriptions replayed, not just one."""
        proxy = make_proxy()
        user_id = "testuser"
        proxy.user_mapping["client-tab-1"] = user_id
        proxy.user_mapping["client-tab-2"] = user_id
        proxy.subscriptions["client-tab-1"] = {make_subscription("SBIN")}
        proxy.subscriptions["client-tab-2"] = {make_subscription("TCS")}

        mock_adapter = MagicMock()
        mock_adapter.initialize.return_value = {"status": "success"}
        mock_adapter.connect.return_value = {"status": "success"}
        mock_adapter.subscribe.return_value = {"status": "success"}

        fake_auth_row = SimpleNamespace(is_revoked=False)

        with patch("websocket_proxy.server.create_broker_adapter", return_value=mock_adapter), \
             patch("database.auth_db.Auth") as mock_auth_model, \
             patch("database.auth_db.get_auth_token", return_value="fresh-token"):
            mock_auth_model.query.filter_by.return_value.first.return_value = fake_auth_row

            result = run(proxy._rebuild_adapter_and_resubscribe(user_id, "zerodha"))

        assert result is True
        subscribed_symbols = {call.args[0] for call in mock_adapter.subscribe.call_args_list}
        assert subscribed_symbols == {"SBIN", "TCS"}

    def test_rebuild_retries_once_on_auth_error_during_initialize(self):
        """Mirrors authenticate_client's own retry-with-fresh-token
        behavior for an auth error surfaced during adapter.initialize()."""
        proxy = make_proxy()
        user_id = "testuser"
        proxy.user_mapping["client-1"] = user_id
        proxy.subscriptions["client-1"] = {make_subscription("SBIN")}

        mock_adapter = MagicMock()
        mock_adapter.is_auth_error.return_value = True
        mock_adapter.initialize.side_effect = [
            {"status": "error", "message": "401 Unauthorized"},
            {"status": "success"},
        ]
        mock_adapter.connect.return_value = {"status": "success"}
        mock_adapter.subscribe.return_value = {"status": "success"}

        fake_auth_row = SimpleNamespace(is_revoked=False)

        with patch("websocket_proxy.server.create_broker_adapter", return_value=mock_adapter), \
             patch("database.auth_db.Auth") as mock_auth_model, \
             patch("database.auth_db.get_auth_token", return_value="fresh-token"):
            mock_auth_model.query.filter_by.return_value.first.return_value = fake_auth_row

            result = run(proxy._rebuild_adapter_and_resubscribe(user_id, "zerodha"))

        assert result is True
        assert mock_adapter.initialize.call_count == 2
        mock_adapter.clear_auth_cache_for_user.assert_called_once_with(user_id)

    def test_rebuild_returns_false_when_connect_fails(self):
        """A broker-side connect failure (broker feed genuinely down, bad
        credentials that survived the auth-error retry) must not silently
        pretend to succeed -- caller gets False, adapter is not stored."""
        proxy = make_proxy()
        user_id = "testuser"
        proxy.user_mapping["client-1"] = user_id
        proxy.subscriptions["client-1"] = {make_subscription("SBIN")}

        mock_adapter = MagicMock()
        mock_adapter.initialize.return_value = {"status": "success"}
        mock_adapter.connect.return_value = {"status": "error", "message": "connection refused"}

        fake_auth_row = SimpleNamespace(is_revoked=False)

        with patch("websocket_proxy.server.create_broker_adapter", return_value=mock_adapter), \
             patch("database.auth_db.Auth") as mock_auth_model:
            mock_auth_model.query.filter_by.return_value.first.return_value = fake_auth_row

            result = run(proxy._rebuild_adapter_and_resubscribe(user_id, "zerodha"))

        assert result is False
        assert user_id not in proxy.broker_adapters
        mock_adapter.subscribe.assert_not_called()

    def test_one_failed_resubscribe_does_not_abort_the_others(self):
        """A single symbol failing to resubscribe (e.g. delisted, broker
        rejects it) must not prevent every other symbol from being
        restored -- same isolation principle as the earlier
        close_all_positions/cancel_all_orders_api fixes in this codebase."""
        proxy = make_proxy()
        user_id = "testuser"
        proxy.user_mapping["client-1"] = user_id
        proxy.subscriptions["client-1"] = {
            make_subscription("GOODSTOCK"), make_subscription("BADSTOCK"),
        }

        mock_adapter = MagicMock()
        mock_adapter.initialize.return_value = {"status": "success"}
        mock_adapter.connect.return_value = {"status": "success"}

        def fake_subscribe(symbol, exchange, mode, depth_level):
            if symbol == "BADSTOCK":
                return {"status": "error", "message": "symbol not found"}
            return {"status": "success"}

        mock_adapter.subscribe.side_effect = fake_subscribe

        fake_auth_row = SimpleNamespace(is_revoked=False)

        with patch("websocket_proxy.server.create_broker_adapter", return_value=mock_adapter), \
             patch("database.auth_db.Auth") as mock_auth_model:
            mock_auth_model.query.filter_by.return_value.first.return_value = fake_auth_row

            result = run(proxy._rebuild_adapter_and_resubscribe(user_id, "zerodha"))

        assert result is True, "the adapter itself connected fine; a per-symbol resub failure isn't fatal"
        assert mock_adapter.subscribe.call_count == 2, "both symbols must still be attempted"


# ---------------------------------------------------------------------------
# 2. Never auto-reconnect a session the user explicitly logged out of
# ---------------------------------------------------------------------------

class TestAutoRecoveryRefusesRevokedSessions:
    def test_does_not_reconnect_when_session_is_revoked(self):
        """upsert_auth(..., revoke=True) (explicit logout) fires the exact
        same cache-invalidation path as a fresh re-login -- the helper must
        check is_revoked directly and refuse to reconnect, otherwise a
        logout would silently keep the live feed running."""
        proxy = make_proxy()
        user_id = "testuser"

        mock_adapter = MagicMock()
        fake_auth_row = SimpleNamespace(is_revoked=True)

        with patch("websocket_proxy.server.create_broker_adapter", return_value=mock_adapter) as mock_create, \
             patch("database.auth_db.Auth") as mock_auth_model:
            mock_auth_model.query.filter_by.return_value.first.return_value = fake_auth_row

            result = run(proxy._rebuild_adapter_and_resubscribe(user_id, "zerodha"))

        assert result is False
        mock_create.assert_not_called()
        assert user_id not in proxy.broker_adapters

    def test_does_not_reconnect_when_no_auth_row_exists(self):
        """No Auth row at all (never logged in, or deleted) must also
        refuse to reconnect, not crash or silently proceed."""
        proxy = make_proxy()
        user_id = "ghostuser"

        with patch("websocket_proxy.server.create_broker_adapter") as mock_create, \
             patch("database.auth_db.Auth") as mock_auth_model:
            mock_auth_model.query.filter_by.return_value.first.return_value = None

            result = run(proxy._rebuild_adapter_and_resubscribe(user_id, "zerodha"))

        assert result is False
        mock_create.assert_not_called()

    def test_db_check_failure_fails_closed_not_open(self):
        """If checking is_revoked itself raises (DB hiccup), the helper
        must fail CLOSED (do not reconnect) rather than assume it's safe to
        proceed -- reconnecting on an unverifiable session state risks
        streaming a logged-out user's feed."""
        proxy = make_proxy()
        user_id = "testuser"

        with patch("websocket_proxy.server.create_broker_adapter") as mock_create, \
             patch("database.auth_db.Auth") as mock_auth_model:
            mock_auth_model.query.filter_by.side_effect = RuntimeError("db unavailable")

            result = run(proxy._rebuild_adapter_and_resubscribe(user_id, "zerodha"))

        assert result is False
        mock_create.assert_not_called()


# ---------------------------------------------------------------------------
# 3. _handle_cache_invalidation wiring: triggers rebuild only when there's
#    an actual connected client to recover, and never blocks other users.
# ---------------------------------------------------------------------------

class TestHandleCacheInvalidationWiring:
    def test_triggers_rebuild_when_user_has_connected_client(self):
        proxy = make_proxy()
        user_id = "testuser"
        proxy.user_mapping["client-1"] = user_id
        proxy.user_broker_mapping[user_id] = "zerodha"
        proxy.broker_adapters[user_id] = MagicMock()  # the "stale" adapter being torn down

        message = json.dumps({"user_id": user_id, "cache_type": "ALL"})
        mock_rebuild = AsyncMock(return_value=True)
        proxy._rebuild_adapter_and_resubscribe = mock_rebuild

        with patch("database.auth_db.auth_cache"), \
             patch("database.auth_db.broker_cache"), \
             patch("database.auth_db.feed_token_cache"), \
             patch("database.auth_db.verified_api_key_cache"), \
             patch("database.auth_db.invalid_api_key_cache"), \
             patch("websocket_proxy.broker_factory.cleanup_pools_for_user", return_value=0):
            run(proxy._handle_cache_invalidation("CACHE_INVALIDATE_ALL_testuser", message))

        mock_rebuild.assert_called_once_with(user_id, "zerodha")
        assert user_id not in proxy.broker_adapters, "old adapter must still be torn down first"

    def test_does_not_trigger_rebuild_when_no_connected_client(self):
        """A user with no open browser tab (e.g. logging in from a fresh
        session with nothing else connected) shouldn't trigger a wasted
        broker rebuild attempt -- nothing is there to recover."""
        proxy = make_proxy()
        user_id = "testuser"
        # No entry in proxy.user_mapping for this user.
        proxy.user_broker_mapping[user_id] = "zerodha"

        message = json.dumps({"user_id": user_id, "cache_type": "ALL"})
        mock_rebuild = AsyncMock(return_value=True)
        proxy._rebuild_adapter_and_resubscribe = mock_rebuild

        with patch("database.auth_db.auth_cache"), \
             patch("database.auth_db.broker_cache"), \
             patch("database.auth_db.feed_token_cache"), \
             patch("database.auth_db.verified_api_key_cache"), \
             patch("database.auth_db.invalid_api_key_cache"), \
             patch("websocket_proxy.broker_factory.cleanup_pools_for_user", return_value=0):
            run(proxy._handle_cache_invalidation("CACHE_INVALIDATE_ALL_testuser", message))

        mock_rebuild.assert_not_called()

    def test_zmq_listener_dispatches_cache_invalidation_as_background_task_not_awaited(self):
        """The critical non-blocking property: zmq_listener must schedule
        _handle_cache_invalidation via ensure_future (fire-and-forget), NOT
        await it inline -- awaiting inline would stall tick delivery to
        every other connected user for the duration of one user's broker
        adapter rebuild (a real network round-trip). Verified by source
        inspection: the exact failure mode (blocking the shared loop) can't
        be distinguished from correct behavior by mocking alone within a
        single test process, so this pins the actual dispatch mechanism."""
        import inspect

        source = inspect.getsource(WebSocketProxy.zmq_listener)
        assert "aio.ensure_future(" in source, (
            "Expected zmq_listener to dispatch _handle_cache_invalidation via "
            "aio.ensure_future (fire-and-forget) -- if this is now an inline "
            "'await self._handle_cache_invalidation(...)', every other "
            "connected user's ticks would stall during adapter rebuilds."
        )
        assert "await self._handle_cache_invalidation(" not in source

    def test_done_callback_logs_unhandled_task_exceptions(self):
        """The fire-and-forget task's exception must not be silently
        dropped -- confirms _log_cache_invalidation_task_error actually
        logs when the background task raised."""
        async def _boom():
            raise RuntimeError("simulated rebuild crash")

        async def _drive():
            task = asyncio.ensure_future(_boom())
            task.add_done_callback(WebSocketProxy._log_cache_invalidation_task_error)
            with pytest.raises(RuntimeError):
                await task

        with patch("websocket_proxy.server.logger") as mock_logger:
            run(_drive())

        mock_logger.exception.assert_called_once()


# ---------------------------------------------------------------------------
# 4. Scaling: admission control caps concurrent NEW users, and daily
#    mass-reconnect (~3 AM IST token rollover) is staggered with jitter so
#    up to ~1000 users' adapters don't all reconnect in the same instant.
# ---------------------------------------------------------------------------

class TestAdmissionControl:
    def test_rejects_new_user_past_capacity(self):
        proxy = make_proxy()
        # Fill capacity with existing users who already hold adapters.
        for i in range(3):
            proxy.broker_adapters[f"existing_user_{i}"] = MagicMock()
        proxy.clients["client-new"] = make_client_socket()

        with patch.dict(os.environ, {"MAX_CONCURRENT_WS_USERS": "3"}), \
             patch("websocket_proxy.server.verify_api_key", return_value="new_user"):
            run(proxy.authenticate_client("client-new", {"api_key": "somekey"}))

        assert "new_user" not in proxy.user_mapping, (
            "a rejected user must not be recorded as authenticated"
        )
        sent = json.loads(proxy.clients["client-new"].send.call_args[0][0])
        assert sent["code"] == "CAPACITY_EXCEEDED"

    def test_allows_existing_user_reconnect_even_at_capacity(self):
        """A user who ALREADY has an adapter (e.g. opening a second browser
        tab) must not be blocked by the cap -- they aren't new capacity
        demand. Only NEW users past the limit should be rejected."""
        proxy = make_proxy()
        proxy.broker_adapters["testuser"] = MagicMock()
        proxy.user_broker_mapping["testuser"] = "zerodha"
        proxy.adapter_token_hashes["testuser"] = None
        proxy.clients["client-second-tab"] = make_client_socket()

        mock_adapter = proxy.broker_adapters["testuser"]
        mock_adapter.connected = True

        with patch.dict(os.environ, {"MAX_CONCURRENT_WS_USERS": "1"}), \
             patch("websocket_proxy.server.verify_api_key", return_value="testuser"), \
             patch("websocket_proxy.server.get_broker_name", return_value="zerodha"), \
             patch("database.auth_db.get_auth_token", return_value="sometoken"):
            run(proxy.authenticate_client("client-second-tab", {"api_key": "somekey"}))

        assert proxy.user_mapping.get("client-second-tab") == "testuser", (
            "an existing user's second connection must not be rejected by "
            "the capacity cap even when the process is already at the limit"
        )

    def test_allows_new_user_under_capacity(self):
        proxy = make_proxy()
        proxy.clients["client-new"] = make_client_socket()

        mock_adapter = MagicMock()
        mock_adapter.initialize.return_value = {"status": "success"}
        mock_adapter.connect.return_value = {"status": "success"}

        with patch.dict(os.environ, {"MAX_CONCURRENT_WS_USERS": "1000"}), \
             patch("websocket_proxy.server.verify_api_key", return_value="new_user"), \
             patch("websocket_proxy.server.get_broker_name", return_value="zerodha"), \
             patch("websocket_proxy.server.create_broker_adapter", return_value=mock_adapter), \
             patch("database.auth_db.get_auth_token", return_value="sometoken"):
            run(proxy.authenticate_client("client-new", {"api_key": "somekey"}))

        assert proxy.user_mapping.get("client-new") == "new_user"
        assert "new_user" in proxy.broker_adapters


class TestReconnectJitter:
    def test_jitter_delay_is_bounded_by_env_var(self):
        """Confirms the jitter sleep duration respects
        WS_RECONNECT_JITTER_SECONDS rather than an unbounded/hardcoded
        value, and that it's actually invoked (not dead code)."""
        proxy = make_proxy()
        user_id = "testuser"
        proxy.user_mapping["client-1"] = user_id
        proxy.subscriptions["client-1"] = set()

        mock_adapter = MagicMock()
        mock_adapter.initialize.return_value = {"status": "success"}
        mock_adapter.connect.return_value = {"status": "success"}
        fake_auth_row = SimpleNamespace(is_revoked=False)

        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch.dict(os.environ, {"WS_RECONNECT_JITTER_SECONDS": "5"}), \
             patch("websocket_proxy.server.create_broker_adapter", return_value=mock_adapter), \
             patch("database.auth_db.Auth") as mock_auth_model, \
             patch("database.auth_db.get_auth_token", return_value="fresh-token"), \
             patch("websocket_proxy.server.aio.sleep", side_effect=fake_sleep):
            mock_auth_model.query.filter_by.return_value.first.return_value = fake_auth_row

            run(proxy._rebuild_adapter_and_resubscribe(user_id, "zerodha"))

        assert len(sleep_calls) == 1
        assert 0 <= sleep_calls[0] <= 5

    def test_jitter_disabled_when_env_var_is_zero(self):
        """WS_RECONNECT_JITTER_SECONDS=0 must skip the sleep entirely
        (useful for tests/dev where the delay is undesirable)."""
        proxy = make_proxy()
        user_id = "testuser"
        proxy.user_mapping["client-1"] = user_id
        proxy.subscriptions["client-1"] = set()

        mock_adapter = MagicMock()
        mock_adapter.initialize.return_value = {"status": "success"}
        mock_adapter.connect.return_value = {"status": "success"}
        fake_auth_row = SimpleNamespace(is_revoked=False)

        with patch.dict(os.environ, {"WS_RECONNECT_JITTER_SECONDS": "0"}), \
             patch("websocket_proxy.server.create_broker_adapter", return_value=mock_adapter), \
             patch("database.auth_db.Auth") as mock_auth_model, \
             patch("database.auth_db.get_auth_token", return_value="fresh-token"), \
             patch("websocket_proxy.server.aio.sleep") as mock_sleep:
            mock_auth_model.query.filter_by.return_value.first.return_value = fake_auth_row

            run(proxy._rebuild_adapter_and_resubscribe(user_id, "zerodha"))

        mock_sleep.assert_not_called()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
