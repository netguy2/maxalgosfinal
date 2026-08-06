"""Regression tests for a real incident: symtoken had no `broker` column,
so it could only ever hold ONE broker's instrument master at a time.
delete_symtoken_table() wiped the ENTIRE table on every download, and
should_download_master_contract() forced a re-download whenever
get_last_downloaded_broker() differed from the broker now logging in --
because otherwise a user on a different broker would see stale/wrong data.

On a multi-broker instance, this meant login activity alternating across
brokers (User A on Zerodha, then User B on Dhan, then User A again)
repeatedly wiped and rebuilt the whole symbol table, even though each
individual broker's own once-a-day-after-cutoff rule was already correct.

The fix: SymToken.broker lets every connected broker's rows persist
side-by-side. Downloads are now scoped deletes+inserts per broker instead
of a full-table wipe, and should_download_master_contract() no longer
forces a re-download on a broker switch -- each broker's own
last_download_time is the only thing that matters.

These tests pin that contract so it cannot silently regress back to a
single-broker-at-a-time shared table.
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import database.symbol as symbol_db  # noqa: E402
import database.master_contract_status_db as status_db  # noqa: E402
import utils.auth_utils as auth_utils  # noqa: E402

BROKER_A = "__test_pb_zerodha__"
BROKER_B = "__test_pb_dhan__"


def _purge(*brokers):
    for broker in brokers:
        symbol_db.SymToken.query.filter(symbol_db.SymToken.broker == broker).delete(
            synchronize_session=False
        )
    symbol_db.db_session.commit()

    session = status_db.SessionLocal()
    try:
        for broker in brokers:
            session.query(status_db.MasterContractStatus).filter_by(broker=broker).delete()
        session.commit()
    finally:
        session.close()


def _seed_symbol(broker: str, symbol: str, token: str):
    row = symbol_db.SymToken(
        symbol=symbol,
        brsymbol=symbol,
        name=symbol,
        exchange="NFO",
        brexchange="NFO",
        token=token,
        broker=broker,
    )
    symbol_db.db_session.add(row)
    symbol_db.db_session.commit()


def _record_download(broker: str, when: datetime):
    session = status_db.SessionLocal()
    try:
        row = status_db.MasterContractStatus(
            broker=broker,
            status="success",
            message="test seed",
            last_updated=when,
            is_ready=True,
            last_download_time=when,
            download_date=when.date(),
        )
        session.add(row)
        session.commit()
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _clean():
    _purge(BROKER_A, BROKER_B)
    yield
    _purge(BROKER_A, BROKER_B)


class TestPerBrokerStorageIsolation:
    """SymToken.broker must let every connected broker's rows persist
    side-by-side -- THE regression test: broker A's data must survive
    broker B's download and vice versa."""

    def test_two_brokers_data_coexist(self):
        _seed_symbol(BROKER_A, "NIFTY28AUG2524000CE", "111")
        _seed_symbol(BROKER_B, "NIFTY28AUG2524000CE", "222")

        a_rows = symbol_db.SymToken.query.filter(symbol_db.SymToken.broker == BROKER_A).all()
        b_rows = symbol_db.SymToken.query.filter(symbol_db.SymToken.broker == BROKER_B).all()

        assert len(a_rows) == 1
        assert len(b_rows) == 1
        assert a_rows[0].token == "111"
        assert b_rows[0].token == "222"

    def test_delete_symtoken_table_scoped_to_one_broker_only(self):
        """delete_symtoken_table(broker) must never wipe another broker's
        rows -- this is the exact bug that forced repeat downloads."""
        _seed_symbol(BROKER_A, "NIFTY28AUG2524000CE", "111")
        _seed_symbol(BROKER_B, "NIFTY28AUG2524000CE", "222")

        symbol_db.delete_symtoken_table(BROKER_A)

        a_rows = symbol_db.SymToken.query.filter(symbol_db.SymToken.broker == BROKER_A).all()
        b_rows = symbol_db.SymToken.query.filter(symbol_db.SymToken.broker == BROKER_B).all()

        assert a_rows == []
        assert len(b_rows) == 1, "Broker B's data must survive Broker A's delete"

    def test_delete_symtoken_table_unscoped_is_still_full_wipe(self):
        """Legacy no-argument call (pre-migration callers, admin Force
        Download without a broker context) still wipes everything -- this
        must be an explicit opt-in, not the default per-broker path."""
        _seed_symbol(BROKER_A, "NIFTY28AUG2524000CE", "111")
        _seed_symbol(BROKER_B, "NIFTY28AUG2524000CE", "222")

        symbol_db.delete_symtoken_table()

        assert symbol_db.SymToken.query.filter(symbol_db.SymToken.broker == BROKER_A).all() == []
        assert symbol_db.SymToken.query.filter(symbol_db.SymToken.broker == BROKER_B).all() == []


