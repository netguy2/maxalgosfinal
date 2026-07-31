"""Regression test for: MCX (and other F&O) symbols never appeared in the
Charts page's symbol search.

Root cause: frontend/src/pages/Charts.tsx's search call sent only
`?q=<query>`, never an `exchange` param. blueprints/search.py's
api_search() decides which search engine handles a request PER EXCHANGE:
`is_fno_path = has_fno_filters or (exch is not None and exch in
FNO_EXCHANGES)`. With no exchange supplied, `exch_iter` degenerates to a
single `[None]` iteration, so `is_fno_path` is always False and every
query -- including one for an MCX commodity like GOLDM -- was routed to
`enhanced_search_symbols`, a plain SymToken table LIKE-search that never
consults the FNO in-memory cache MCX/NFO/BFO/CDS contracts are indexed in
(database/token_db_enhanced.py). Options Chain / Strategy Builder never
hit this bug because they already pass an explicit exchange.

Fix: Charts.tsx now sends every broker-supported exchange (comma-
separated) via useSupportedExchanges()'s allExchanges, so MCX rows are
routed through fno_search_symbols like every other F&O exchange already
was.

This test exercises blueprints/search.py's api_search() dispatch logic
directly -- confirming that when 'MCX' is present anywhere in a
comma-separated `exchange` param (mixed with plain equity exchanges), the
FNO-cache engine is invoked for the MCX leg specifically, not just
silently skipped. All DB/cache calls are mocked -- no live data.
"""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_KEY", "test-app-key-" + "0" * 52)
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-" + "0" * 52)

import pytest  # noqa: E402
from flask import Flask  # noqa: E402

import restx_api  # noqa: F401,E402
import blueprints.search as search_bp  # noqa: E402


@pytest.fixture()
def app():
    application = Flask(__name__)
    application.secret_key = "test-secret"
    application.register_blueprint(search_bp.search_bp)
    return application


@pytest.fixture()
def client(app, monkeypatch):
    monkeypatch.setattr("utils.session.is_session_valid", lambda: True)
    monkeypatch.setattr("utils.session._subscription_blocks_request", lambda username: False)
    return app.test_client()


class TestMultiExchangeSearchRoutesMcxToFnoEngine:
    def test_mcx_among_mixed_exchanges_uses_fno_search(self, client, monkeypatch):
        """A comma-separated exchange list mixing equity (NSE/BSE) and F&O
        (MCX) exchanges must route the MCX leg through fno_search_symbols,
        not silently through the plain-table search."""
        fno_calls = []
        plain_calls = []

        def fake_fno_search(**kwargs):
            fno_calls.append(kwargs)
            return [
                {
                    "symbol": "GOLDM26AUG266500CE",
                    "brsymbol": "GOLDM26AUG266500CE",
                    "name": "GOLDM",
                    "exchange": "MCX",
                    "brexchange": "MCX",
                    "token": "12345",
                    "expiry": "26-AUG-26",
                    "strike": 6500,
                    "instrumenttype": "OPTFUT",
                }
            ]

        def fake_enhanced_search(query, exchange, limit=None):
            plain_calls.append((query, exchange))
            return []

        monkeypatch.setattr(search_bp, "fno_search_symbols", fake_fno_search)
        monkeypatch.setattr(search_bp, "enhanced_search_symbols", fake_enhanced_search)
        with patch("database.qty_freeze_db.get_freeze_qty_for_option", return_value=1):
            resp = client.get("/search/api/search?q=gold&exchange=NSE,BSE,MCX")

        assert resp.status_code == 200
        data = resp.get_json()

        # MCX must have gone through the FNO engine.
        assert any(call.get("exchange") == "MCX" for call in fno_calls)
        # NSE/BSE must have gone through the plain-table engine.
        plain_exchanges = {exch for _, exch in plain_calls}
        assert plain_exchanges == {"NSE", "BSE"}
        # The MCX result must actually surface in the aggregated response.
        assert any(r["exchange"] == "MCX" for r in data["results"])

    def test_no_exchange_param_never_reaches_fno_engine(self, client, monkeypatch):
        """Contrast/regression case: this is the exact old broken behavior
        -- confirms it without an exchange param, MCX can never be found
        (documents the bug this fix addresses, not a desired behavior)."""
        fno_calls = []

        def fake_fno_search(**kwargs):
            fno_calls.append(kwargs)
            return []

        monkeypatch.setattr(search_bp, "fno_search_symbols", fake_fno_search)
        monkeypatch.setattr(search_bp, "enhanced_search_symbols", lambda *a, **k: [])

        resp = client.get("/search/api/search?q=gold")

        assert resp.status_code == 200
        assert fno_calls == []  # confirms the FNO engine is never reached


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
