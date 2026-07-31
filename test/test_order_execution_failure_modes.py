"""
Failure-mode tests for the order execution / position management flow.

These deliberately target unhappy paths: broker errors, malformed payloads,
duplicate/racing webhook calls, closing a non-existent position, malformed
strategy-builder input, websocket reconnect state, and market-hours edges.

All broker HTTP calls are mocked (httpx client / broker module functions).
Nothing hits a live endpoint.
"""

import os
import sys
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# services.place_order_service <-> restx_api has a pre-existing circular
# import (place_order_service imports OrderSchema from restx_api.schemas;
# restx_api/__init__ eagerly imports options_multiorder, which imports
# place_order back from services.place_order_service). In the running app
# this never surfaces because app.py imports restx_api first, fully
# initializing it before any service module is touched. Import restx_api
# first here too, purely to dodge the ordering issue -- not a code fix.
import restx_api  # noqa: F401

# Same shape of hazard, second instance: importing broker.zerodha.streaming
# .zerodha_adapter directly (bypassing broker.zerodha.streaming.__init__)
# trips over websocket_proxy/__init__.py, which imports EVERY broker's
# adapter eagerly and, at the very end, imports zerodha_adapter again --
# except this time the module is still mid-initialization from our direct
# import, so it comes back partially-initialized. Pre-importing
# websocket_proxy first (which fully resolves all broker adapters up front,
# in app.py's actual startup order) avoids it here too.
import websocket_proxy  # noqa: F401

import broker.zerodha.api.order_api as zerodha_order_api
import services.close_position_service as close_position_service
import services.place_order_service as place_order_service
from database.market_calendar_db import is_market_open

IST = pytz.timezone("Asia/Kolkata")