class TestReadFunctionsScopeByBroker:
    def test_enhanced_search_symbols_scopes_to_broker(self):
        _seed_symbol(BROKER_A, "NIFTY28AUG2524000CE", "111")
        _seed_symbol(BROKER_B, "NIFTY28AUG2524000CE", "222")

        a_results = symbol_db.enhanced_search_symbols("NIFTY28AUG2524000CE", broker=BROKER_A)
        b_results = symbol_db.enhanced_search_symbols("NIFTY28AUG2524000CE", broker=BROKER_B)

        assert {r.token for r in a_results} == {"111"}
        assert {r.token for r in b_results} == {"222"}

    def test_fno_search_symbols_db_scopes_to_broker(self):
        _seed_symbol(BROKER_A, "NIFTY28AUG2524000CE", "111")
        _seed_symbol(BROKER_B, "NIFTY28AUG2524000CE", "222")

        a_results = symbol_db.fno_search_symbols_db(exchange="NFO", broker=BROKER_A)
        b_results = symbol_db.fno_search_symbols_db(exchange="NFO", broker=BROKER_B)

        assert {r["token"] for r in a_results} == {"111"}
        assert {r["token"] for r in b_results} == {"222"}


class TestShouldDownloadNoLongerForcesOnBrokerSwitch:
    """THE regression test for the daily-gate logic: a broker switch must
    no longer force a re-download now that symtoken persists every
    broker's rows independently."""

    def test_broker_switch_does_not_force_redownload_when_recent_and_after_cutoff(self):
        now = datetime.now()
        # Broker A downloaded recently (today, well after any reasonable cutoff).
        _record_download(BROKER_A, now - timedelta(minutes=5))
        # Broker B downloaded even more recently -- would have been
        # "the last downloaded broker" under the old logic.
        _record_download(BROKER_B, now - timedelta(minutes=1))

        # Force a very early cutoff so "after cutoff" is true regardless of
        # what time this test happens to run.
        os.environ["MASTER_CONTRACT_CUTOFF_TIME"] = "00:00"
        try:
            should_download, reason = auth_utils.should_download_master_contract(BROKER_A)
        finally:
            del os.environ["MASTER_CONTRACT_CUTOFF_TIME"]

        assert should_download is False, (
            f"Broker A should reuse its own cached download even though Broker B "
            f"downloaded more recently -- got reason: {reason!r}"
        )

    def test_each_broker_still_gated_by_its_own_cutoff_independently(self):
        now = datetime.now()
        # Broker A downloaded today but BEFORE a late cutoff -- must still
        # re-download on its own account, independent of Broker B.
        _record_download(BROKER_A, now.replace(hour=1, minute=0, second=0, microsecond=0))
        _record_download(BROKER_B, now - timedelta(minutes=1))

        os.environ["MASTER_CONTRACT_CUTOFF_TIME"] = "23:59"
        try:
            should_download, reason = auth_utils.should_download_master_contract(BROKER_A)
        finally:
            del os.environ["MASTER_CONTRACT_CUTOFF_TIME"]

        assert should_download is True, (
            f"Broker A downloaded before its own cutoff today, so it must still "
            f"re-download regardless of Broker B's status -- got reason: {reason!r}"
        )
