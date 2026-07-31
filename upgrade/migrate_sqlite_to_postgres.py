#!/usr/bin/env python3
"""
Max Algos SQLite -> PostgreSQL Data Migration (operator-controlled, DESTRUCTIVE-ish)
=====================================================================================

Copies every row from the SQLite databases this install has been using into a
PostgreSQL database, so an existing install with real users/orders/history can
be cut over to Postgres without losing data. This is NOT registered in
upgrade/migrate_all.py -- like rotate_pepper.py, it must be run explicitly by
the operator at a controlled moment, because it is a one-time, environment-
specific operation, not a routine idempotent schema migration.

WHAT THIS DOES:
  1. For each of the 5 SQLite-backed databases (main, latency, logs, health,
     sandbox), connects to the existing SQLite file (source) and the target
     PostgreSQL URL (destination, read from the *_DATABASE_URL env vars --
     point these at Postgres in the environment BEFORE running this script,
     see "Usage" below).
  2. Creates the schema on the Postgres side using the SAME SQLAlchemy models
     already defined in each database/*.py module (via Base.metadata.create_all),
     so there is zero risk of schema drift between this script and the app.
  3. Copies every row, table by table, in an order that respects foreign-key
     dependencies (via SQLAlchemy's own topological sort of the combined
     metadata for that database -- not a hand-maintained table-order list).
  4. Reports per-table row counts copied, and a final verification pass that
     compares SQLite source count vs Postgres destination count per table.

WHAT THIS DOES NOT DO:
  - It does not touch db/historify.duckdb (DuckDB is not part of the SQLite/
    Postgres switch -- see CLAUDE.md).
  - It does not modify .env. You control the cutover moment by only pointing
    *_DATABASE_URL at Postgres in .env AFTER this script confirms a clean copy
    (see "Usage" below) -- run this script first with a Postgres URL passed
    explicitly via --pg-url / the individual --*-pg-url flags, verify, THEN
    edit .env, THEN restart the app.
  - It is NOT re-run-safe against a non-empty Postgres target: by default it
    refuses to run if a destination table already has rows, to avoid silently
    duplicating data on a second run. Pass --truncate-first to explicitly wipe
    each destination table before copying (only ever do this if you are
    intentionally re-running after fixing a problem with a previous attempt).

WHY IT'S KEPT OUT OF migrate_all.py:
  This script requires a Postgres server to already exist and be reachable,
  and its correct behavior depends on operator judgment about timing (stop
  writes to SQLite before copying, verify counts before cutting .env over).
  Auto-running it on every `migrate_all.py` invocation would silently attempt
  a Postgres connection (and likely fail loudly) on every plain SQLite install
  that has never touched Postgres.

USAGE:
    Run from the PROJECT ROOT (not from inside upgrade/) -- unlike most other
    upgrade/*.py scripts, this one imports 26+ database/*.py modules to get
    at their SQLAlchemy metadata, and several of those modules read a
    relative sqlite:///db/whatever.db default straight from os.getenv() at
    import time without resolving it against the project root. Running from
    upgrade/ would make those modules create a stray upgrade/db/ directory
    instead of touching the real db/ directory.

    # Dry run: shows what WOULD be copied (table names + source row counts),
    # makes no connection to Postgres, no writes anywhere.
    uv run upgrade/migrate_sqlite_to_postgres.py --dry-run

    # Real run: source SQLite paths come from the CURRENT *_DATABASE_URL env
    # vars (which should still say sqlite:/// at this point -- don't edit
    # .env yet). Destination Postgres URLs are passed explicitly so this
    # script never accidentally reads a half-migrated .env:
    uv run upgrade/migrate_sqlite_to_postgres.py \\
        --pg-url "postgresql://maxalgos:PASSWORD@localhost:5432/maxalgos"

    # Use a different Postgres database per source DB instead of one shared
    # database (only needed if you want genuine per-database isolation on
    # the Postgres side too):
    uv run upgrade/migrate_sqlite_to_postgres.py \\
        --main-pg-url "postgresql://maxalgos:PW@localhost:5432/maxalgos" \\
        --latency-pg-url "postgresql://maxalgos:PW@localhost:5432/maxalgos_latency" \\
        --logs-pg-url "postgresql://maxalgos:PW@localhost:5432/maxalgos_logs" \\
        --health-pg-url "postgresql://maxalgos:PW@localhost:5432/maxalgos_health" \\
        --sandbox-pg-url "postgresql://maxalgos:PW@localhost:5432/maxalgos_sandbox"

    # After a clean run (all counts match), THEN edit .env to point
    # *_DATABASE_URL at the same Postgres URL(s) you migrated to, and restart
    # the app. The app's own init_*_db() calls will find the tables already
    # populated and skip creation (idempotent create_all).

PRE-FLIGHT (do this before running):
  1. Stop the running Max Algos process (or at minimum stop all traffic to
     it) -- this script reads a point-in-time snapshot of each SQLite file.
     Any writes to SQLite during/after the copy will NOT be reflected in
     Postgres.
  2. Back up the db/ directory: `cp -r db/ db.bak.$(date +%Y%m%d)/`
  3. Confirm the target Postgres database/user already exist (see
     upgrade/../CLAUDE.md-referenced server runbook) and that the
     *_DATABASE_URL env vars you pass via --pg-url are actually reachable
     from this machine.

POST-FLIGHT:
  1. Review the verification output (source vs destination row counts per
     table) -- every table must match exactly.
  2. Only then edit .env to point *_DATABASE_URL at Postgres.
  3. Restart Max Algos and confirm /admin diagnostics DB read check passes.
  4. Keep the db.bak.<date>/ backup until you've confirmed the app works
     correctly against Postgres for at least a few days.

Migration: N/A (operator-triggered, not part of the numbered migrate_all.py sequence)
Created: 2026-07-23
"""

