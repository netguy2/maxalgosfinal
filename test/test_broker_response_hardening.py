"""
Regression tests for the broker-response-hardening audit that followed the
zerodha close_all_positions/place_order_api fix (see
test_order_execution_failure_modes.py for the zerodha originals).

Covers the top-N brokers found VULNERABLE in that audit: angel, zebu, bnr.
Same bug shape in all three: close_all_positions and cancel_all_orders_api
did raw dict indexing on broker-response data with no .get() fallback, so a
single malformed entry (missing key, unexpected shape) would raise and abort
processing of every OTHER valid position/order in the same response.

All broker HTTP calls are mocked. Nothing hits a live endpoint.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Same restx_api/place_order_service circular-import dodge as
# test_order_execution_failure_modes.py -- see that file for the full
# explanation. Not needed for these tests directly, but broker order_api
# modules get imported by the same package graph in some environments.
import restx_api  # noqa: F401

import broker.angel.api.order_api as angel_order_api
import broker.bnr.api.order_api as bnr_order_api
import broker.zebu.api.order_api as zebu_order_api


# ---------------------------------------------------------------------------
# angel
# ---------------------------------------------------------------------------

class TestAngelCloseAllPositionsHardening:
    def test_missing_data_key_treated_as_no_positions(self):
        """Broker response with no "data" key at all (not even null) must
        not raise KeyError before the empty-check runs."""
        with patch.object(angel_order_api, "get_positions", return_value={"status": True}):
            response, status = angel_order_api.close_all_positions("apikey123", "faketoken")

        assert status == 200
        assert "No Open Positions" in response["message"]

    def test_malformed_position_does_not_abort_the_rest(self):
        """One position missing "netqty" must not crash the loop and leave
        every other valid position unclosed."""
        positions = {
            "status": True,
            "data": [
                {"symboltoken": "3045", "exchange": "NSE", "producttype": "INTRADAY"},  # missing netqty
                {"symboltoken": "99926000", "exchange": "NSE", "producttype": "INTRADAY", "netqty": "10"},
            ],
        }
        placed_symbols = []

        def fake_place_order_api(payload, auth):
            placed_symbols.append(payload["symbol"])
            return MagicMock(status=200), {"status": "success"}, "1"

        with patch.object(angel_order_api, "get_positions", return_value=positions), \
             patch.object(angel_order_api, "place_order_api", side_effect=fake_place_order_api), \
             patch.object(angel_order_api, "get_symbol", side_effect=lambda tok, exch: tok), \
             patch.object(angel_order_api, "reverse_map_product_type", return_value="MIS"):
            response, status = angel_order_api.close_all_positions("apikey123", "faketoken")

        assert "99926000" in placed_symbols, "the well-formed position must still be closed"
        assert status == 200
        assert response["status"] == "error"

    def test_empty_data_list_is_a_noop(self):
        with patch.object(angel_order_api, "get_positions", return_value={"status": True, "data": []}), \
             patch.object(angel_order_api, "place_order_api") as mock_place:
            response, status = angel_order_api.close_all_positions("apikey123", "faketoken")

        mock_place.assert_not_called()
        assert status == 200


class TestAngelCancelAllOrdersHardening:
    def test_missing_status_key_returns_empty_not_crash(self):
        with patch.object(angel_order_api, "get_order_book", return_value={"data": []}):
            canceled, failed = angel_order_api.cancel_all_orders_api({}, "faketoken")

        assert canceled == [] and failed == []

    def test_order_missing_status_field_is_skipped_not_crashed(self):
        """A single order entry missing "status" must not crash the filter
        comprehension for every other order in the book."""
        order_book = {
            "status": True,
            "data": [
                {"orderid": "1"},  # missing "status"
                {"orderid": "2", "status": "open"},
            ],
        }
        with patch.object(angel_order_api, "get_order_book", return_value=order_book), \
             patch.object(angel_order_api, "cancel_order", return_value=({"status": "success"}, 200)) as mock_cancel:
            canceled, failed = angel_order_api.cancel_all_orders_api({}, "faketoken")

        mock_cancel.assert_called_once_with("2", "faketoken")
        assert canceled == ["2"]

    def test_order_missing_orderid_is_skipped_not_crashed(self):
        order_book = {
            "status": True,
            "data": [
                {"status": "open"},  # missing "orderid"
                {"orderid": "2", "status": "open"},
            ],
        }
        with patch.object(angel_order_api, "get_order_book", return_value=order_book), \
             patch.object(angel_order_api, "cancel_order", return_value=({"status": "success"}, 200)) as mock_cancel:
            canceled, failed = angel_order_api.cancel_all_orders_api({}, "faketoken")

        mock_cancel.assert_called_once_with("2", "faketoken")
        assert canceled == ["2"]


# ---------------------------------------------------------------------------
# zebu (Noren/Shoonya-family: list-indexed positions response)
# ---------------------------------------------------------------------------

class TestZebuCloseAllPositionsHardening:
    def test_error_dict_response_treated_as_no_positions_not_crash(self):
        """Noren-family brokers return a dict like {"stat": "Not_Ok", ...}
        on error, not a list -- positions_response[0] used to raise
        IndexError/TypeError on this shape."""
        with patch.object(zebu_order_api, "get_positions", return_value={"stat": "Not_Ok", "emsg": "Session Expired"}):
            response, status = zebu_order_api.close_all_positions("apikey123", "faketoken")

        assert status == 200
        assert "No Open Positions" in response["message"] or response.get("status") in (None, "error")

    def test_empty_list_response_treated_as_no_positions(self):
        with patch.object(zebu_order_api, "get_positions", return_value=[]):
            response, status = zebu_order_api.close_all_positions("apikey123", "faketoken")

        assert status == 200

    def test_malformed_position_does_not_abort_the_rest(self):
        """One position missing "netqty" must not crash the loop and leave
        every other valid position unclosed."""
        positions = [
            {"token": "3045", "exch": "NSE", "prd": "I"},  # missing netqty
            {"token": "99926000", "exch": "NSE", "prd": "I", "netqty": "10"},
        ]
        placed_symbols = []

        def fake_place_order_api(payload, auth):
            placed_symbols.append(payload["symbol"])
            return MagicMock(status=200), {"stat": "Ok", "norenordno": "1"}, "1"

        with patch.object(zebu_order_api, "get_positions", return_value=positions), \
             patch.object(zebu_order_api, "place_order_api", side_effect=fake_place_order_api), \
             patch.object(zebu_order_api, "get_symbol", side_effect=lambda tok, exch: tok), \
             patch.object(zebu_order_api, "reverse_map_product_type", return_value="MIS"):
            response, status = zebu_order_api.close_all_positions("apikey123", "faketoken")

        assert "99926000" in placed_symbols, "the well-formed position must still be closed"
        assert status == 200


class TestZebuCancelAllOrdersHardening:
    def test_order_missing_status_field_is_skipped_not_crashed(self):
        """Zebu's order book response is itself a flat list (unlike angel's
        {"data": [...]} wrapper)."""
        order_book = [
            {"norenordno": "1"},  # missing "status"
            {"norenordno": "2", "status": "OPEN"},
        ]
        with patch.object(zebu_order_api, "get_order_book", return_value=order_book), \
             patch.object(zebu_order_api, "cancel_order", return_value=({"status": "success"}, 200)) as mock_cancel:
            canceled, failed = zebu_order_api.cancel_all_orders_api({}, "faketoken")

        mock_cancel.assert_called_once_with("2", "faketoken")
        assert canceled == ["2"]


# ---------------------------------------------------------------------------
# bnr (same Noren/Shoonya-family shape as zebu)
# ---------------------------------------------------------------------------

class TestBnrCloseAllPositionsHardening:
    def test_error_dict_response_treated_as_no_positions_not_crash(self):
        with patch.object(bnr_order_api, "get_positions", return_value={"stat": "Not_Ok", "emsg": "Session Expired"}):
            response, status = bnr_order_api.close_all_positions("apikey123", "faketoken")

        assert status == 200

    def test_malformed_position_does_not_abort_the_rest(self):
        positions = [
            {"token": "3045", "exch": "NSE", "prd": "I"},  # missing netqty
            {"token": "99926000", "exch": "NSE", "prd": "I", "netqty": "10"},
        ]
        placed_symbols = []

        def fake_place_order_api(payload, auth):
            placed_symbols.append(payload["symbol"])
            return MagicMock(status=200), {"stat": "Ok", "norenordno": "1"}, "1"

        with patch.object(bnr_order_api, "get_positions", return_value=positions), \
             patch.object(bnr_order_api, "place_order_api", side_effect=fake_place_order_api), \
             patch.object(bnr_order_api, "get_symbol", side_effect=lambda tok, exch: tok), \
             patch.object(bnr_order_api, "reverse_map_product_type", return_value="MIS"):
            response, status = bnr_order_api.close_all_positions("apikey123", "faketoken")

        assert "99926000" in placed_symbols
        assert status == 200


class TestBnrCancelAllOrdersHardening:
    def test_order_missing_status_field_is_skipped_not_crashed(self):
        """Bnr's order book response is itself a flat list (unlike angel's
        {"data": [...]} wrapper)."""
        order_book = [
            {"norenordno": "1"},  # missing "status"
            {"norenordno": "2", "status": "OPEN"},
        ]
        with patch.object(bnr_order_api, "get_order_book", return_value=order_book), \
             patch.object(bnr_order_api, "cancel_order", return_value=({"status": "success"}, 200)) as mock_cancel:
            canceled, failed = bnr_order_api.cancel_all_orders_api({}, "faketoken")

        mock_cancel.assert_called_once_with("2", "faketoken")
        assert canceled == ["2"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
