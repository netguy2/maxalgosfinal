"""Regression test for a real bug found in a code audit: kill-switch and
Master SL/Target cleanup call close_position()/cancel_all_orders() with
only (auth_token, broker) -- no api_key, since these are internal calls
using a broker session the monitor already holds, not an external API
request. Both functions resolve the acting user for the per-user Analyze
Mode check via `username_from_api_key(api_key)`, which is None here, so
get_analyze_mode(None) silently fell back to Live Mode regardless of the
user's actual setting.

Concretely: a user with Analyze Mode ON hits their kill switch or Master
SL/Target. The cleanup path is supposed to close their SANDBOX positions
(since that's where their real trading was happening), but instead it
tried to close LIVE broker positions -- a silent no-op if they have none,
which defeats the entire point of an emergency-stop / risk-limit feature.

Fix: close_position()/close_position_with_auth() and cancel_all_orders()/
cancel_all_orders_with_auth() now accept an explicit `username` parameter
that internal callers (kill_switch_service.py, master_risk_monitor_service.py
-- both of which already have the username in scope) pass through, taking
priority over the api_key-based resolution.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.cancel_all_order_service as cancel_all_order_service  # noqa: E402
import services.close_position_service as close_position_service  # noqa: E402

USER_A = "__test_ks_analyze_user_a__"


class TestCloseSpositionThreadsUsernameForAnalyzeModeCheck:
    def test_internal_call_passes_username_to_get_analyze_mode(self):
        """THE regression test: an internal (auth_token+broker, no
        api_key) call must resolve Analyze Mode using the explicit
        username, not silently resolve to None/Live Mode."""
        seen_usernames = []

        def fake_get_analyze_mode(username=None):
            seen_usernames.append(username)
            return False

        with patch.object(
            close_position_service, "get_analyze_mode", side_effect=fake_get_analyze_mode
        ), patch.object(
            close_position_service, "import_broker_module", return_value=None
        ):
            close_position_service.close_position(
                auth_token="tok", broker="zerodha", username=USER_A
            )

        assert USER_A in seen_usernames, (
            f"get_analyze_mode was never called with the explicit username "
            f"{USER_A!r} -- got calls with: {seen_usernames!r}"
        )

    def test_internal_call_without_username_still_works_but_resolves_none(self):
        """Backward compatibility: omitting username must not raise --
        just falls back to the old (broken for this call path) behavior."""
        with patch.object(
            close_position_service, "get_analyze_mode", return_value=False
        ) as mock_gam, patch.object(
            close_position_service, "import_broker_module", return_value=None
        ):
            close_position_service.close_position(auth_token="tok", broker="zerodha")

        mock_gam.assert_called_with(None)


class TestCancelAllOrdersThreadsUsernameForAnalyzeModeCheck:
    def test_internal_call_passes_username_to_get_analyze_mode(self):
        seen_usernames = []

        def fake_get_analyze_mode(username=None):
            seen_usernames.append(username)
            return False

        with patch.object(
            cancel_all_order_service, "get_analyze_mode", side_effect=fake_get_analyze_mode
        ), patch.object(
            cancel_all_order_service, "import_broker_module", return_value=None
        ):
            cancel_all_order_service.cancel_all_orders(
                auth_token="tok", broker="zerodha", username=USER_A
            )

        assert USER_A in seen_usernames, (
            f"get_analyze_mode was never called with the explicit username "
            f"{USER_A!r} -- got calls with: {seen_usernames!r}"
        )


class TestKillSwitchAndMasterRiskCallersPassUsername:
    """Confirm the two real callers that motivated this fix actually pass
    username through, not just that the plumbing supports it."""

    def test_kill_switch_service_passes_username_to_close_position(self):
        import inspect

        import services.kill_switch_service as kss

        source = inspect.getsource(kss._cleanup_live_orders_and_positions)
        assert "close_position(" in source
        assert "username=username" in source, (
            "kill_switch_service._cleanup_live_orders_and_positions must pass "
            "username=username to close_position() -- it already has the "
            "username in scope as its own function parameter."
        )
        assert "cancel_all_orders(" in source
        # Both call sites in this function must thread username through.
        assert source.count("username=username") >= 2

    def test_master_risk_monitor_passes_username_to_close_position(self):
        import inspect

        import services.master_risk_monitor_service as mrm

        source = inspect.getsource(mrm._close_all_positions)
        assert "close_position(" in source
        assert "username=username" in source, (
            "master_risk_monitor_service._close_all_positions must pass "
            "username=username to close_position() -- it already has the "
            "username in scope as its own function parameter."
        )