def make_order_data(**overrides):
    data = {
        "apikey": "testkey",
        "strategy": "TestStrategy",
        "symbol": "SBIN",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": "1",
        "pricetype": "MARKET",
        "product": "MIS",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# 1. Broker API returns 500 / times out mid-order
# ---------------------------------------------------------------------------

class TestBrokerErrorsAndTimeouts:
    def test_place_order_api_raises_httpx_timeout(self):
        """Zerodha's place_order_api makes a raw client.post() call with no
        try/except of its own -- an httpx timeout must propagate as an
        exception, not silently become a (None, None, None) tuple."""
        import httpx

        with patch.object(zerodha_order_api, "get_httpx_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.ConnectTimeout("connect timed out")
            mock_get_client.return_value = mock_client

            with pytest.raises(httpx.ConnectTimeout):
                zerodha_order_api.place_order_api(make_order_data(), "faketoken")

    def test_place_order_with_auth_converts_broker_exception_to_500(self):
        """place_order_with_auth wraps broker_module.place_order_api in a
        try/except -- confirm a raised exception (timeout, 500, connection
        reset, whatever) becomes a clean 500 JSON error, not an unhandled
        traceback bubbling to the Flask layer."""
        order_data = make_order_data()

        with patch.object(place_order_service, "import_broker_module") as mock_import:
            broker_module = MagicMock()
            broker_module.place_order_api.side_effect = ConnectionError("connection reset by peer")
            mock_import.return_value = broker_module

            with patch.object(place_order_service, "get_analyze_mode", return_value=False), \
                 patch("services.order_gate.check_order_allowed", return_value=(True, None, None)):
                success, response, status = place_order_service.place_order_with_auth(
                    order_data, "faketoken", "zerodha", order_data
                )

        assert success is False
        assert status == 500
        assert response["status"] == "error"
        assert "internal error" in response["message"].lower()

    def test_broker_returns_http_500_with_json_body(self):
        """REGRESSION (TIER 2 fix): simulates the broker gateway returning a
        genuine 500 with a valid-JSON error body (many gateways return
        {"error": "..."} on 5xx). Zerodha's place_order_api used to read
        response_data["status"] unconditionally and raise KeyError, since
        Kite's error envelope never has "status" in this shape. Now it must
        return orderid=None (via the .get("status") guard) instead of
        raising -- this response is still a 500 by HTTP status code, which
        callers can check directly."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = '{"error": "internal_server_error"}'
        mock_response.json.return_value = {"error": "internal_server_error"}

        with patch.object(zerodha_order_api, "get_httpx_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            res, response_data, orderid = zerodha_order_api.place_order_api(make_order_data(), "faketoken")

        assert orderid is None
        assert res.status == 500

    def test_broker_500_is_caught_and_surfaced_as_500_through_service_layer(self):
        """End-to-end: a malformed-body 500 from the broker (order_id=None,
        res.status=500) must flow through place_order_with_auth as a clean
        failure response with the broker's real status code, not a 200 or
        an unhandled exception."""
        order_data = make_order_data()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": "internal_server_error"}

        with patch.object(zerodha_order_api, "get_httpx_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            with patch.object(place_order_service, "import_broker_module", return_value=zerodha_order_api), \
                 patch.object(place_order_service, "get_analyze_mode", return_value=False), \
                 patch("services.order_gate.check_order_allowed", return_value=(True, None, None)), \
                 patch("broker.zerodha.mapping.transform_data.transform_data") as mock_transform:
                mock_transform.return_value = {
                    "tradingsymbol": "SBIN", "exchange": "NSE", "transaction_type": "BUY",
                    "order_type": "MARKET", "quantity": "1", "product": "MIS", "price": "0",
                    "trigger_price": "0", "disclosed_quantity": "0", "validity": "DAY", "tag": "",
                    "market_protection": "0",
                }
                success, response, status = place_order_service.place_order_with_auth(
                    order_data, "faketoken", "zerodha", order_data
                )

        assert success is False
        assert status == 500
        assert response["status"] == "error"


# ---------------------------------------------------------------------------
# 2. Broker API returns success but with malformed/unexpected payload shape
# ---------------------------------------------------------------------------

class TestMalformedBrokerPayloads:
    def test_place_order_success_response_missing_data_key(self):
        """REGRESSION (TIER 2 fix): real Kite success shape is
        {"status": "success", "data": {"order_id": ...}}. If the broker (or
        a proxy in front of it) returns {"status": "success"} with no "data"
        key at all, place_order_api used to raise KeyError instead of
        returning orderid=None gracefully. Now it must return a None
        orderid (treated as "couldn't confirm", not a crash) rather than
        raise -- this matters because a raised exception here gets
        reported as a generic 500 indistinguishable from "never reached
        the broker," when the broker may actually have accepted the order."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}  # no "data"

        with patch.object(zerodha_order_api, "get_httpx_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            res, response_data, orderid = zerodha_order_api.place_order_api(make_order_data(), "faketoken")

        assert orderid is None

    def test_place_order_response_not_valid_json(self):
        """response.json() itself can raise (e.g. broker returns an HTML
        error page with a 200 status because of a misconfigured proxy)."""
        import json as json_module

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html>Bad Gateway</html>"
        mock_response.json.side_effect = json_module.JSONDecodeError("Expecting value", "<html>", 0)

        with patch.object(zerodha_order_api, "get_httpx_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            with pytest.raises(json_module.JSONDecodeError):
                zerodha_order_api.place_order_api(make_order_data(), "faketoken")

    def test_close_all_positions_malformed_payload_missing_data_key(self):
        """REGRESSION (TIER 2 fix): close_all_positions used to do
        positions_response["data"] with no .get() guard, so a broker
        response of {"status": True} with NO "data" key at all (not even
        null) raised KeyError before the "is data None or empty" check ever
        ran. Now it must be treated the same as "no open positions"."""
        with patch.object(zerodha_order_api, "get_positions", return_value={"status": True}):
            response, status = zerodha_order_api.close_all_positions("apikey123", "faketoken")

        assert status == 200
        assert "No Open Positions" in response["message"]

    def test_close_all_positions_net_missing_from_data(self):
        """REGRESSION (TIER 2 fix): broker returns "data" present but
        without the expected "net" key (e.g. schema change or partial
        response). Iterating positions_response["data"]["net"] used to
        raise KeyError; now an absent "net" key must be treated as an
        empty position list (a no-op close), not a crash."""
        with patch.object(zerodha_order_api, "get_positions",
                           return_value={"status": True, "data": {"day": []}}), \
             patch.object(zerodha_order_api, "place_order_api") as mock_place:
            response, status = zerodha_order_api.close_all_positions("apikey123", "faketoken")

        mock_place.assert_not_called()
        assert status == 200

    def test_close_all_positions_one_malformed_position_does_not_abort_the_rest(self):
        """REGRESSION (TIER 2 fix): previously a single malformed position
        entry (e.g. missing "quantity") would raise and abort the whole
        close_all_positions loop, silently leaving every OTHER valid
        position in the same response open with no close attempt made at
        all. Now each position is closed independently -- one bad entry is
        recorded as failed but must not block the good ones from being
        squared off."""
        positions = {
            "status": True,
            "data": {"net": [
                {"tradingsymbol": "SBIN", "exchange": "NSE", "product": "MIS"},  # missing "quantity"
                {"tradingsymbol": "INFY", "exchange": "NSE", "product": "MIS", "quantity": "10"},
            ]},
        }
        placed_symbols = []

        def fake_place_order_api(payload, auth):
            placed_symbols.append(payload["symbol"])
            return MagicMock(status=200), {"status": "success", "data": {"order_id": "1"}}, "1"

        with patch.object(zerodha_order_api, "get_positions", return_value=positions), \
             patch.object(zerodha_order_api, "place_order_api", side_effect=fake_place_order_api), \
             patch.object(zerodha_order_api, "get_oa_symbol", side_effect=lambda sym, exch: sym), \
             patch.object(zerodha_order_api, "reverse_map_product_type", return_value="MIS"):
            response, status = zerodha_order_api.close_all_positions("apikey123", "faketoken")

        assert "INFY" in placed_symbols, "the well-formed INFY position must still be closed"
        assert "SBIN" not in placed_symbols, "the malformed SBIN position has no quantity to act on"
        assert status == 200
        assert response["status"] == "error"
        assert "SBIN" in response["message"]

    def test_close_position_with_auth_missing_net_key_now_reports_success(self):
        """End-to-end through the service layer: since close_all_positions
        no longer raises on a missing "net" key (previous test), this must
        now flow through close_position_with_auth as a clean success
        rather than the 500 it produced before the TIER 2 fix."""
        position_data = {"apikey": "testkey"}
        original_data = {"apikey": "testkey"}

        with patch.object(close_position_service, "import_broker_module", return_value=zerodha_order_api), \
             patch.object(close_position_service, "get_analyze_mode", return_value=False), \
             patch.object(zerodha_order_api, "get_positions",
                          return_value={"status": True, "data": {"day": []}}):
            success, response, status = close_position_service.close_position_with_auth(
                position_data, "faketoken", "zerodha", original_data
            )

        assert success is True
        assert status == 200

    def test_place_order_quantity_field_wrong_type(self):
        """Broker occasionally returns numeric order_id as int rather than
        str -- place_order_with_auth does str(order_id) defensively so this
        should NOT fail; included as a contrast/control case."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success", "data": {"order_id": 123456789}}

        with patch.object(zerodha_order_api, "get_httpx_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_get_client.return_value = mock_client

            with patch("broker.zerodha.mapping.transform_data.transform_data") as mock_transform:
                mock_transform.return_value = {
                    "tradingsymbol": "SBIN", "exchange": "NSE", "transaction_type": "BUY",
                    "order_type": "MARKET", "quantity": "1", "product": "MIS", "price": "0",
                    "trigger_price": "0", "disclosed_quantity": "0", "validity": "DAY", "tag": "",
                    "market_protection": "0",
                }
                res, response_data, orderid = zerodha_order_api.place_order_api(make_order_data(), "faketoken")

        assert orderid == 123456789


# ---------------------------------------------------------------------------
# 3. Two orders for the same symbol within milliseconds (duplicate/retry)
# ---------------------------------------------------------------------------

class TestDuplicateConcurrentOrders:
    def test_concurrent_smart_orders_same_symbol_are_serialized(self):
        """place_smartorder_api uses a per-(symbol,exchange,product) lock so
        two near-simultaneous webhook deliveries for the same symbol don't
        race on the position-delta calculation. Verify serialization
        actually happens: both calls should NOT observe the broker call
        running concurrently."""
        call_order = []
        lock_gate = threading.Event()

        def fake_get_open_position(symbol, exchange, product, auth):
            call_order.append(("read_position", threading.current_thread().name))
            return "0"

        def fake_place_order_api(data, auth):
            call_order.append(("place_order_start", threading.current_thread().name))
            time.sleep(0.05)  # hold the lock long enough to prove serialization
            call_order.append(("place_order_end", threading.current_thread().name))
            return MagicMock(status=200), {"status": "success", "data": {"order_id": "1"}}, "1"

        with patch.object(zerodha_order_api, "get_open_position", side_effect=fake_get_open_position), \
             patch.object(zerodha_order_api, "place_order_api", side_effect=fake_place_order_api):

            data = {"symbol": "SBIN", "exchange": "NSE", "product": "MIS",
                     "position_size": "10", "action": "BUY", "quantity": "10"}

            results = []

            def worker():
                results.append(zerodha_order_api.place_smartorder_api(dict(data), "faketoken"))

            t1 = threading.Thread(target=worker, name="webhook-retry-1")
            t2 = threading.Thread(target=worker, name="webhook-retry-2")
            t1.start()
            t2.start()
            t1.join()
            t2.join()

        # Both completed without interleaving: no "place_order_start" for
        # thread B should appear before thread A's "place_order_end".
        starts_ends = [e for e in call_order if e[0] in ("place_order_start", "place_order_end")]
        assert len(starts_ends) == 4
        # First start's matching end must come before the second start
        first_thread = starts_ends[0][1]
        first_end_idx = next(i for i, e in enumerate(starts_ends) if e[0] == "place_order_end" and e[1] == first_thread)
        second_start_idx = next(i for i, e in enumerate(starts_ends) if e[0] == "place_order_start" and e[1] != first_thread)
        assert first_end_idx < second_start_idx, (
            "Two webhook retries for the same symbol executed their broker "
            "calls concurrently instead of being serialized by the per-symbol lock"
        )

    def _place_via_place_order(self, order_data, api_key="testkey"):
        def fake_place_order_api(data, auth):
            return MagicMock(status=200), {"status": "success", "data": {"order_id": "1"}}, "1"

        with patch.object(place_order_service, "import_broker_module", return_value=zerodha_order_api), \
             patch.object(place_order_service, "get_analyze_mode", return_value=False), \
             patch("services.order_gate.check_order_allowed", return_value=(True, None, None)), \
             patch("services.order_router_service.should_route_to_pending", return_value=False), \
             patch.object(place_order_service, "get_auth_token_broker", return_value=("faketoken", "zerodha")), \
             patch.object(zerodha_order_api, "place_order_api", side_effect=fake_place_order_api):
            return place_order_service.place_order(dict(order_data), api_key=api_key)

    def test_duplicate_place_order_webhook_is_suppressed(self):
        """REGRESSION (TIER 2 fix): place_order now fingerprints
        (apikey, strategy, symbol, exchange, action, quantity, pricetype,
        product, price, trigger_price) and rejects an exact repeat arriving
        within DEDUP_WINDOW_SECONDS. A duplicate TradingView/Chartink
        webhook delivery must be suppressed with a 429, not silently placed
        twice."""
        place_order_service._recent_order_fingerprints.clear()
        order_data = make_order_data()

        success1, response1, status1 = self._place_via_place_order(order_data)
        success2, response2, status2 = self._place_via_place_order(order_data)

        assert success1 is True
        assert status1 == 200
        assert success2 is False
        assert status2 == 429
        assert "duplicate" in response2["message"].lower()

    def test_distinct_orders_are_not_deduped(self):
        """Two orders that differ in symbol must not collide in the dedup
        fingerprint -- confirms the fix suppresses true repeats only, not
        every order from the same strategy/apikey in a short window."""
        place_order_service._recent_order_fingerprints.clear()
        order_a = make_order_data(symbol="SBIN")
        order_b = make_order_data(symbol="INFY")

        success1, _, status1 = self._place_via_place_order(order_a)
        success2, _, status2 = self._place_via_place_order(order_b)

        assert success1 is True and status1 == 200
        assert success2 is True and status2 == 200

    def test_duplicate_order_allowed_again_after_dedup_window_expires(self):
        """A legitimately repeated order (same strategy re-firing later, not
        a retry) must be allowed once DEDUP_WINDOW_SECONDS has passed --
        confirms this is a retry-suppression window, not a permanent
        one-shot-per-payload rule."""
        place_order_service._recent_order_fingerprints.clear()
        order_data = make_order_data()

        success1, _, status1 = self._place_via_place_order(order_data)
        with patch("time.monotonic", return_value=time.monotonic() + place_order_service.DEDUP_WINDOW_SECONDS + 1):
            success2, _, status2 = self._place_via_place_order(order_data)

        assert success1 is True and status1 == 200
        assert success2 is True and status2 == 200

    def test_internal_call_with_auth_token_and_broker_is_exempt_from_dedup(self):
        """Direct internal calls (auth_token+broker already resolved, e.g.
        signal_engine.py) are not webhook retries and must not be
        fingerprint-suppressed -- otherwise a legitimate rapid-fire
        strategy (e.g. a scalper re-entering the same symbol seconds apart)
        would get silently blocked."""
        order_data = make_order_data()
        del order_data["apikey"]

        def fake_place_order_api(data, auth):
            return MagicMock(status=200), {"status": "success", "data": {"order_id": "1"}}, "1"

        with patch.object(place_order_service, "import_broker_module", return_value=zerodha_order_api), \
             patch.object(place_order_service, "get_analyze_mode", return_value=False), \
             patch("services.order_gate.check_order_allowed", return_value=(True, None, None)), \
             patch.object(zerodha_order_api, "place_order_api", side_effect=fake_place_order_api):
            success1, _, status1 = place_order_service.place_order(
                dict(order_data), auth_token="faketoken", broker="zerodha"
            )
            success2, _, status2 = place_order_service.place_order(
                dict(order_data), auth_token="faketoken", broker="zerodha"
            )

        assert success1 is True and status1 == 200
        assert success2 is True and status2 == 200


# ---------------------------------------------------------------------------
# 4. Position close called when no position exists
# ---------------------------------------------------------------------------

class TestCloseWithNoPosition:
    def test_close_all_positions_empty_data_returns_200_no_op(self):
        """Broker's own contract for 'no positions': {"data": None}. Confirm
        close_all_positions short-circuits cleanly instead of iterating."""
        with patch.object(zerodha_order_api, "get_positions", return_value={"status": True, "data": None}):
            response, status = zerodha_order_api.close_all_positions("apikey123", "faketoken")

        assert status == 200
        assert "No Open Positions" in response["message"]

    def test_close_all_positions_empty_net_list_is_a_noop(self):
        """net list present but empty -- loop body never executes, still 200."""
        with patch.object(zerodha_order_api, "get_positions",
                           return_value={"status": True, "data": {"net": []}}), \
             patch.object(zerodha_order_api, "place_order_api") as mock_place:
            response, status = zerodha_order_api.close_all_positions("apikey123", "faketoken")

        mock_place.assert_not_called()
        assert status == 200
        assert response["status"] == "success"

    def test_close_all_positions_all_zero_quantity_positions_skipped(self):
        """Positions with net quantity 0 (already flat, broker still lists
        them) must be skipped, not sent as a zero-quantity order."""
        with patch.object(zerodha_order_api, "get_positions", return_value={
            "status": True,
            "data": {"net": [
                {"tradingsymbol": "SBIN", "exchange": "NSE", "product": "MIS", "quantity": "0"},
            ]},
        }), patch.object(zerodha_order_api, "place_order_api") as mock_place:
            response, status = zerodha_order_api.close_all_positions("apikey123", "faketoken")

        mock_place.assert_not_called()
        assert status == 200

    def test_close_position_service_no_position_flows_to_success(self):
        """End-to-end through close_position_with_auth: broker reports no
        open positions -- caller still gets a clean success, not an error."""
        with patch.object(close_position_service, "import_broker_module", return_value=zerodha_order_api), \
             patch.object(close_position_service, "get_analyze_mode", return_value=False), \
             patch.object(zerodha_order_api, "get_positions", return_value={"status": True, "data": None}):
            success, response, status = close_position_service.close_position_with_auth(
                {"apikey": "testkey"}, "faketoken", "zerodha", {"apikey": "testkey"}
            )

        assert success is True
        assert status == 200


# ---------------------------------------------------------------------------
# 5. Strategy builder generates an order with missing/null fields
# ---------------------------------------------------------------------------

class TestMissingNullFields:
    def test_missing_quantity_field_rejected(self):
        data = make_order_data()
        del data["quantity"]
        ok, validated, error = place_order_service.validate_order_data(data)
        assert ok is False
        assert "quantity" in error.lower()

    def test_missing_symbol_field_rejected(self):
        data = make_order_data()
        del data["symbol"]
        ok, validated, error = place_order_service.validate_order_data(data)
        assert ok is False
        assert "symbol" in error.lower()

    def test_null_action_field_rejected_not_crashed(self):
        """REGRESSION (TIER 1 fix): validate_order_data used to call
        data["action"].upper() unconditionally once "action" was a present
        key. A Flow/strategy-builder order with action=None (e.g. an unbound
        node variable) raised AttributeError instead of returning a clean
        400 -- an uncaught exception that would propagate straight out of
        place_order() with no OrderFailedEvent, no error response, just a
        raw traceback. Now a None action must be treated as a missing
        mandatory field."""
        data = make_order_data(action=None)
        ok, validated, error = place_order_service.validate_order_data(data)
        assert ok is False
        assert "action" in error.lower()

    def test_null_quantity_value_present_but_none(self):
        """quantity present as key but value None -- passes the "missing
        fields" check (key exists) but should fail downstream schema
        validation rather than reach the broker with quantity=None."""
        data = make_order_data(quantity=None)
        ok, validated, error = place_order_service.validate_order_data(data)
        assert ok is False, "order with quantity=None must not validate successfully"

    def test_empty_string_symbol_rejected(self):
        """REGRESSION (TIER 1 fix): symbol="" is falsy but WAS present as a
        key, so the old 'missing mandatory fields' check (which only tested
        `field not in data`) let it through to the broker call. Blank
        required fields (None, "", or whitespace-only) must now be treated
        as missing."""
        data = make_order_data(symbol="")
        ok, validated, error = place_order_service.validate_order_data(data)
        assert ok is False
        assert "symbol" in error.lower()

    def test_whitespace_only_symbol_rejected(self):
        """Same gap, whitespace variant -- a template substitution gone wrong
        can produce "   " rather than "", which .strip() must also catch."""
        data = make_order_data(symbol="   ")
        ok, validated, error = place_order_service.validate_order_data(data)
        assert ok is False
        assert "symbol" in error.lower()

    def test_blank_apikey_field_rejected(self):
        """Blank-field check applies to every required field, not just
        symbol/action -- confirm apikey="" (e.g. a caller that forwards an
        unresolved template var) is also caught."""
        data = make_order_data(apikey="")
        ok, validated, error = place_order_service.validate_order_data(data)
        assert ok is False
        assert "apikey" in error.lower()

    def test_invalid_action_value_rejected(self):
        data = make_order_data(action="HOLD")
        ok, validated, error = place_order_service.validate_order_data(data)
        assert ok is False
        assert "action" in error.lower()

    def test_invalid_exchange_rejected(self):
        data = make_order_data(exchange="NASDAQ")
        ok, validated, error = place_order_service.validate_order_data(data)
        assert ok is False
        assert "exchange" in error.lower()

    def test_flow_builder_missing_required_fields_dict_get_defaults_to_empty(self):
        """flow_executor_service's execute_place_order builds its order dict
        from node config using .get() helpers -- if a required upstream node
        output is missing, fields silently default to empty string / 0
        rather than raising at construction time, deferring the failure to
        validate_order_data. Confirm an all-blank order is rejected there."""
        blank_order = {
            "apikey": "testkey", "strategy": "", "symbol": "", "exchange": "",
            "action": "", "quantity": "0",
        }
        ok, validated, error = place_order_service.validate_order_data(blank_order)
        # action="" fails VALID_ACTIONS check specifically
        assert ok is False


# ---------------------------------------------------------------------------
# 6. Websocket disconnects mid-session -- reconnect & state
# ---------------------------------------------------------------------------

class TestWebSocketReconnect:
    def test_on_disconnect_callback_does_not_clear_adapter_subscription_state(self):
        """The ZerodhaWebSocketAdapter._on_disconnect callback (fired on an
        actual unexpected drop, as opposed to explicit .disconnect()) only
        flips self.connected = False. It does NOT clear
        self.subscribed_symbols / self.token_to_symbol the way the explicit
        disconnect() path does. This means the adapter's app-level view of
        "what am I subscribed to" survives a mid-session drop -- which is
        actually the correct behavior FOR the low-level client's
        _resubscribe_all() to work, but it also means if the low-level
        client fails to reconnect (see next test), the adapter has no signal
        instructing it to fall back or alert."""
        from broker.zerodha.streaming.zerodha_adapter import ZerodhaWebSocketAdapter

        adapter = ZerodhaWebSocketAdapter()
        adapter.subscribed_symbols = {"NSE:SBIN": {"token": "3045", "mode": "quote"}}
        adapter.token_to_symbol = {"3045": "NSE:SBIN"}
        adapter.connected = True

        adapter._on_disconnect()

        assert adapter.connected is False
        # Subscription bookkeeping survives -- this is what _resubscribe_all
        # in the low-level client relies on being intact after reconnect.
        assert adapter.subscribed_symbols == {"NSE:SBIN": {"token": "3045", "mode": "quote"}}
        assert adapter.token_to_symbol == {"3045": "NSE:SBIN"}

    def test_resubscribe_all_replays_subscriptions_after_reconnect(self):
        """Low-level ZerodhaWebSocket._resubscribe_all is the mechanism that
        actually restores live ticks after a reconnect -- it's invoked from
        _on_ws_open. Verify it sends subscribe+mode messages for every
        previously-subscribed token, using a fake ws.send to avoid any real
        socket."""
        from broker.zerodha.streaming.zerodha_websocket import ZerodhaWebSocket

        ws_client = ZerodhaWebSocket.__new__(ZerodhaWebSocket)
        ws_client.lock = threading.Lock()
        ws_client.subscribed_tokens = {3045, 738561}
        ws_client.mode_map = {3045: "quote", 738561: "full"}
        ws_client.MODE_QUOTE = "quote"
        ws_client.MAX_TOKENS_PER_SUBSCRIBE = 1000
        ws_client.SUBSCRIPTION_DELAY = 0
        ws_client.logger = MagicMock()
        ws_client.ws = MagicMock()

        with patch("time.sleep"):
            ws_client._resubscribe_all()

        sent_payloads = [call.args[0] for call in ws_client.ws.send.call_args_list]
        assert any('"subscribe"' in p and "3045" in p for p in sent_payloads)
        assert any('"subscribe"' in p and "738561" in p for p in sent_payloads)

    def test_resubscribe_all_noop_when_nothing_was_subscribed(self):
        """A disconnect before any symbol was ever subscribed must not send
        anything on reconnect (guards the empty-state edge)."""
        from broker.zerodha.streaming.zerodha_websocket import ZerodhaWebSocket

        ws_client = ZerodhaWebSocket.__new__(ZerodhaWebSocket)
        ws_client.lock = threading.Lock()
        ws_client.subscribed_tokens = set()
        ws_client.mode_map = {}
        ws_client.logger = MagicMock()
        ws_client.ws = MagicMock()

        ws_client._resubscribe_all()

        ws_client.ws.send.assert_not_called()

    def test_resubscribe_batch_send_failure_does_not_raise(self):
        """If ws.send() raises mid-resubscribe (e.g. socket already dead
        again by the time we try), _resubscribe_all must log and continue
        rather than propagate and kill the reconnect callback chain."""
        from broker.zerodha.streaming.zerodha_websocket import ZerodhaWebSocket

        ws_client = ZerodhaWebSocket.__new__(ZerodhaWebSocket)
        ws_client.lock = threading.Lock()
        ws_client.subscribed_tokens = {3045}
        ws_client.mode_map = {3045: "quote"}
        ws_client.MODE_QUOTE = "quote"
        ws_client.MAX_TOKENS_PER_SUBSCRIBE = 1000
        ws_client.SUBSCRIPTION_DELAY = 0
        ws_client.logger = MagicMock()
        ws_client.ws = MagicMock()
        ws_client.ws.send.side_effect = OSError("socket is closed")

        with patch("time.sleep"):
            ws_client._resubscribe_all()  # must not raise

        ws_client.logger.error.assert_called()

    def test_explicit_disconnect_clears_subscription_state_unlike_on_disconnect(self):
        """Contrast case: the ADAPTER's own disconnect() (user/app-initiated,
        e.g. logout) explicitly clears subscribed_symbols/token_to_symbol --
        different from the passive _on_disconnect callback tested above.
        Confirms the asymmetry is real, not a testing assumption."""
        from broker.zerodha.streaming.zerodha_adapter import ZerodhaWebSocketAdapter

        adapter = ZerodhaWebSocketAdapter()
        adapter.subscribed_symbols = {"NSE:SBIN": {"token": "3045", "mode": "quote"}}
        adapter.token_to_symbol = {"3045": "NSE:SBIN"}
        adapter.ws_client = MagicMock()
        adapter.running = True
        adapter.connected = True
        adapter.batch_timer = None

        with patch.object(adapter, "cleanup_zmq"):
            adapter.disconnect()

        assert adapter.subscribed_symbols == {}
        assert adapter.token_to_symbol == {}


# ---------------------------------------------------------------------------
# 7. Market hours edge cases (pre-market, exactly at close, weekend)
# ---------------------------------------------------------------------------

class TestMarketHoursEdges:
    def _mock_now(self, dt_naive):
        return IST.localize(dt_naive)

    def test_premarket_908am_is_closed(self):
        """08:59:59 IST on a weekday -- one second before the 09:00 pre-open,
        well before the 09:15 continuous session start offset (33300000 ms)."""
        fake_now = self._mock_now(datetime(2026, 7, 27, 8, 59, 59))  # Monday
        with patch("database.market_calendar_db.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            assert is_market_open("NSE") is False

    def test_exactly_915_00_is_open_boundary(self):
        """09:15:00.000 IST is the documented open instant (33300000 ms
        offset). The boundary check is inclusive (<=) per
        is_market_open's window comparison -- confirm the exact instant is
        treated as open, not off-by-one closed."""
        fake_now = self._mock_now(datetime(2026, 7, 27, 9, 15, 0))  # Monday
        with patch("database.market_calendar_db.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            assert is_market_open("NSE") is True

    def test_exactly_at_close_1530_00_is_still_open_boundary(self):
        """15:30:00.000 IST is the documented close instant (55800000 ms
        offset). Window check is start<=now<=end (inclusive), so the exact
        close tick is still 'open' by one instant -- the first closed
        instant is 15:30:00.001. This is a real off-by-nothing edge worth
        pinning down explicitly since order-placement code elsewhere in the
        file has the market-hours check commented out entirely (see
        place_order_service.py:209-215), meaning this boundary currently
        has NO enforcement effect on live order placement at all."""
        fake_now = self._mock_now(datetime(2026, 7, 27, 15, 30, 0))  # Monday
        with patch("database.market_calendar_db.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            assert is_market_open("NSE") is True

    def test_one_second_after_close_is_closed(self):
        fake_now = self._mock_now(datetime(2026, 7, 27, 15, 30, 1))  # Monday
        with patch("database.market_calendar_db.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            assert is_market_open("NSE") is False

    def test_saturday_is_closed_absent_special_session_row(self):
        """Plain Saturday with no SPECIAL_SESSION override configured in the
        DB -- get_effective_session_window should yield no window at all."""
        fake_now = self._mock_now(datetime(2026, 8, 1, 11, 0, 0))  # Saturday
        with patch("database.market_calendar_db.datetime") as mock_dt, \
             patch("database.market_calendar_db.get_effective_session_window", return_value=None):
            mock_dt.now.return_value = fake_now
            assert is_market_open("NSE") is False

    def test_market_hours_check_exception_fails_closed_not_open(self):
        """is_market_open wraps its whole body in try/except and returns
        False on any internal error -- confirms the fail-safe direction is
        'closed', i.e. a DB error here blocks trading rather than silently
        permitting it."""
        with patch("database.market_calendar_db.datetime") as mock_dt:
            mock_dt.now.side_effect = RuntimeError("clock/timezone db unavailable")
            assert is_market_open("NSE") is False

    def test_place_order_market_hours_gate_is_disabled_in_current_code(self):
        """Direct confirmation of the finding referenced above: the market-
        hours check in place_order_with_auth is commented out
        (place_order_service.py ~209-215), so an order placed at 3am IST on
        a Sunday goes straight to the broker call with no local gate at all.
        This test places an order with a mocked broker success and asserts
        it succeeds regardless of wall-clock time or day -- proving there is
        currently no market-hours enforcement at the order-placement layer
        (enforcement, if any, exists only broker-side)."""
        order_data = make_order_data()

        def fake_place_order_api(data, auth):
            return MagicMock(status=200), {"status": "success", "data": {"order_id": "1"}}, "1"

        with patch.object(place_order_service, "import_broker_module", return_value=zerodha_order_api), \
             patch.object(place_order_service, "get_analyze_mode", return_value=False), \
             patch("services.order_gate.check_order_allowed", return_value=(True, None, None)), \
             patch.object(zerodha_order_api, "place_order_api", side_effect=fake_place_order_api):
            success, response, status = place_order_service.place_order_with_auth(
                order_data, "faketoken", "zerodha", order_data
            )

        assert success is True, (
            "Order succeeded with no market-hours gate applied at the service layer "
            "-- confirms the commented-out check means weekend/off-hours orders are "
            "not blocked locally."
        )


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