import argparse
import importlib
import os
import sys
import time
from pathlib import Path

# Add parent directory to path for imports
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from sqlalchemy import MetaData, create_engine, inspect
from sqlalchemy.orm import sessionmaker

from utils.logging import get_logger

logger = get_logger(__name__)


# Every module that defaults to (or can be pointed at) each of the 5
# SQLite-backed *_DATABASE_URL groups. Each module declares its own
# `Base = declarative_base()` (26 separate registries share the "main" DB
# file even though they're one physical sqlite file) -- we import all of
# them so the combined metadata covers every table that actually exists.
DB_GROUPS = {
    "main": {
        "env_var": "DATABASE_URL",
        "default_sqlite": "sqlite:///db/maxalgos.db",
        "modules": [
            "database.auth_db",
            "database.user_db",
            "database.action_center_db",
            "database.ai_settings_db",
            "database.analyzer_db",
            "database.apilog_db",
            "database.chart_drawing_db",
            "database.chart_prefs_db",
            "database.chart_watchlist_db",
            "database.chartink_db",
            "database.custom_indicator_db",
            "database.flow_db",
            "database.indicator_preset_db",
            "database.instrument_registry",
            "database.leverage_db",
            "database.market_calendar_db",
            "database.master_contract_status_db",
            "database.oauth_db",
            "database.payment_db",
            "database.qty_freeze_db",
            "database.settings_db",
            "database.strategy_db",
            "database.strategy_portfolio_db",
            "database.symbol",
            "database.telegram_db",
            "database.whatsapp_db",
        ],
    },
    "latency": {
        "env_var": "LATENCY_DATABASE_URL",
        "default_sqlite": "sqlite:///db/latency.db",
        "modules": ["database.latency_db"],
    },
    "logs": {
        "env_var": "LOGS_DATABASE_URL",
        "default_sqlite": "sqlite:///db/logs.db",
        "modules": ["database.traffic_db"],
    },
    "health": {
        "env_var": "HEALTH_DATABASE_URL",
        "default_sqlite": "sqlite:///db/health.db",
        "modules": ["database.health_db"],
    },
    "sandbox": {
        "env_var": "SANDBOX_DATABASE_URL",
        "default_sqlite": "sqlite:///db/sandbox.db",
        "modules": ["database.sandbox_db"],
    },
}


def collect_metadata(module_names: list[str]) -> MetaData:
    """Import each module and merge every distinct Base.metadata found into
    one combined MetaData, so sorted_tables reflects FK dependencies across
    ALL tables in this database group, not just one module's subset."""
    combined = MetaData()
    seen_base_ids = set()
    for name in module_names:
        mod = importlib.import_module(name)
        base = getattr(mod, "Base", None) or getattr(mod, "HealthBase", None) \
            or getattr(mod, "LatencyBase", None) or getattr(mod, "LogBase", None)
        if base is None:
            logger.warning(f"module={name} -> no Base/HealthBase/LatencyBase/LogBase found, skipping")
            continue
        if id(base.metadata) in seen_base_ids:
            continue
        seen_base_ids.add(id(base.metadata))
        for table in base.metadata.tables.values():
            if table.name not in combined.tables:
                table.to_metadata(combined)
    return combined


