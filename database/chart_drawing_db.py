# database/chart_drawing_db.py
"""
Manually-placed chart drawings (trendlines, horizontal rays) for the
Charts page (pages/Charts.tsx). Persisted per-user, per-symbol, per-
exchange, per-interval, so a drawing reappears next time that exact
symbol/interval is opened.

Follows the exact module structure of database/chart_watchlist_db.py /
database/custom_indicator_db.py: its own engine/session/Base, NullPool for
SQLite, user identity as the username string (see database/user_db.py's
own comment -- username/email are the only identity columns every other
table in this app keys on).
"""

import json
import os
from typing import Any

from sqlalchemy import Column, DateTime, Index, Integer, String, Text
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


class ChartDrawing(Base):
    __tablename__ = "chart_drawings"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    symbol = Column(String(50), nullable=False)
    exchange = Column(String(20), nullable=False)
    interval = Column(String(10), nullable=False)
    # 'trendline' | 'horizontal_ray' | 'rectangle' | 'fibonacci'
    drawing_type = Column(String(20), nullable=False)
    # JSON-encoded points (+ color) -- validated shape (checked by the
    # blueprint before this is ever called), not arbitrary/executable data
    # like custom_indicator_db.py's formula_json, just numbers and a color
    # string.
    data_json = Column(Text, nullable=False)
    color = Column(String(20), default="#3b82f6")
    created_at = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("idx_chart_drawing_lookup", "user_id", "symbol", "exchange", "interval"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.drawing_type,
            **json.loads(self.data_json),
            "color": self.color,
        }


def init_db():
    """Initialize database tables."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Chart Drawing DB", logger)


def create_drawing(
    user_id: str,
    symbol: str,
    exchange: str,
    interval: str,
    drawing_type: str,
    data: dict[str, Any],
    color: str,
) -> dict[str, Any] | None:
    """Save a new drawing. `data` is the type-specific point payload
    (e.g. {"pointA": {...}, "pointB": {...}} for a trendline)."""
    try:
        drawing = ChartDrawing(
            user_id=user_id,
            symbol=symbol,
            exchange=exchange,
            interval=interval,
            drawing_type=drawing_type,
            data_json=json.dumps(data),
            color=color,
        )
        db_session.add(drawing)
        db_session.commit()
        logger.info(
            f"Chart drawing created: id={drawing.id}, user={user_id}, "
            f"{symbol}:{exchange}:{interval}, type={drawing_type}"
        )
        return drawing.to_dict()
    except Exception as e:
        logger.exception(f"Error creating chart drawing: {e}")
        db_session.rollback()
        return None


def get_drawings(user_id: str, symbol: str, exchange: str, interval: str) -> list[dict[str, Any]]:
    """Get all drawings for a user on one symbol/exchange/interval."""
    try:
        drawings = (
            ChartDrawing.query.filter_by(
                user_id=user_id, symbol=symbol, exchange=exchange, interval=interval
            )
            .order_by(ChartDrawing.created_at.asc())
            .all()
        )
        return [d.to_dict() for d in drawings]
    except Exception as e:
        logger.exception(f"Error getting chart drawings: {e}")
        return []


def delete_drawing(user_id: str, drawing_id: int) -> bool:
    """Delete a drawing, ownership-checked."""
    try:
        drawing = ChartDrawing.query.filter_by(id=drawing_id, user_id=user_id).first()
        if not drawing:
            return False
        db_session.delete(drawing)
        db_session.commit()
        logger.info(f"Chart drawing deleted: id={drawing_id}, user={user_id}")
        return True
    except Exception as e:
        logger.exception(f"Error deleting chart drawing: {e}")
        db_session.rollback()
        return False
