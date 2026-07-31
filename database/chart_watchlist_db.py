# database/chart_watchlist_db.py
"""
Named, multiple watchlists for the Charts page (pages/Charts.tsx).

Deliberately separate from Historify's existing single flat watchlist
(database/historify_db.py's `watchlist` table, used by the /historify
page) rather than retrofitting that table with a list_name column --
historify_db.py has no schema-migration framework (CREATE TABLE IF NOT
EXISTS only) and that table is shared with a page this feature doesn't
otherwise touch. This is a pure addition: a new table, a new blueprint,
zero risk to the existing single-list watchlist or the /historify page.

Follows the exact module structure of database/action_center_db.py /
database/custom_indicator_db.py: its own engine/session/Base, NullPool for
SQLite, user identity as the username string (see database/user_db.py's
own comment -- username/email are the only identity columns every other
table in this app keys on).
"""

import os
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.sql import func

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_db_engine(DATABASE_URL)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class ChartWatchlist(Base):
    __tablename__ = "chart_watchlists"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (Index("idx_chart_watchlist_user", "user_id"),)

    def to_dict(self, items: list["ChartWatchlistItem"] | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "items": [i.to_dict() for i in items] if items is not None else [],
        }


class ChartWatchlistItem(Base):
    __tablename__ = "chart_watchlist_items"

    id = Column(Integer, primary_key=True)
    watchlist_id = Column(Integer, ForeignKey("chart_watchlists.id"), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(20), nullable=False)
    added_at = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("idx_chart_watchlist_item_list", "watchlist_id"),
        UniqueConstraint("watchlist_id", "symbol", "exchange", name="uq_watchlist_symbol_exchange"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "added_at": self.added_at.isoformat() if self.added_at else None,
        }


def init_db():
    """Initialize database tables."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Chart Watchlist DB", logger)


def create_watchlist(user_id: str, name: str) -> dict[str, Any] | None:
    """Create a new named watchlist for a user."""
    try:
        watchlist = ChartWatchlist(user_id=user_id, name=name)
        db_session.add(watchlist)
        db_session.commit()
        logger.info(f"Chart watchlist created: id={watchlist.id}, user={user_id}, name={name}")
        return watchlist.to_dict(items=[])
    except Exception as e:
        logger.exception(f"Error creating chart watchlist: {e}")
        db_session.rollback()
        return None


def get_watchlists(user_id: str) -> list[dict[str, Any]]:
    """Get all of a user's named watchlists, each with its items."""
    try:
        watchlists = (
            ChartWatchlist.query.filter_by(user_id=user_id)
            .order_by(ChartWatchlist.created_at.asc())
            .all()
        )
        result = []
        for wl in watchlists:
            items = (
                ChartWatchlistItem.query.filter_by(watchlist_id=wl.id)
                .order_by(ChartWatchlistItem.added_at.desc())
                .all()
            )
            result.append(wl.to_dict(items=items))
        return result
    except Exception as e:
        logger.exception(f"Error getting chart watchlists: {e}")
        return []


def delete_watchlist(user_id: str, watchlist_id: int) -> bool:
    """Delete a watchlist and its items, ownership-checked."""
    try:
        watchlist = ChartWatchlist.query.filter_by(id=watchlist_id, user_id=user_id).first()
        if not watchlist:
            return False
        ChartWatchlistItem.query.filter_by(watchlist_id=watchlist_id).delete()
        db_session.delete(watchlist)
        db_session.commit()
        logger.info(f"Chart watchlist deleted: id={watchlist_id}, user={user_id}")
        return True
    except Exception as e:
        logger.exception(f"Error deleting chart watchlist: {e}")
        db_session.rollback()
        return False


def add_symbol_to_watchlist(
    user_id: str, watchlist_id: int, symbol: str, exchange: str
) -> dict[str, Any] | None:
    """Add a symbol to a watchlist, ownership-checked against the watchlist itself."""
    try:
        watchlist = ChartWatchlist.query.filter_by(id=watchlist_id, user_id=user_id).first()
        if not watchlist:
            return None
        existing = ChartWatchlistItem.query.filter_by(
            watchlist_id=watchlist_id, symbol=symbol, exchange=exchange
        ).first()
        if existing:
            return existing.to_dict()
        item = ChartWatchlistItem(watchlist_id=watchlist_id, symbol=symbol, exchange=exchange)
        db_session.add(item)
        db_session.commit()
        logger.info(
            f"Symbol added to chart watchlist: watchlist={watchlist_id}, symbol={symbol}:{exchange}"
        )
        return item.to_dict()
    except Exception as e:
        logger.exception(f"Error adding symbol to chart watchlist: {e}")
        db_session.rollback()
        return None


def remove_symbol_from_watchlist(
    user_id: str, watchlist_id: int, symbol: str, exchange: str
) -> bool:
    """Remove a symbol from a watchlist, ownership-checked."""
    try:
        watchlist = ChartWatchlist.query.filter_by(id=watchlist_id, user_id=user_id).first()
        if not watchlist:
            return False
        item = ChartWatchlistItem.query.filter_by(
            watchlist_id=watchlist_id, symbol=symbol, exchange=exchange
        ).first()
        if not item:
            return False
        db_session.delete(item)
        db_session.commit()
        return True
    except Exception as e:
        logger.exception(f"Error removing symbol from chart watchlist: {e}")
        db_session.rollback()
        return False
