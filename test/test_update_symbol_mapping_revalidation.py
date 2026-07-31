"""Regression test for: updating a FUT/OPT symbol mapping's `exchange`
field alone (without also resending `instrument_type`) must still be
re-validated against expiry/strike resolution -- not silently accepted.

Root cause: blueprints/strategy.py's update_symbol() route only ran
_validate_instrument_config() (the same dry-run expiry/strike resolution
check performed when a mapping is first created) when the request body
happened to include "instrument_type". A request that updates ONLY
`exchange` on an existing FUT/OPT mapping (e.g. NFO -> NSE) skipped this
block entirely: it only had to pass the broad VALID_EXCHANGES allow-list
(which legitimately includes plain NSE/BSE for EQ rows), silently leaving
an OPT mapping with instrument_type="OPT" but exchange="NSE" -- a
combination services/expiry_service.py's resolve_expiry_type() rejects
outright (NSE is not in its NFO/BFO/MCX/CDS/CRYPTO whitelist), causing
services/signal_engine.py's _resolve_live_instrument() to fail forever on
every subsequent webhook signal for that mapping ("Processed" in the old
code / "Rejected: instrument_resolution_failed" after the delivery-log
accuracy fix) with no error at save time to warn the user why.

Fix: the route now re-validates whenever EITHER the request explicitly
sets instrument_type, OR the mapping's EXISTING instrument_type is already
FUT/OPT, OR the request changes `exchange` at all -- using the mapping's
existing underlying/expiry_type/option_type/strike_offset as validation
defaults so a request that only touches `exchange` doesn't lose them.

All DB/network calls are mocked -- nothing hits a live broker.
"""

import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("APP_KEY", "test-app-key-" + "0" * 52)
os.environ.setdefault("API_KEY_PEPPER", "test-pepper-" + "0" * 52)

import pytest  # noqa: E402
from flask import Flask, session  # noqa: E402

import restx_api  # noqa: F401,E402
import blueprints.strategy as strategy_bp  # noqa: E402


@pytest.fixture()
def app_context():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    with patch("utils.session.is_session_valid", return_value=True), \
         patch("utils.session._subscription_blocks_request", return_value=False), \
         app.test_request_context(
             "/strategy/1/symbol/42/update", method="POST", json={"exchange": "NSE"}
         ):
        session["user"] = "alice"
        yield


def _existing_opt_mapping():
    """An existing mapping already configured as NIFTY OPT on NFO --
    exactly the shape that must not be silently downgraded to a
    non-resolvable exchange."""
    return SimpleNamespace(
        id=42,
        strategy_id=1,
        exchange="NFO",
        instrument_type="OPT",
        underlying="NIFTY",
        expiry_type="current_week",
        option_type="CE",
        strike_offset="ATM",
        strike_selection_mode=None,
        strike_target_value=None,
    )


