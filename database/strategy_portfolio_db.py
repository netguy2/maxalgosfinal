"""Persistent store for Strategy Builder portfolios.

Scoped per user (user_id column, username string -- see database/flow_db.py's
FlowWorkflow for the exact same ownership-retrofit pattern this follows: NULL
user_id on existing rows is treated as legacy/unowned and remains readable by
any authenticated user, but every row created from here on is owned by its
creator). Two watchlists are supported: `mytrades` (live or intended-live
trades) and `simulation` (paper scenarios). The legs array is serialised as
JSON; restoring is cheap and re-validation happens in the builder UI.
"""

import json
import os
from datetime import datetime
from typing import Any

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_db_engine(DATABASE_URL)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


WATCHLISTS = ("mytrades", "simulation")


class StrategyPortfolio(Base):
    __tablename__ = "strategy_portfolio"
    id = Column(Integer, primary_key=True)
    # Owning username. Nullable for pre-migration rows (see
    # _migrate_add_user_id_column) -- those are treated as legacy/unowned
    # and remain visible to any authenticated user, matching
    # database/flow_db.py's FlowWorkflow.user_id convention exactly.
    user_id = Column(String(255), nullable=True, index=True)
    # 'mytrades' or 'simulation' — enforced at the service layer.
    watchlist = Column(String(20), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    underlying = Column(String(40), nullable=False)
    exchange = Column(String(20), nullable=False)
    expiry = Column(String(20), nullable=True)
    # JSON-encoded list[dict]; each entry follows the frontend StrategyLeg shape.
    legs_json = Column(Text, nullable=False, default="[]")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


def init_db():
    """Create the strategy_portfolio table if missing."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Strategy Portfolio DB", logger)
    _migrate_add_user_id_column()


def _migrate_add_user_id_column():
    """Add user_id column to strategy_portfolio table if it doesn't exist.

    Existing rows get NULL user_id (treated as legacy/unowned by every
    query below), so this migration never breaks or hides pre-existing
    saved strategies -- it only enables per-user isolation for entries
    created from here on. Mirrors database/flow_db.py's
    _migrate_add_user_id_column exactly.
    """
    try:
        from sqlalchemy import inspect, text

        inspector = inspect(engine)
        if "strategy_portfolio" not in inspector.get_table_names():
            return

        columns = [col["name"] for col in inspector.get_columns("strategy_portfolio")]
        if "user_id" not in columns:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE strategy_portfolio ADD COLUMN user_id VARCHAR(255)"))
                conn.commit()
                logger.info("Migration: Added 'user_id' column to strategy_portfolio table")
    except Exception as e:
        logger.debug(f"Migration check for user_id column: {e}")


def ensure_strategy_portfolio_tables_exists():
    """Alias to match the app.py init pattern."""
    init_db()


def _serialize(row: StrategyPortfolio) -> dict[str, Any]:
    try:
        legs = json.loads(row.legs_json) if row.legs_json else []
    except json.JSONDecodeError:
        legs = []
    return {
        "id": row.id,
        "watchlist": row.watchlist,
        "name": row.name,
        "underlying": row.underlying,
        "exchange": row.exchange,
        "expiry": row.expiry,
        "legs": legs,
        "notes": row.notes,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _owned_by(user_id: str):
    """Filter clause: rows owned by user_id, or legacy rows with no owner
    (pre-migration data) -- matches database/flow_db.py's user_owns_workflow
    convention. Every read/write function below applies this so one user
    can't see or mutate another user's saved strategies."""
    return (StrategyPortfolio.user_id == user_id) | (StrategyPortfolio.user_id.is_(None))


def list_portfolio(user_id: str, watchlist: str | None = None) -> list[dict[str, Any]]:
    """Return the given user's saved strategies (plus legacy unowned rows),
    optionally filtered by watchlist."""
    try:
        query = StrategyPortfolio.query.filter(_owned_by(user_id))
        if watchlist:
            query = query.filter_by(watchlist=watchlist)
        rows = query.order_by(StrategyPortfolio.updated_at.desc()).all()
        return [_serialize(r) for r in rows]
    except Exception as e:
        logger.exception(f"[StrategyPortfolio] list_portfolio failed: {e}")
        return []


def get_portfolio_entry(entry_id: int, user_id: str) -> dict[str, Any] | None:
    """Return the entry only if it's owned by user_id or is a legacy
    unowned row -- returns None (not found) for another user's entry,
    same as if the id didn't exist."""
    try:
        row = StrategyPortfolio.query.filter(
            StrategyPortfolio.id == entry_id, _owned_by(user_id)
        ).first()
        return _serialize(row) if row else None
    except Exception as e:
        logger.exception(f"[StrategyPortfolio] get_portfolio_entry failed: {e}")
        return None


def save_portfolio_entry(
    *,
    user_id: str,
    name: str,
    watchlist: str,
    underlying: str,
    exchange: str,
    expiry: str | None,
    legs: list[dict[str, Any]],
    notes: str | None = None,
    entry_id: int | None = None,
) -> dict[str, Any] | None:
    """Create or update a portfolio entry.

    On update, entry_id must be owned by user_id (or be a legacy unowned
    row) -- otherwise this returns None, same as "not found", rather than
    silently overwriting another user's entry. A legacy unowned row gets
    claimed by user_id on update (stops being ownerless once touched).

    Returns the serialised row on success, None on failure.
    """
    if watchlist not in WATCHLISTS:
        logger.warning(f"[StrategyPortfolio] invalid watchlist: {watchlist}")
        return None

    try:
        legs_json = json.dumps(legs, default=str)
        if entry_id is not None:
            row = StrategyPortfolio.query.filter(
                StrategyPortfolio.id == entry_id, _owned_by(user_id)
            ).first()
            if not row:
                return None
            row.user_id = user_id
            row.name = name
            row.watchlist = watchlist
            row.underlying = underlying
            row.exchange = exchange
            row.expiry = expiry
            row.legs_json = legs_json
            row.notes = notes
        else:
            row = StrategyPortfolio(
                user_id=user_id,
                name=name,
                watchlist=watchlist,
                underlying=underlying,
                exchange=exchange,
                expiry=expiry,
                legs_json=legs_json,
                notes=notes,
            )
            db_session.add(row)
        db_session.commit()
        return _serialize(row)
    except Exception as e:
        logger.exception(f"[StrategyPortfolio] save_portfolio_entry failed: {e}")
        db_session.rollback()
        return None


def delete_portfolio_entry(entry_id: int, user_id: str) -> bool:
    """Delete the entry only if it's owned by user_id or a legacy unowned
    row -- returns False (not found) for another user's entry."""
    try:
        row = StrategyPortfolio.query.filter(
            StrategyPortfolio.id == entry_id, _owned_by(user_id)
        ).first()
        if not row:
            return False
        db_session.delete(row)
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"[StrategyPortfolio] delete_portfolio_entry failed: {e}")
        db_session.rollback()
        return False
