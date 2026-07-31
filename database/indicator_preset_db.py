# database/indicator_preset_db.py
"""
Saved indicator selections ("setups") for the Charts page
(pages/Charts.tsx). A preset is scoped either to one symbol/exchange
(auto-loads only when that exact symbol is opened) or globally -- NULL
symbol/exchange, applied as the default for any symbol without its own
saved setup.

Follows the exact module structure of database/chart_drawing_db.py: its
own engine/session/Base, NullPool for SQLite, user identity as the
username string (see database/user_db.py's own comment -- username/email
are the only identity columns every other table in this app keys on).
"""

import json
import os
from typing import Any

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
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


class IndicatorPreset(Base):
    __tablename__ = "indicator_presets"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    # NULL symbol/exchange = the user's global default; a real
    # symbol/exchange = that symbol's own saved setup, which takes
    # priority over the global default when both exist.
    symbol = Column(String(50), nullable=True)
    exchange = Column(String(20), nullable=True)
    # JSON: {"indicators": ["EMA", "RSI", ...], "customIndicatorIds": [1, 2]}
    config_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("idx_indicator_preset_lookup", "user_id", "symbol", "exchange"),
        UniqueConstraint("user_id", "symbol", "exchange", name="uq_indicator_preset_scope"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "exchange": self.exchange,
            **json.loads(self.config_json),
        }


def init_db():
    """Initialize database tables."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Indicator Preset DB", logger)


def save_preset(
    user_id: str,
    symbol: str | None,
    exchange: str | None,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Upsert the preset for this scope (symbol+exchange, or both NULL for global)."""
    try:
        preset = IndicatorPreset.query.filter_by(
            user_id=user_id, symbol=symbol, exchange=exchange
        ).first()
        if preset:
            preset.config_json = json.dumps(config)
        else:
            preset = IndicatorPreset(
                user_id=user_id,
                symbol=symbol,
                exchange=exchange,
                config_json=json.dumps(config),
            )
            db_session.add(preset)
        db_session.commit()
        logger.info(
            f"Indicator preset saved: user={user_id}, scope={symbol}:{exchange or 'global'}"
        )
        return preset.to_dict()
    except Exception as e:
        logger.exception(f"Error saving indicator preset: {e}")
        db_session.rollback()
        return None


def get_preset(user_id: str, symbol: str | None, exchange: str | None) -> dict[str, Any] | None:
    """Exact-scope lookup (pass symbol=None, exchange=None for the global preset)."""
    try:
        preset = IndicatorPreset.query.filter_by(
            user_id=user_id, symbol=symbol, exchange=exchange
        ).first()
        return preset.to_dict() if preset else None
    except Exception as e:
        logger.exception(f"Error getting indicator preset: {e}")
        return None


def delete_preset(user_id: str, symbol: str | None, exchange: str | None) -> bool:
    """Delete a preset, ownership-checked against the session user."""
    try:
        preset = IndicatorPreset.query.filter_by(
            user_id=user_id, symbol=symbol, exchange=exchange
        ).first()
        if not preset:
            return False
        db_session.delete(preset)
        db_session.commit()
        logger.info(f"Indicator preset deleted: user={user_id}, scope={symbol}:{exchange or 'global'}")
        return True
    except Exception as e:
        logger.exception(f"Error deleting indicator preset: {e}")
        db_session.rollback()
        return False