def get_sqlite_source_url(group: dict) -> str:
    """Read the CURRENT env var -- expected to still be sqlite:/// at
    migration time. Refuses to proceed if it's already been pointed at
    Postgres (that would mean .env was edited before this script ran, which
    is the wrong order -- see module docstring).

    Relative sqlite:/// paths are resolved against PROJECT_ROOT, not the
    process's current working directory -- this script is documented to be
    run via `cd upgrade && uv run migrate_sqlite_to_postgres.py`, and a
    relative path resolved against cwd would silently point at a
    (nonexistent or stray) upgrade/db/ directory instead of the real
    project-root db/ directory. Mirrors the same fix already applied in
    upgrade/migrate_sandbox.py's get_sandbox_db_engine().
    """
    url = os.getenv(group["env_var"], group["default_sqlite"])
    if "sqlite" not in url:
        raise RuntimeError(
            f"{group['env_var']} is already set to a non-SQLite URL ({url}). "
            "This script expects to read the ORIGINAL SQLite data before you "
            "edit .env -- restore the sqlite:// URL in .env, or pass the "
            "correct source explicitly, before running this migration."
        )
    if url.startswith("sqlite:///"):
        db_path = url.replace("sqlite:///", "")
        if db_path != ":memory:" and not os.path.isabs(db_path):
            db_path = os.path.join(PROJECT_ROOT, db_path)
            url = f"sqlite:///{db_path}"
    return url


def copy_table(
    table,
    source_engine,
    dest_engine,
    truncate_first: bool,
    dry_run: bool,
    source_tables: set,
) -> tuple[int, int]:
    """Copy all rows of one table from source_engine to dest_engine.
    Returns (source_row_count, rows_copied).

    A table absent from the SQLite source (a feature added after this
    install's DB was created, and never exercised, so create_all() on the
    live app never ran for it) is a legitimate 0-row case, not an error --
    schema is still created on Postgres via metadata.create_all() so the
    table exists there, just empty.
    """
    if table.name not in source_tables:
        # Note: log phrasing here deliberately avoids "<table_name>: <value>"
        # -- utils.logging.SensitiveDataFilter redacts anything matching
        # `token|key|secret|password|auth ... [:=] ... value` to keep
        # credentials out of logs, and several real table names in this
        # schema (symtoken, api_keys, auth, ...) end in or contain those
        # words, so a naive "table_name: count" format gets falsely redacted.
        logger.info(f"  table={table.name} -> not present in source SQLite DB (0 rows)")
        return 0, 0

    with source_engine.connect() as src_conn:
        rows = src_conn.execute(table.select()).mappings().all()

    if dry_run:
        return len(rows), 0

    with dest_engine.begin() as dest_conn:
        if truncate_first:
            dest_conn.execute(table.delete())

        existing = dest_conn.execute(table.select()).first()
        if existing is not None and not truncate_first:
            raise RuntimeError(
                f"Destination table '{table.name}' already has rows. Refusing to "
                "copy into a non-empty table (would create duplicates). Pass "
                "--truncate-first if you intentionally want to wipe and redo "
                "this table."
            )

        if rows:
            # Batch insert in chunks to avoid one giant statement on large tables.
            CHUNK = 1000
            for i in range(0, len(rows), CHUNK):
                chunk = rows[i : i + CHUNK]
                dest_conn.execute(table.insert(), [dict(r) for r in chunk])

    return len(rows), len(rows)


