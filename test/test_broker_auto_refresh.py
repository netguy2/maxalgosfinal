"""Unit tests for broker auto session refresh
(services/broker_auto_refresh_service.py + database/user_db.py helpers).

See docs/plans/2026-07-16-broker-auto-session-refresh-plan.md.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyotp  # noqa: E402
import pytest  # noqa: E402

import database.user_db as user_db  # noqa: E402
import services.broker_auto_refresh_service as svc  # noqa: E402

# A stable base32 seed so pyotp generates deterministic (time-based) codes.
TEST_SEED = "JBSWY3DPEHPK3PXP"


def test_supported_brokers_are_exactly_the_password_totp_three():
    assert user_db.is_auto_refresh_supported("angel")
    assert user_db.is_auto_refresh_supported("fivepaisa")
    assert user_db.is_auto_refresh_supported("motilal")
    # OAuth / Noren-GenAcsTok brokers must NOT be auto-refreshable.
    for broker in ("zerodha", "upstox", "dhan", "fyers", "zebu", "shoonya", "flattrade"):
        assert not user_db.is_auto_refresh_supported(broker)


def test_call_broker_auth_angel_shape(monkeypatch):
    """angel: authenticate_broker(clientcode, pin, totp) -> (token, feed, err)."""
    captured = {}

    class FakeAuthMod:
        @staticmethod
        def authenticate_broker(clientcode, pin, totp):
            captured["args"] = (clientcode, pin, totp)
            return "tok_angel", "feed_angel", None

    monkeypatch.setattr(
        "importlib.import_module", lambda name: FakeAuthMod if "angel" in name else None
    )
    token, feed, err = svc._call_broker_auth(
        "angel", "123456", {"clientcode": "AB1234", "pin": "1111"}
    )
    assert token == "tok_angel"
    assert feed == "feed_angel"
    assert err is None
    assert captured["args"] == ("AB1234", "1111", "123456")


def test_call_broker_auth_fivepaisa_two_tuple(monkeypatch):
    """fivepaisa returns a 2-tuple (token, err) -- feed must normalize to None."""

    class FakeAuthMod:
        @staticmethod
        def authenticate_broker(clientcode, pin, totp):
            return "tok_5p", None

    monkeypatch.setattr("importlib.import_module", lambda name: FakeAuthMod)
    token, feed, err = svc._call_broker_auth(
        "fivepaisa", "654321", {"clientcode": "user@x.com", "pin": "2222"}
    )
    assert token == "tok_5p"
    assert feed is None
    assert err is None


def test_call_broker_auth_motilal_passes_dob(monkeypatch):
    """motilal: authenticate_broker(userid, pin, totp, dob)."""
    captured = {}

    class FakeAuthMod:
        @staticmethod
        def authenticate_broker(userid, pin, totp, dob):
            captured["args"] = (userid, pin, totp, dob)
            return "tok_moti", None, None

    monkeypatch.setattr("importlib.import_module", lambda name: FakeAuthMod)
    token, feed, err = svc._call_broker_auth(
        "motilal", "999999", {"userid": "U1", "pin": "3333", "dob": "01/01/1990"}
    )
    assert token == "tok_moti"
    assert captured["args"] == ("U1", "3333", "999999", "01/01/1990")


def test_call_broker_auth_rejects_unsupported_broker():
    with pytest.raises(ValueError):
        svc._call_broker_auth("zerodha", "123456", {})


def test_refresh_one_success(monkeypatch):
    """Happy path: seed present, broker returns a token -> upsert_auth called,
    result recorded as success."""
    upserted = {}
    recorded = {}

    monkeypatch.setattr(svc, "is_auto_refresh_supported", lambda b: True)
    monkeypatch.setattr(
        svc,
        "get_broker_auto_refresh_secrets",
        lambda u, b: {"totp_seed": TEST_SEED, "login_params": {"clientcode": "C1", "pin": "1234"}},
    )
    # Bypass the credential-context (no Flask/env needed for the fake broker).
    import contextlib

    monkeypatch.setattr(
        "utils.broker_context.broker_credential_context",
        lambda u, b: contextlib.nullcontext(),
    )
    monkeypatch.setattr(
        svc, "_call_broker_auth", lambda b, totp, params: ("fresh_token", "feed", None)
    )
    monkeypatch.setattr(
        "database.auth_db.upsert_auth",
        lambda name, token, broker, feed_token=None: upserted.update(
            {"name": name, "token": token, "broker": broker, "feed": feed_token}
        ),
    )
    monkeypatch.setattr(
        svc, "record_auto_refresh_result", lambda u, b, success: recorded.update({"success": success})
    )

    res = svc.refresh_one("alice", "angel")
    assert res["success"] is True
    assert upserted == {"name": "alice", "token": "fresh_token", "broker": "angel", "feed": "feed"}
    assert recorded == {"success": True}


def test_refresh_one_broker_rejects_triggers_failsafe(monkeypatch):
    """Broker returns an error -> no token stored, failure recorded, failsafe
    notification path invoked (never a silent false-connected state)."""
    recorded = {}
    failsafe_called = {}

    monkeypatch.setattr(svc, "is_auto_refresh_supported", lambda b: True)
    monkeypatch.setattr(
        svc,
        "get_broker_auto_refresh_secrets",
        lambda u, b: {"totp_seed": TEST_SEED, "login_params": {"clientcode": "C1", "pin": "bad"}},
    )
    import contextlib

    monkeypatch.setattr(
        "utils.broker_context.broker_credential_context",
        lambda u, b: contextlib.nullcontext(),
    )
    monkeypatch.setattr(
        svc, "_call_broker_auth", lambda b, totp, params: (None, None, "Invalid credentials")
    )
    monkeypatch.setattr(
        svc, "record_auto_refresh_result", lambda u, b, success: recorded.update({"success": success})
    )
    monkeypatch.setattr(
        svc, "_handle_failure", lambda u, b, reason: failsafe_called.update({"reason": reason})
    )

    res = svc.refresh_one("alice", "angel")
    assert res["success"] is False
    assert "Invalid credentials" in res["error"]
    assert failsafe_called["reason"] == "Invalid credentials"


def test_refresh_one_no_seed_returns_disabled(monkeypatch):
    """Auto-refresh not enabled / no seed -> clean 'not enabled' result, no
    broker call, no crash."""
    monkeypatch.setattr(svc, "is_auto_refresh_supported", lambda b: True)
    monkeypatch.setattr(svc, "get_broker_auto_refresh_secrets", lambda u, b: None)

    res = svc.refresh_one("alice", "angel")
    assert res["success"] is False
    assert "not enabled" in res["error"]


def test_refresh_one_unsupported_broker_is_rejected(monkeypatch):
    monkeypatch.setattr(svc, "is_auto_refresh_supported", lambda b: False)
    res = svc.refresh_one("alice", "zerodha")
    assert res["success"] is False
    assert "not auto-refresh-capable" in res["error"]


def test_totp_seed_generates_valid_code():
    """Sanity: the stored seed produces a 6-digit code (the mechanism the
    whole feature depends on)."""
    code = pyotp.TOTP(TEST_SEED).now()
    assert len(code) == 6
    assert code.isdigit()
