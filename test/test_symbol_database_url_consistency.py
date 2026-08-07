"""Regression test for a production split-brain: master contract WRITERS
and the symbol READER pointed at two different databases.

`SYMBOL_DATABASE_URL` deliberately lets the large, write-heavy,
fully-rebuildable `symtoken` (master contract) table live somewhere other
than the main application database -- in production it is SQLite while
everything else is PostgreSQL.

`database/symbol.py` (which READS symtoken) honoured that variable. All 27
broker `master_contract_db.py` modules (which WRITE symtoken) did not --
they each did a bare `os.getenv("DATABASE_URL")`. So downloads wrote
instruments into PostgreSQL while every lookup read an entirely different,
empty SQLite `symtoken`: two same-named tables in two databases.

Observed symptoms before the fix:
  * "column symtoken.broker does not exist" on every master contract
    download -- the broker column migration had only ever been applied to
    the READER's database, because that is the one database/symbol.py's
    init_db() touches.
  * Master contract downloads that reported success but never populated
    anything the app could actually see.
  * Slow pages, because every symbol lookup missed and fell through to a
    slower path.

Both sides now resolve through engine_factory.get_symbol_database_url().
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import glob  # noqa: E402
import re  # noqa: E402


def test_no_broker_module_reads_database_url_directly():
    """THE regression test: a broker master_contract_db.py that resolves its
    engine from a bare DATABASE_URL writes to the wrong database whenever
    SYMBOL_DATABASE_URL is set."""
    offenders = []
    for path in sorted(glob.glob("broker/*/database/master_contract_db.py")):
        src = open(path, encoding="utf-8").read()
        if "sharekhan" in path:
            # Deliberate exception: Sharekhan uses its own dedicated
            # sharekhan_symtoken.db file, never the shared symtoken table.
            continue
        if re.search(r'os\.getenv\(\s*["\']DATABASE_URL["\']\s*\)', src):
            offenders.append(path)

    assert offenders == [], (
        "These broker modules resolve symtoken's engine from a bare "
        "DATABASE_URL instead of get_symbol_database_url(), so they write "
        "the master contract into a different database than database/symbol.py "
        f"reads it from when SYMBOL_DATABASE_URL is set: {offenders}"
    )


def test_resolver_prefers_symbol_url_then_falls_back(monkeypatch):
    from database.engine_factory import get_symbol_database_url

    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h:5432/main")
    monkeypatch.setenv("SYMBOL_DATABASE_URL", "sqlite:///db/symbols.db")
    assert get_symbol_database_url() == "sqlite:///db/symbols.db"

    # Unset -> single-database installs must be completely unaffected.
    monkeypatch.delenv("SYMBOL_DATABASE_URL", raising=False)
    assert get_symbol_database_url() == "postgresql://u:p@h:5432/main"


def test_status_db_reads_symtoken_from_the_symbol_engine():
    """master_contract_status_db's exchange-stats query must use
    database.symbol's engine -- the status table itself lives in the main
    DB, but symtoken may not."""
    import inspect

    import database.master_contract_status_db as status_db

    source = inspect.getsource(status_db.get_exchange_stats_from_db)
    assert "from database.symbol import engine" in source, (
        "get_exchange_stats_from_db must query symtoken on database.symbol's "
        "engine; using this module's own engine returns an empty/missing "
        "table whenever SYMBOL_DATABASE_URL points elsewhere."
    )
