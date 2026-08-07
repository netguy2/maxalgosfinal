"""Regression test: a BNR rate-limit throttle must not masquerade as an
expired broker session.

Production symptom: the Signal Delivery Log showed

    Could not resolve option NIFTY ATM PE for expiry 11AUG26 on NFO:
    Failed to fetch LTP for NIFTY. Error fetching quotes:
    Error from Bnr API: Session Expired : Invalid Session Key

on a token that was perfectly valid -- verified by calling BNR's Limits
endpoint directly and getting live account data back, and by re-running the
exact same get_quotes() call successfully moments later.

Cause: BNR enforces ONE shared per-account quota (10/sec, 120/min) across
every endpoint. throttle_bnr_request() waited up to 1.5s for headroom (to
avoid 504s on web workers) and then, if the quota still had not cleared,
SENT THE REQUEST ANYWAY. BNR rejects an over-quota request with an
auth-shaped error, so a temporary throttle surfaced to users as "your
broker session died" -- sending them to re-authenticate a session that was
never broken. The 2523ms latency on the failing signal matches the 1.5s
wait plus the doomed round trip.

Contributing: broker/bnr/api/funds.py made HTTP calls WITHOUT calling the
throttle, so dashboard funds polling consumed quota the limiter never
counted, leaving its own counter under-reporting real usage.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import broker.bnr.api.rate_limiter as rl  # noqa: E402


@pytest.fixture(autouse=True)
def _clear():
    rl._request_times.clear()
    yield
    rl._request_times.clear()


class TestNormalTrafficUnaffected:
    def test_calls_under_quota_do_not_block_or_raise(self):
        start = time.time()
        for _ in range(5):
            rl.throttle_bnr_request()
        assert time.time() - start < 0.5, "under-quota calls must not sleep"
        assert len(rl._request_times) == 5


class TestOverQuotaFailsFastAndHonestly:
    def test_raises_instead_of_sending_a_doomed_request(self):
        """THE regression test. Sending anyway is what made a throttle look
        like an auth failure."""
        rl._request_times.extend([time.time()] * rl._MAX_PER_MIN)

        with pytest.raises(rl.BnrRateLimitExceeded):
            rl.throttle_bnr_request()

    def test_error_says_rate_limit_and_explicitly_not_a_session_problem(self):
        """The whole point of the fix: the message must not send the user
        off to re-authenticate a healthy session."""
        rl._request_times.extend([time.time()] * rl._MAX_PER_MIN)

        with pytest.raises(rl.BnrRateLimitExceeded) as exc:
            rl.throttle_bnr_request()

        msg = str(exc.value).lower()
        assert "rate limit" in msg
        assert "not a login or session problem" in msg
        assert "retry" in msg

    def test_still_bounded_by_the_504_safety_window(self):
        """It must fail fast rather than hanging a web worker."""
        rl._request_times.extend([time.time()] * rl._MAX_PER_MIN)

        start = time.time()
        with pytest.raises(rl.BnrRateLimitExceeded):
            rl.throttle_bnr_request()
        elapsed = time.time() - start

        assert 1.4 < elapsed < 3.0, (
            f"expected to give up shortly after the 1.5s window, took {elapsed:.2f}s"
        )


class TestEveryBnrHttpModuleIsThrottled:
    def test_funds_module_calls_the_shared_throttle(self):
        """BNR's quota is per-account and shared across endpoints, so a
        module that skips the throttle corrupts the limiter's view of real
        usage for every other module."""
        import inspect

        import broker.bnr.api.funds as funds

        source = inspect.getsource(funds.get_margin_data)
        assert "throttle_bnr_request()" in source, (
            "funds.get_margin_data makes an HTTP call to BNR and must call "
            "throttle_bnr_request(); without it, dashboard polling burns quota "
            "the limiter cannot see."
        )

    def test_data_and_order_modules_still_throttle(self):
        for mod_name in ("broker.bnr.api.data", "broker.bnr.api.order_api"):
            src = open(mod_name.replace(".", "/") + ".py", encoding="utf-8").read()
            assert "throttle_bnr_request()" in src, f"{mod_name} lost its throttle call"
