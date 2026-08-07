"""Regression test: an equity symbol that doesn't exist must be rejected at
SAVE time, not silently accepted and discovered blind days later.

_validate_instrument_config() performed a live dry-run resolution for
FUT/OPT mappings ("so a bad config is rejected at add-time with a clear
error instead of silently failing on the first real webhook signal" -- its
own docstring) but returned immediately for EQ with no validation at all.

A mapping saved as ZOMATO after Zomato Ltd was renamed ETERNAL on NSE was
therefore accepted without complaint. Every subsequent indicator history
fetch failed with "Symbol 'ZOMATO' not found for exchange 'NSE'", and every
failure path collapses to 0.0, so the deployment reported "conditions not
yet met" for hours while completely blind to the market -- with status
Waiting, heartbeat Healthy and health 100% the whole time.

Validating at save time is the preventive half; deployment_service's
_symbol_exists_for_evaluation is the backstop for anything already saved or
renamed after the fact.
"""

import os
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DB = "sqlite:///" + os.path.join(tempfile.gettempdir(), "eq_symbol_validation_test.db")
os.environ.setdefault("DATABASE_URL", _DB)
os.environ.setdefault("SYMBOL_DATABASE_URL", _DB)

import pytest  # noqa: E402

import database.symbol as sym  # noqa: E402
from blueprints.strategy import _assert_equity_instrument_exists as check  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _seed():
    sym.Base.metadata.create_all(bind=sym.engine)
    sym.db_session.query(sym.SymToken).delete()
    # Mirror production: ETERNAL exists (post-rename), ZOMATO does not.
    for s, e in [("ETERNAL", "NSE"), ("ETERNAL", "BSE"), ("RELIANCE", "NSE")]:
        sym.db_session.add(
            sym.SymToken(symbol=s, brsymbol=s, exchange=e, token=str(uuid.uuid4())[:6])
        )
    sym.db_session.commit()
    yield
    sym.db_session.query(sym.SymToken).delete()
    sym.db_session.commit()


class TestGhostSymbolsAreRejected:
    def test_renamed_symbol_is_rejected(self):
        """THE regression test -- the exact production case."""
        with pytest.raises(ValueError) as exc:
            check("ZOMATO", "NSE")
        assert "ZOMATO" in str(exc.value)

    def test_error_explains_the_rename_possibility(self):
        """A bare 'not found' leaves the user stuck; naming the concrete
        rename is what makes it actionable."""
        with pytest.raises(ValueError) as exc:
            check("ZOMATO", "NSE")
        msg = str(exc.value)
        assert "renamed or delisted" in msg
        assert "ETERNAL" in msg

    def test_wrong_exchange_says_where_it_does_exist(self):
        with pytest.raises(ValueError) as exc:
            check("RELIANCE", "BSE")
        assert "does exist on NSE" in str(exc.value)


class TestValidSavesAreNotBlocked:
    def test_existing_symbol_passes(self):
        check("ETERNAL", "NSE")  # must not raise

    def test_case_and_whitespace_tolerated(self):
        check("  eternal  ", "nse")  # must not raise

    @pytest.mark.parametrize(
        "exchange", ["NSE_INDEX", "BSE_INDEX", "MCX_INDEX", "GLOBAL_INDEX"]
    )
    def test_index_exchanges_are_exempt(self, exchange):
        """Indices aren't ordinary instruments and resolve via a different
        path; validating them here would block every index strategy."""
        check("NIFTY", exchange)  # must not raise

    def test_unpopulated_exchange_does_not_block(self):
        """If the master contract has no rows for an exchange we cannot
        tell 'missing' from 'not downloaded yet' -- must not block the save
        on that ambiguity."""
        check("ANYTHING", "MCX")  # no MCX rows seeded; must not raise

    def test_missing_fields_defer_to_other_validation(self):
        check("", "NSE")
        check("ETERNAL", "")


class TestFailsOpenOnLookupError:
    def test_db_fault_does_not_block_the_save(self, monkeypatch):
        """A transient master-contract/DB fault must not stop users saving
        otherwise-valid mappings. The deployment-time guard is the backstop."""

        class Boom:
            def query(self, *a, **k):
                raise RuntimeError("symbol DB unavailable")

        monkeypatch.setattr(sym, "db_session", Boom())
        check("ZOMATO", "NSE")  # must not raise
