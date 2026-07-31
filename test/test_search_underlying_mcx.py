"""Regression test for: MCX commodities never appeared in the MaxHook
webhook strategy Configure Symbols page's "Underlying" search, on ANY
tab (Options/Futures), regardless of exchange selected.

Root cause: blueprints/strategy.py's search_underlying_symbols() (route
/strategy/search/underlying) queried SymToken filtered to
`instrumenttype IN ("EQ", "INDEX")` unconditionally. NSE/BSE indices and
stocks have a standalone row in one of those types (e.g. NIFTY as
instrumenttype="INDEX"), but MCX commodities do NOT -- every MCX SymToken
row IS a dated contract (FUT/OPTFUT/CE/PE, e.g. "GOLDM26AUG26FUT"), never
a bare "GOLDM" row of type EQ/INDEX. So this endpoint could never return
an MCX commodity no matter what the user searched or selected -- it had
no code path capable of finding one.

Separately, the frontend (frontend/src/pages/strategy/ConfigureSymbols.tsx's
runSearch()) silently dropped the exchange filter for the OPT/FUT
underlying-search path entirely -- `strategyApi.searchUnderlyingSymbols(query)`
never even sent the caller's chosen exchange to the backend. Both bugs
combined meant MCX was undiscoverable from this specific page even though
Options Chain, Strategy Builder, Flow, and Charts (fixed in earlier
passes) all correctly support it.

Fix: for MCX/CDS/NCDEX (F&O-only exchanges with no EQ/INDEX row),
search_underlying_symbols() now resolves via
get_distinct_underlyings_cached(exchange, include_futures=True) -- the
same cache-backed lookup already used correctly elsewhere in this file
(get_underlying_lotsize) -- instead of the EQ/INDEX table query. The
frontend now passes `exchange` through on every call site.

All DB/cache calls are mocked -- nothing hits a live broker.
"""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_KEY", "test-app-key-" + "0" * 52)
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-" + "0" * 52)

import pytest  # noqa: E402
from flask import Flask  # noqa: E402

import restx_api  # noqa: F401,E402
import blueprints.strategy as strategy_bp  # noqa: E402


@pytest.fixture()
def app():
    application = Flask(__name__)
    application.secret_key = "test-secret"
    application.register_blueprint(strategy_bp.strategy_bp)
    return application


@pytest.fixture()
def client(app, monkeypatch):
    monkeypatch.setattr("utils.session.is_session_valid", lambda: True)
    monkeypatch.setattr("utils.session._subscription_blocks_request", lambda username: False)
    return app.test_client()


class TestSearchUnderlyingMcx:
    def test_mcx_exchange_resolves_via_fno_cache_not_eq_index_table(self, client, monkeypatch):
        """The core regression: searching 'GOLD' with exchange=MCX must
        find GOLDM via the FNO cache, since no EQ/INDEX row for it exists."""
        monkeypatch.setattr(
            "database.token_db_enhanced.get_distinct_underlyings_cached",
            lambda exchange=None, include_futures=False: ["GOLDM", "GOLD1"] if exchange == "MCX" else [],
        )
        monkeypatch.setattr(
            "database.token_db_enhanced.fno_search_symbols",
            lambda underlying=None, exchange=None, limit=1: (
                [{"lotsize": 100, "tick_size": 1.0}] if underlying == "GOLDM" else []
            ),
        )

        resp = client.get("/strategy/search/underlying?q=GOLD&exchange=MCX")

        assert resp.status_code == 200
        data = resp.get_json()
        symbols = {r["symbol"] for r in data["results"]}
        assert "GOLDM" in symbols
        goldm_row = next(r for r in data["results"] if r["symbol"] == "GOLDM")
        assert goldm_row["exchange"] == "MCX"
        assert goldm_row["lotsize"] == 100

    def test_nse_exchange_still_uses_eq_index_table_unaffected(self, client, monkeypatch):
        """Contrast case: NSE/BSE underlying search must be completely
        unchanged by this fix (it has real EQ/INDEX rows to query)."""
        fake_row = MagicMock(symbol="NIFTY", exchange="NSE_INDEX", lotsize=65, tick_size=0.05)
        fake_row.name = "NIFTY 50"

        mock_query = MagicMock()
        mock_query.filter.return_value.limit.return_value.all.return_value = [fake_row]

        with patch("database.symbol.db_session") as mock_session:
            mock_session.query.return_value = mock_query
            resp = client.get("/strategy/search/underlying?q=NIFTY&exchange=NSE_INDEX")

        assert resp.status_code == 200
        data = resp.get_json()
        assert any(r["symbol"] == "NIFTY" for r in data["results"])

    def test_no_exchange_param_falls_back_to_eq_index_query(self, client, monkeypatch):
        """Backward compatibility: omitting `exchange` entirely (old
        frontend behavior, or a caller that hasn't picked an exchange yet)
        must not crash and must use the original EQ/INDEX path."""
        mock_query = MagicMock()
        mock_query.filter.return_value.limit.return_value.all.return_value = []

        with patch("database.symbol.db_session") as mock_session:
            mock_session.query.return_value = mock_query
            resp = client.get("/strategy/search/underlying?q=NIFTY")

        assert resp.status_code == 200
        assert resp.get_json() == {"results": []}

    def test_query_too_short_returns_empty_without_touching_cache(self, client, monkeypatch):
        called = []
        monkeypatch.setattr(
            "database.token_db_enhanced.get_distinct_underlyings_cached",
            lambda **kwargs: called.append(kwargs) or [],
        )

        resp = client.get("/strategy/search/underlying?q=G&exchange=MCX")

        assert resp.status_code == 200
        assert resp.get_json() == {"results": []}
        assert called == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