def migrate_group(
    group_name: str,
    group: dict,
    pg_url: str,
    truncate_first: bool,
    dry_run: bool,
) -> dict:
    """Migrate one database group (main/latency/logs/health/sandbox).
    Returns a dict of {table_name: (source_count, dest_count)} for the
    final verification report."""
    logger.info(f"=== {group_name} ===")

    sqlite_url = get_sqlite_source_url(group)
    logger.info(f"Source (SQLite): {sqlite_url}")
    if not dry_run:
        logger.info(f"Destination (Postgres): {pg_url}")

    metadata = collect_metadata(group["modules"])
    tables = metadata.sorted_tables  # FK-dependency-respecting order
    logger.info(f"Tables in this group: {[t.name for t in tables]}")

    source_engine = create_engine(sqlite_url)
    source_tables = set(inspect(source_engine).get_table_names())

    if dry_run:
        report = {}
        for table in tables:
            if table.name not in source_tables:
                report[table.name] = (0, None)
                logger.info(f"  [DRY RUN] table={table.name} -> not present in source (0 rows)")
                continue
            with source_engine.connect() as conn:
                count = len(conn.execute(table.select()).mappings().all())
            report[table.name] = (count, None)
            logger.info(f"  [DRY RUN] table={table.name} -> {count} row(s) would be copied")
        source_engine.dispose()
        return report

    dest_engine = create_engine(pg_url)

    # Create schema on Postgres using the exact same models the app uses --
    # no separate DDL, no drift risk.
    metadata.create_all(bind=dest_engine)
    logger.info(f"Schema created/verified on Postgres for {group_name}")

    report = {}
    for table in tables:
        src_count, copied = copy_table(
            table, source_engine, dest_engine, truncate_first, dry_run, source_tables
        )
        logger.info(f"  table={table.name} -> {src_count} row(s) in source, {copied} copied")
        report[table.name] = (src_count, copied)

    # Verification pass: re-count on the Postgres side independently of what
    # copy_table reported, to catch any silent partial-commit issue.
    inspector = inspect(dest_engine)
    dest_tables = set(inspector.get_table_names())
    for table in tables:
        if table.name not in dest_tables:
            report[table.name] = (report[table.name][0], -1)
            continue
        with dest_engine.connect() as conn:
            dest_count = conn.execute(table.select()).rowcount
            dest_count = len(conn.execute(table.select()).mappings().all())
        src_count = report[table.name][0]
        report[table.name] = (src_count, dest_count)

    source_engine.dispose()
    dest_engine.dispose()
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Max Algos SQLite databases to PostgreSQL (operator-run, one-time).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be copied (table names + source row counts). No Postgres connection made.",
    )
    parser.add_argument(
        "--pg-url",
        help="Single Postgres URL used for all 5 database groups (simplest option, shares one database).",
    )
    parser.add_argument("--main-pg-url", help="Postgres URL for the main database (overrides --pg-url).")
    parser.add_argument("--latency-pg-url", help="Postgres URL for the latency database (overrides --pg-url).")
    parser.add_argument("--logs-pg-url", help="Postgres URL for the logs database (overrides --pg-url).")
    parser.add_argument("--health-pg-url", help="Postgres URL for the health database (overrides --pg-url).")
    parser.add_argument("--sandbox-pg-url", help="Postgres URL for the sandbox database (overrides --pg-url).")
    parser.add_argument(
        "--truncate-first",
        action="store_true",
        help="Wipe each destination table before copying. Only use when intentionally re-running "
        "after fixing a problem with a previous attempt -- default behavior refuses to copy "
        "into a non-empty destination table to avoid silent duplication.",
    )
    parser.add_argument(
        "--only",
        choices=list(DB_GROUPS.keys()),
        action="append",
        help="Limit to specific database group(s) (repeatable). Default: all 5.",
    )
    args = parser.parse_args()

    groups_to_run = args.only or list(DB_GROUPS.keys())

    if not args.dry_run:
        pg_urls = {
            "main": args.main_pg_url or args.pg_url,
            "latency": args.latency_pg_url or args.pg_url,
            "logs": args.logs_pg_url or args.pg_url,
            "health": args.health_pg_url or args.pg_url,
            "sandbox": args.sandbox_pg_url or args.pg_url,
        }
        missing = [g for g in groups_to_run if not pg_urls[g]]
        if missing:
            parser.error(
                f"No Postgres URL provided for group(s): {missing}. "
                "Pass --pg-url for a shared database, or --<group>-pg-url per group."
            )

    logger.info("=" * 70)
    logger.info("Max Algos SQLite -> PostgreSQL Data Migration")
    logger.info("DRY RUN" if args.dry_run else "LIVE RUN")
    logger.info("=" * 70)

    start = time.time()
    all_reports = {}
    failures = []

    for group_name in groups_to_run:
        group = DB_GROUPS[group_name]
        try:
            pg_url = None if args.dry_run else pg_urls[group_name]
            report = migrate_group(group_name, group, pg_url, args.truncate_first, args.dry_run)
            all_reports[group_name] = report
        except Exception as e:
            logger.exception(f"FAILED migrating group '{group_name}': {e}")
            failures.append(group_name)

    elapsed = time.time() - start
    logger.info("=" * 70)
    logger.info(f"Completed in {elapsed:.1f}s")

    if not args.dry_run:
        logger.info("Verification (source row count -> destination row count):")
        mismatches = []
        for group_name, report in all_reports.items():
            for table_name, (src, dest) in report.items():
                status = "OK" if src == dest else "MISMATCH"
                if src != dest:
                    mismatches.append((group_name, table_name, src, dest))
                logger.info(f"  [{group_name}] table={table_name} -> {src} -> {dest}  [{status}]")

        if mismatches:
            logger.error(f"{len(mismatches)} table(s) have row count mismatches -- DO NOT cut .env over yet:")
            for group_name, table_name, src, dest in mismatches:
                logger.error(f"  [{group_name}] table={table_name} -> expected {src}, got {dest}")
            sys.exit(1)
        else:
            logger.info("All tables verified -- row counts match. Safe to update .env and restart.")

    if failures:
        logger.error(f"Migration FAILED for group(s): {failures}")
        sys.exit(1)


if __name__ == "__main__":
    main()
