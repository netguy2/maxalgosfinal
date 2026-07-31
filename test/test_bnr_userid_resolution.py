"""Regression tests for: BNR webhook orders "triggered but never placed."

Root cause: broker/bnr/api/order_api.py's place_order_api() (and several
sibling functions in the same file, plus broker/bnr/api/data.py and
broker/bnr/api/funds.py) resolved the trading user ID with a naive

    full_api_key = os.getenv("BROKER_API_KEY")
    api_key = full_api_key.split(":::")[0]

os.getenv("BROKER_API_KEY") is monkeypatched (utils/env_patch.py) to
resolve per-user credentials, but only when EITHER an active
broker_credential_context override is set OR a Flask request/session
context is present. MaxHook webhook signals are processed on
signal_engine.py's async worker THREAD -- broker_credential_context IS set
there (see signal_engine.py's `with broker_credential_context(...)`), but
if that resolution didn't produce a value for any reason (env var falls
back to `.env`'s literal BROKER_API_KEY, which is None/empty on a fresh
install, or the user has multiple brokers connected and BNR isn't the
current data broker), os.getenv returned None and
`full_api_key.split(":::")` raised an unhandled AttributeError --
place_order_api never made it to the broker's API at all. Caught by
services/place_order_service.py's outer try/except as a generic 500
"internal error", which is why the delivery log showed the signal was
"processed" (an order WAS attempted) while nothing ever reached BNR's
orderbook -- not even a rejected order.

Zebu (broker/zebu/api/order_api.py) already went through this exact fix:
get_zebu_userid() resolves the user ID from (1) AuthBrokerSession/Auth DB
rows matched by auth token, (2) UserBrokerCredential, (3) the env var,
(4) a caller-supplied fallback -- falling threading through cleanly with
an empty string (not a crash) if nothing resolves. This applies the
identical pattern to BNR as get_bnr_userid().

Separately: place_order_api's new "can't resolve -- return (None, err, None)
without ever calling the broker" path exposed a second, previously
unreachable bug in services/place_order_service.py: `res.status == 200`
raises AttributeError when res is None. Fixed there too, with a test below.

All DB/network calls are mocked -- nothing hits a live broker.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_KEY", "test-app-key-" + "0" * 52)
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-" + "0" * 52)

import pytest  # noqa: E402

import restx_api  # noqa: F401,E402 -- circular-import dodge, same as other test files

import broker.bnr.api.order_api as bnr_order_api  # noqa: E402


class TestGetBnrUserid:
    def test_resolves_from_auth_broker_session_by_token_match(self, monkeypatch):
        fake_session = MagicMock(auth="encrypted-token", user_id="ITC1441", is_revoked=False)

        class FakeQuery:
            def filter_by(self, **kwargs):
                assert kwargs == {"broker": "bnr", "is_revoked": False}
                return self

            def all(self):
                return [fake_session]

        fake_auth_db = MagicMock()
        fake_auth_db.AuthBrokerSession.query = FakeQuery()
        fake_auth_db.Auth.query.filter_by.return_value.all.return_value = []
        fake_auth_db.decrypt_token = lambda tok: "real-auth-token" if tok == "encrypted-token" else tok

        monkeypatch.setitem(sys.modules, "database.auth_db", fake_auth_db)

        result = bnr_order_api.get_bnr_userid("real-auth-token")

        assert result == "ITC1441"

    def test_falls_back_to_env_var_when_db_lookup_empty(self, monkeypatch):
        fake_auth_db = MagicMock()
        fake_auth_db.AuthBrokerSession.query.filter_by.return_value.all.return_value = []
        fake_auth_db.Auth.query.filter_by.return_value.all.return_value = []
        monkeypatch.setitem(sys.modules, "database.auth_db", fake_auth_db)

        fake_user_db = MagicMock()
        fake_user_db.UserBrokerCredential.query.filter_by.return_value.first.return_value = None
        monkeypatch.setitem(sys.modules, "database.user_db", fake_user_db)

        monkeypatch.setattr(bnr_order_api.os, "getenv",
                             lambda key, default="": "ITC1441:::ITC1441_U" if key == "BROKER_API_KEY" else default)

        result = bnr_order_api.get_bnr_userid("some-token")

        assert result == "ITC1441"

    def test_returns_empty_string_not_none_when_nothing_resolves(self, monkeypatch):
        """The critical property: never returns None, so callers can safely
        check `if not bnr_userid:` instead of crashing on .split()."""
        fake_auth_db = MagicMock()
        fake_auth_db.AuthBrokerSession.query.filter_by.return_value.all.return_value = []
        fake_auth_db.Auth.query.filter_by.return_value.all.return_value = []
        monkeypatch.setitem(sys.modules, "database.auth_db", fake_auth_db)

        fake_user_db = MagicMock()
        fake_user_db.UserBrokerCredential.query.filter_by.return_value.first.return_value = None
        monkeypatch.setitem(sys.modules, "database.user_db", fake_user_db)

        monkeypatch.setattr(bnr_order_api.os, "getenv", lambda key, default="": default)

        result = bnr_order_api.get_bnr_userid(None)

        assert result == ""

    def test_rejects_admin_and_mak_prefixed_fallback_values(self, monkeypatch):
        """These are Max Algos platform identifiers, never real BNR client
        codes -- accepting them would send orders with a bogus uid."""
        fake_auth_db = MagicMock()
        fake_auth_db.AuthBrokerSession.query.filter_by.return_value.all.return_value = []
        fake_auth_db.Auth.query.filter_by.return_value.all.return_value = []
        monkeypatch.setitem(sys.modules, "database.auth_db", fake_auth_db)

        fake_user_db = MagicMock()
        fake_user_db.UserBrokerCredential.query.filter_by.return_value.first.return_value = None
        monkeypatch.setitem(sys.modules, "database.user_db", fake_user_db)

        monkeypatch.setattr(bnr_order_api.os, "getenv", lambda key, default="": default)

        assert bnr_order_api.get_bnr_userid(None, fallback_userid="admin") == ""
        assert bnr_order_api.get_bnr_userid(None, fallback_userid="mak_abc123") == ""


class TestPlaceOrderApiMissingUserid:
    def test_place_order_api_returns_clean_error_not_crash_when_userid_unresolvable(self, monkeypatch):
        monkeypatch.setattr(bnr_order_api, "get_bnr_userid", lambda auth, fallback_userid=None: "")

        res, response_data, order_id = bnr_order_api.place_order_api(
            {"symbol": "SBIN", "exchange": "NSE", "action": "BUY", "quantity": 1}, "fake-auth-token"
        )

        assert res is None
        assert order_id is None
        assert response_data["stat"] == "Not_Ok"
        assert "Client Code" in response_data["emsg"]


class TestPlaceOrderServiceHandlesNoneResponse:
    """place_order_service.py must not crash on res.status when a broker
    module deliberately returns res=None (aborted before any HTTP call)."""

    def test_none_response_object_produces_clean_error_not_attributeerror(self, monkeypatch):
        import services.place_order_service as pos

        fake_module = MagicMock()
        fake_module.place_order_api.return_value = (
            None,
            {"stat": "Not_Ok", "emsg": "BNR Client Code (User ID) is missing."},
            None,
        )

        with patch.object(pos.importlib, "import_module", return_value=fake_module), \
             patch.object(pos, "get_analyze_mode", return_value=False), \
             patch.object(pos.bus, "publish"):
            success, response, status = pos.place_order(
                order_data={
                    "symbol": "SBIN", "exchange": "NSE", "action": "BUY",
                    "quantity": 1, "pricetype": "MARKET", "product": "MIS",
                    "strategy": "test",
                },
                auth_token="fake-token",
                broker="bnr",
                username="alice",
            )

        assert success is False
        assert status == 400
        assert "Client Code" in response["message"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
