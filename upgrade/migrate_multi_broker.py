#!/usr/bin/env python3
"""
Migration script for multi-broker support.

Two changes, both additive/backward-compatible:

1. Creates the new `auth_broker_sessions` table (AuthBrokerSession model in
   database/auth_db.py) if it doesn't exist yet. This table is entirely new
   - it never existed before, so this is a plain CREATE TABLE, no data to
   migrate. The Auth table itself is completely untouched by this migration.

2. Adds a `broker_name` column to the existing `user_broker_credentials`
   table (previously one row per username; now one row per
   (username, broker_name)). Existing rows are backfilled by inferring
   their broker from `redirect_url` (e.g. ".../zebu/callback" -> "zebu"),
   using the same logic as blueprints/broker_credentials.py's
   get_broker_from_redirect_url(). Rows that can't be inferred (no
   redirect_url, or a redirect_url that doesn't end in /<broker>/callback)
   are left as broker_name='unknown' rather than dropped, so no credential
   data is ever lost - the user can re-save them under the correct broker
   from the new Broker Management page if needed.

Usage:
    cd upgrade
    python migrate_multi_broker.py
"""

import os
import re
import sys

# Add parent directory to path to import modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text

# Load environment from parent directory
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
load_dotenv(env_path)

from utils.logging import get_logger

logger = get_logger(__name__)


def _resolve_database_url():
    database_url = os.getenv("DATABASE_URL", "sqlite:///db/maxalgos.db")
    if database_url.startswith("sqlite:///") and not database_url.startswith("sqlite:////"):
        db_path = database_url.replace("sqlite:///", "")
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_db_path = os.path.join(parent_dir, db_path)
        database_url = f"sqlite:///{full_db_path}"
        logger.info(f"Using database: {full_db_path}")
    return database_url


def _broker_from_redirect_url(redirect_url):
    if not redirect_url:
        return None
    match = re.search(r"/([^/]+)/callback$", redirect_url)
    return match.group(1).lower() if match else None


def migrate_auth_broker_sessions(engine):
    """Create the new auth_broker_sessions table if missing. Additive only
    - never touches the existing `auth` table."""
    inspector = inspect(engine)
    if "auth_broker_sessions" in inspector.get_table_names():
        logger.info("Table auth_broker_sessions already exists - skipping.")
        return True

    logger.info("Creating auth_broker_sessions table...")
    # Import here (after path setup) so the model registers on Base.metadata.
    from database.auth_db import AuthBrokerSession, Base

    Base.metadata.create_all(engine, tables=[AuthBrokerSession.__table__])
    logger.info("auth_broker_sessions table created.")
    return True


def migrate_user_broker_credentials(engine):
    """Add broker_name to user_broker_credentials, change uniqueness to
    (username, broker_name), and backfill existing rows from redirect_url."""
    inspector = inspect(engine)

    if "user_broker_credentials" not in inspector.get_table_names():
        logger.info("Table user_broker_credentials does not exist yet - nothing to migrate.")
        return True

    columns = [col["name"] for col in inspector.get_columns("user_broker_credentials")]
    if "broker_name" in columns:
        logger.info("user_broker_credentials already has broker_name - skipping.")
        return True

    logger.info("Migrating user_broker_credentials to (username, broker_name) schema...")

    with engine.connect() as conn:
        # 1. Add the new column (nullable for now, so existing rows don't
        #    fail the ALTER; we backfill immediately after, then the ORM
        #    model's nullable=False only affects NEW rows going forward -
        #    SQLite doesn't enforce NOT NULL retroactively on ALTER anyway).
        conn.execute(text("ALTER TABLE user_broker_credentials ADD COLUMN broker_name VARCHAR(20)"))
        conn.commit()

        # 2. Backfill from redirect_url.
        rows = conn.execute(
            text("SELECT id, username, redirect_url FROM user_broker_credentials")
        ).fetchall()

        for row_id, username, redirect_url in rows:
            broker = _broker_from_redirect_url(redirect_url) or "unknown"
            conn.execute(
                text("UPDATE user_broker_credentials SET broker_name = :broker WHERE id = :id"),
                {"broker": broker, "id": row_id},
            )
            logger.info(f"  Backfilled row id={row_id} username={username} -> broker_name={broker}")
        conn.commit()

        # 3. Recreate the table with the correct constraints (SQLite can't
        #    ALTER a UNIQUE constraint in place). Standard SQLite migration
        #    pattern: rename, recreate with new schema, copy, drop old.
        logger.info("Recreating table with (username, broker_name) unique constraint...")
        conn.execute(text("ALTER TABLE user_broker_credentials RENAME TO user_broker_credentials_old"))
        conn.commit()

        conn.execute(text("""
            CREATE TABLE user_broker_credentials (
                id INTEGER NOT NULL,
                username VARCHAR(80) NOT NULL,
                broker_name VARCHAR(20) NOT NULL,
                broker_api_key TEXT,
                broker_api_secret TEXT,
                broker_api_key_market TEXT,
                broker_api_secret_market TEXT,
                redirect_url TEXT,
                PRIMARY KEY (id),
                CONSTRAINT uq_user_broker_credential UNIQUE (username, broker_name)
            )
        """))
        conn.execute(text("""
            INSERT INTO user_broker_credentials
                (id, username, broker_name, broker_api_key, broker_api_secret,
                 broker_api_key_market, broker_api_secret_market, redirect_url)
            SELECT id, username, broker_name, broker_api_key, broker_api_secret,
                   broker_api_key_market, broker_api_secret_market, redirect_url
            FROM user_broker_credentials_old
        """))
        conn.execute(text("DROP TABLE user_broker_credentials_old"))
        conn.commit()

    logger.info("user_broker_credentials migration complete.")
    return True


def main():
    database_url = _resolve_database_url()
    engine = create_engine(database_url)

    ok1 = migrate_auth_broker_sessions(engine)
    ok2 = migrate_user_broker_credentials(engine)

    if ok1 and ok2:
        logger.info("Multi-broker migration completed successfully.")
        return 0
    logger.error("Multi-broker migration encountered errors - see log above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
