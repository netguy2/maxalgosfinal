"""Regression tests for MCX commodity support in the Flow no-code
builder's Options Order / Options Multi-Order nodes.

Root cause: services/flow_executor_service.py's execute_options_order and
execute_options_multi_order derived BOTH the underlying's exchange AND the
order quantity from a hardcoded, index-only table:

    if underlying in ["SENSEX", "BANKEX", "SENSEX50"]:
        underlying_exchange, fo_exchange = "BSE_INDEX", "BFO"
    else:
        underlying_exchange, fo_exchange = "NSE_INDEX", "NFO"   # <- MCX fell here
    lot_sizes = {"NIFTY": 65, "BANKNIFTY": 30, ...}              # <- no MCX entries
    lot_size = lot_sizes.get(underlying, 75)                     # <- silent wrong default

Any MCX underlying (GOLDM, CRUDEOIL, SILVERM, NATURALGAS, COPPER) fell
through both defaults: it resolved to NFO/NSE_INDEX instead of MCX (wrong
exchange -- the option symbol lookup and expiry resolution would fail or
resolve the wrong contract entirely), and even if it hadn't, the quantity
would multiply by a wrong flat lot size (75 or 65) instead of the
commodity's real, DB-sourced lot size.

Fix: both functions now read the F&O exchange the frontend already writes
into node_data ("exchange": NFO/BFO/MCX -- set by ConfigPanel.tsx when the
underlying is picked from INDEX_SYMBOLS, which now includes the 5 MCX
commodities), falling back to the name-based guess (now MCX-aware) only
for older saved Flow JSON that predates this. Lot size is resolved live
via _resolve_flow_lot_size() (mirrors signal_engine.py's _lookup_lot_size)
instead of a hardcoded table.

All broker/DB calls are mocked -- no live network or database access.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_KEY", "test-app-key-" + "0" * 52)
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-" + "0" * 52)

import pytest  # noqa: E402

from services.flow_executor_service import (  # noqa: E402
    NodeExecutor,
    WorkflowContext,
    _MCX_COMMODITIES,
    _resolve_flow_lot_size,
)


def _executor(api_key="fake-api-key"):
    client = MagicMock()
    client.api_key = api_key
    client.options_order.return_value = {"status": "success"}
    client.options_multi_order.return_value = {"status": "success"}
    return NodeExecutor(client=client, context=WorkflowContext(), logs=[])


class TestMcxCommodityConstant:
    def test_expected_mcx_commodities_are_recognized(self):
        assert _MCX_COMMODITIES == {"GOLDM", "CRUDEOIL", "SILVERM", "NATURALGAS", "COPPER"}


class TestResolveFlowLotSize:
    def test_returns_live_lot_size_for_mcx_commodity(self):
        fake_symbol_info = MagicMock(lotsize=100)
        with patch("services.expiry_service.resolve_expiry_type", return_value="26AUG26"), \
             patch(
                 "services.option_symbol_service.get_option_symbol",
                 return_value=(True, {"symbol": "CRUDEOIL26AUG266500CE", "exchange": "MCX"}, 200),
             ), \
             patch("database.token_db_enhanced.get_symbol_info", return_value=fake_symbol_info):
            lot_size = _resolve_flow_lot_size("CRUDEOIL", "MCX", "current_month", "fake-api-key")

        assert lot_size == 100

    def test_returns_1_when_no_api_key(self):
        assert _resolve_flow_lot_size("CRUDEOIL", "MCX", "current_month", "") == 1

    def test_returns_1_when_expiry_unresolvable(self):
        with patch("services.expiry_service.resolve_expiry_type", return_value=None):
            lot_size = _resolve_flow_lot_size("CRUDEOIL", "MCX", "current_month", "fake-api-key")
        assert lot_size == 1

    def test_returns_1_when_symbol_lookup_fails(self):
        with patch("services.expiry_service.resolve_expiry_type", return_value="26AUG26"), \
             patch(
                 "services.option_symbol_service.get_option_symbol",
                 return_value=(False, {"message": "not found"}, 400),
             ):
            lot_size = _resolve_flow_lot_size("CRUDEOIL", "MCX", "current_month", "fake-api-key")
        assert lot_size == 1


class TestExecuteOptionsOrderMcxResolution:
    def test_frontend_supplied_mcx_exchange_is_used(self):
        """The ConfigPanel.tsx underlying dropdown writes node_data['exchange']
        = 'MCX' for GOLDM/CRUDEOIL/etc (INDEX_SYMBOLS) -- this must be
        honored directly rather than re-derived from the underlying name."""
        executor = _executor()
        node_data = {
            "underlying": "CRUDEOIL",
            "exchange": "MCX",
            "expiryType": "current_month",
            "quantity": 1,
            "offset": "ATM",
            "optionType": "CE",
            "action": "BUY",
        }
        with patch("services.expiry_service.resolve_expiry_type", return_value="26AUG26"), \
             patch(
                 "services.option_symbol_service.get_option_symbol",
                 return_value=(True, {"symbol": "CRUDEOIL26AUG266500CE", "exchange": "MCX"}, 200),
             ), \
             patch("database.token_db_enhanced.get_symbol_info", return_value=MagicMock(lotsize=100)):
            result = executor.execute_options_order(node_data)

        assert result["status"] == "success"
        call_kwargs = executor.client.options_order.call_args.kwargs
        assert call_kwargs["exchange"] == "MCX"
        assert call_kwargs["quantity"] == 100  # 1 lot * live lot size 100

    def test_mcx_underlying_resolves_correctly_without_frontend_exchange_field(self):
        """Older saved Flow JSON (predating the MCX-aware INDEX_SYMBOLS
        list) has no 'exchange' field at all -- the name-based fallback
        must still recognize MCX commodities instead of defaulting to
        NSE_INDEX/NFO."""
        executor = _executor()
        node_data = {
            "underlying": "GOLDM",
            "expiryType": "current_month",
            "quantity": 1,
            "offset": "ATM",
            "optionType": "CE",
            "action": "BUY",
        }
        with patch("services.expiry_service.resolve_expiry_type", return_value="26AUG26") as mock_resolve, \
             patch(
                 "services.option_symbol_service.get_option_symbol",
                 return_value=(True, {"symbol": "GOLDM26AUG2670000CE", "exchange": "MCX"}, 200),
             ), \
             patch("database.token_db_enhanced.get_symbol_info", return_value=MagicMock(lotsize=10)):
            result = executor.execute_options_order(node_data)

        assert result["status"] == "success"
        # resolve_expiry_type is called twice (once for the live lot-size
        # lookup, once for the order's own expiry resolution) -- both calls
        # must resolve against MCX, not NFO.
        assert mock_resolve.call_count == 2
        for call in mock_resolve.call_args_list:
            assert call.args[:3] == ("GOLDM", "MCX", "current_month")
        call_kwargs = executor.client.options_order.call_args.kwargs
        assert call_kwargs["exchange"] == "MCX"

    def test_nifty_still_resolves_to_nse_index_nfo_unaffected(self):
        """Existing NFO index behavior must be unchanged by this fix."""
        executor = _executor()
        node_data = {
            "underlying": "NIFTY",
            "exchange": "NFO",
            "expiryType": "current_week",
            "quantity": 1,
            "offset": "ATM",
            "optionType": "CE",
            "action": "BUY",
        }
        with patch("services.expiry_service.resolve_expiry_type", return_value="07AUG26"), \
             patch(
                 "services.option_symbol_service.get_option_symbol",
                 return_value=(True, {"symbol": "NIFTY07AUG2624500CE", "exchange": "NFO"}, 200),
             ), \
             patch("database.token_db_enhanced.get_symbol_info", return_value=MagicMock(lotsize=65)):
            result = executor.execute_options_order(node_data)

        assert result["status"] == "success"
        call_kwargs = executor.client.options_order.call_args.kwargs
        assert call_kwargs["exchange"] == "NSE_INDEX"
        assert call_kwargs["quantity"] == 65


class TestExecuteOptionsMultiOrderMcxResolution:
    def test_mcx_multi_order_uses_live_lot_size_per_leg(self):
        executor = _executor()
        node_data = {
            "underlying": "CRUDEOIL",
            "exchange": "MCX",
            "expiryType": "current_month",
            "quantity": 1,
            "legs": [
                {"offset": "ATM", "optionType": "CE", "action": "BUY", "quantity": 1},
                {"offset": "OTM1", "optionType": "PE", "action": "SELL", "quantity": 1},
            ],
        }
        with patch("services.expiry_service.resolve_expiry_type", return_value="26AUG26"), \
             patch(
                 "services.option_symbol_service.get_option_symbol",
                 return_value=(True, {"symbol": "CRUDEOIL26AUG266500CE", "exchange": "MCX"}, 200),
             ), \
             patch("database.token_db_enhanced.get_symbol_info", return_value=MagicMock(lotsize=100)):
            result = executor.execute_options_multi_order(node_data)

        assert result["status"] == "success"
        call_kwargs = executor.client.options_multi_order.call_args.kwargs
        assert call_kwargs["exchange"] == "MCX"
        legs = call_kwargs["legs"]
        assert all(leg["quantity"] == 100 for leg in legs)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
