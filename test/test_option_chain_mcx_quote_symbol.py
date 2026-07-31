"""Regression test for: MCX Option Chain fails with "Live market data is
not available for the current broker" / "Failed to load option chain"
even when the connected broker (e.g. Zebu) genuinely supports live quotes.

Root cause: services/option_chain_service.py's get_option_chain() resolved
the underlying-LTP quote symbol as

    quote_symbol = base_symbol if embedded_expiry else underlying

for EVERY non-crypto exchange, including MCX/CDS. But MCX/CDS commodities
have no standalone spot/index symbol -- GOLDM/CRUDEOIL are never
themselves quotable, only their dated futures/option contracts are
(services/option_symbol_service.py's get_option_symbol already has this
exact MCX/CDS special case; option_chain_service.py's separate,
independent implementation never got the same fix). So every MCX/CDS
option chain request tried to fetch a quote for a symbol that structurally
cannot exist ("GOLDM" instead of "GOLDM28AUG26FUT"), the quote call failed,
the hardcoded index-only fallback table (NIFTY/BANKNIFTY/SENSEX/...) has
no MCX entries either, and the request landed on the generic "connect a
broker that supports live quotes" error -- which is misleading boilerplate
unrelated to the actual broker capability; it fires purely when
underlying_ltp ends up None/0.0 for ANY reason.

Fix: for MCX/CDS, quote_symbol is now resolved via get_futures_symbol()
(the same live-contract-resolution helper signal_engine.py's live FUT/OPT
resolution and Flow's executor already use), which finds a genuinely
quotable front-month contract instead of the bare underlying.

All broker/DB calls are mocked -- nothing hits a live broker.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_KEY", "test-app-key-" + "0" * 52)
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-" + "0" * 52)

import pytest  # noqa: E402

import restx_api  # noqa: F401,E402

import services.option_chain_service as ocs  # noqa: E402


class TestMcxQuoteSymbolResolution:
    def test_mcx_resolves_futures_contract_for_ltp_not_bare_underlying(self, monkeypatch):
        """The core regression: for MCX, get_quotes() must be called with
        the resolved futures contract symbol, never the bare 'GOLDM'."""
        monkeypatch.setattr(
            ocs, "get_futures_symbol",
            lambda underlying, exchange, expiry, api_key: {
                "symbol": "GOLDM28AUG26FUT", "exchange": "MCX"
            },
        )

        get_quotes_calls = []

        def fake_get_quotes(symbol, exchange, api_key):
            get_quotes_calls.append((symbol, exchange))
            return True, {"data": {"ltp": 71500.0, "prev_close": 71200.0}}, 200

        monkeypatch.setattr(ocs, "get_quotes", fake_get_quotes)
        monkeypatch.setattr(ocs, "get_available_strikes", lambda *a, **k: [])

        result = ocs.get_option_chain("GOLDM", "MCX", "28AUG26", 10, "fake-api-key")

        assert len(get_quotes_calls) == 1
        symbol_used, exchange_used = get_quotes_calls[0]
        assert symbol_used == "GOLDM28AUG26FUT"
        assert exchange_used == "MCX"
        # Confirms the LTP was actually picked up (not lost/overwritten) --
        # the function proceeds past the LTP step to the strikes lookup,
        # which we short-circuited to an empty list for this focused test.
        success, response, status = result
        assert success is False
        assert "No strikes found" in response["message"]

    def test_mcx_falls_back_to_bare_underlying_with_warning_when_no_futures_found(self, monkeypatch):
        """If no live futures contract can be resolved at all (e.g. stale
        master contract), degrade to the old bare-underlying behavior
        rather than crashing -- this will still fail to quote, but that's
        the pre-existing, honest failure mode, not a regression."""
        monkeypatch.setattr(ocs, "get_futures_symbol", lambda *a, **k: None)

        get_quotes_calls = []

        def fake_get_quotes(symbol, exchange, api_key):
            get_quotes_calls.append((symbol, exchange))
            return False, {"message": "not found"}, 404

        monkeypatch.setattr(ocs, "get_quotes", fake_get_quotes)
        monkeypatch.setattr(ocs, "get_ltp_value", lambda *a, **k: None, raising=False)

        with patch("services.market_data_service.get_ltp_value", return_value=None):
            result = ocs.get_option_chain("GOLDM", "MCX", "28AUG26", 10, "fake-api-key")

        assert len(get_quotes_calls) == 1
        symbol_used, _ = get_quotes_calls[0]
        assert symbol_used == "GOLDM"  # bare underlying, the honest degraded fallback
        success, response, status = result
        assert success is False
        assert status == 503

    def test_nse_index_unaffected_still_uses_base_symbol(self, monkeypatch):
        """Contrast case: NIFTY/NFO must behave exactly as before -- this
        fix must not touch the NSE/BSE index path at all."""
        get_futures_called = []
        monkeypatch.setattr(
            ocs, "get_futures_symbol",
            lambda *a, **k: get_futures_called.append(True) or None,
        )

        get_quotes_calls = []

        def fake_get_quotes(symbol, exchange, api_key):
            get_quotes_calls.append((symbol, exchange))
            return True, {"data": {"ltp": 24200.0, "prev_close": 24100.0}}, 200

        monkeypatch.setattr(ocs, "get_quotes", fake_get_quotes)
        monkeypatch.setattr(ocs, "get_available_strikes", lambda *a, **k: [])

        ocs.get_option_chain("NIFTY", "NFO", "28AUG26", 10, "fake-api-key")

        assert get_futures_called == []  # get_futures_symbol never called for NFO
        symbol_used, exchange_used = get_quotes_calls[0]
        assert symbol_used == "NIFTY"
        assert exchange_used == "NSE_INDEX"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