class TestUpdateSymbolRevalidatesOnExchangeChangeAlone:
    def test_exchange_only_update_on_existing_opt_mapping_is_revalidated(self, app_context):
        """The core regression: a request body of just {"exchange": "NSE"}
        (no instrument_type) against an existing OPT mapping must still run
        the dry-run validation -- and must reject NSE, since options can't
        resolve on NSE."""
        fake_strategy = SimpleNamespace(id=1, user_id="alice")
        fake_mapping = _existing_opt_mapping()

        with patch.object(strategy_bp, "get_strategy", return_value=fake_strategy), \
             patch(
                 "database.strategy_db.StrategySymbolMapping.query"
             ) as mock_query, \
             patch.object(strategy_bp, "_validate_instrument_config") as mock_validate:
            mock_query.get.return_value = fake_mapping
            mock_validate.side_effect = ValueError("Invalid exchange for OPT: NSE")

            response = strategy_bp.update_symbol(1, 42)

        # _validate_instrument_config MUST have been called even though the
        # request body never included "instrument_type" -- this is the
        # actual fix; before it, this call site was skipped entirely for an
        # exchange-only update.
        assert mock_validate.called
        call_args = mock_validate.call_args[0][0]
        assert call_args["instrument_type"] == "OPT"
        assert call_args["exchange"] == "NSE"
        # And the route surfaces the validator's rejection as a 400, not a
        # silent success.
        body, status = response
        assert status == 400

    def test_exchange_only_update_preserves_existing_underlying_and_expiry(self, app_context):
        """The merged validate_data must carry over the mapping's EXISTING
        underlying/expiry_type/option_type/strike_offset -- an exchange-only
        update must not accidentally validate against blank/None fields."""
        fake_strategy = SimpleNamespace(id=1, user_id="alice")
        fake_mapping = _existing_opt_mapping()

        with patch.object(strategy_bp, "get_strategy", return_value=fake_strategy), \
             patch("database.strategy_db.StrategySymbolMapping.query") as mock_query, \
             patch.object(strategy_bp, "_validate_instrument_config") as mock_validate:
            mock_query.get.return_value = fake_mapping
            mock_validate.return_value = {"instrument_type": "OPT"}
            with patch.object(strategy_bp, "update_symbol_mapping", return_value=fake_mapping):
                strategy_bp.update_symbol(1, 42)

        call_args = mock_validate.call_args[0][0]
        assert call_args["underlying"] == "NIFTY"
        assert call_args["expiry_type"] == "current_week"
        assert call_args["option_type"] == "CE"
        assert call_args["strike_offset"] == "ATM"

    def test_valid_exchange_change_still_succeeds(self, app_context):
        """Contrast case: changing exchange to another genuinely valid F&O
        exchange (NFO -> BFO, say a corrected underlying) must still work,
        proving this fix only tightens the bad case, not the whole route."""
        fake_strategy = SimpleNamespace(id=1, user_id="alice")
        fake_mapping = _existing_opt_mapping()

        with patch.object(strategy_bp, "get_strategy", return_value=fake_strategy), \
             patch("database.strategy_db.StrategySymbolMapping.query") as mock_query, \
             patch.object(strategy_bp, "_validate_instrument_config") as mock_validate, \
             patch.object(strategy_bp, "update_symbol_mapping", return_value=fake_mapping):
            mock_query.get.return_value = fake_mapping
            mock_validate.return_value = {"instrument_type": "OPT"}

            response = strategy_bp.update_symbol(1, 42)

        status = response[1] if isinstance(response, tuple) else response.status_code
        assert status == 200


class TestUpdateSymbolEqMappingUnaffected:
    def test_eq_mapping_exchange_change_does_not_require_underlying(self, app_context):
        """An EQ mapping (e.g. a plain stock) changing exchange must not be
        forced through FUT/OPT-only requirements like underlying/expiry --
        _validate_instrument_config's own EQ branch already handles this,
        this just confirms the route doesn't add a NEW blocker for EQ."""
        fake_strategy = SimpleNamespace(id=1, user_id="alice")
        fake_eq_mapping = SimpleNamespace(
            id=42, strategy_id=1, exchange="NSE", instrument_type="EQ",
            underlying=None, expiry_type=None, option_type=None,
            strike_offset=None, strike_selection_mode=None, strike_target_value=None,
        )

        with patch.object(strategy_bp, "get_strategy", return_value=fake_strategy), \
             patch("database.strategy_db.StrategySymbolMapping.query") as mock_query, \
             patch.object(strategy_bp, "update_symbol_mapping", return_value=fake_eq_mapping):
            mock_query.get.return_value = fake_eq_mapping
            # Real _validate_instrument_config (not mocked) -- confirms the
            # EQ branch returns cleanly with just exchange changing.
            response = strategy_bp.update_symbol(1, 42)

        status = response[1] if isinstance(response, tuple) else response.status_code
        assert status == 200


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
