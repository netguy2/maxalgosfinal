# database/custom_indicator_db.py
"""
Custom Indicators — per-user, formula-builder-defined indicator overlays
for the Charts page (pages/Charts.tsx). Follows the exact module structure
of database/action_center_db.py: its own engine/session/Base rather than a
shared db.Model, NullPool for SQLite, user identity stored as the username
string (not an integer FK to users.id — see database/user_db.py's own
comment: username/email are the only identity columns every other table
in this app keys on).
"""

import json
import os
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text
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


class CustomIndicator(Base):
    __tablename__ = "custom_indicators"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False)
    name = Column(String(100), nullable=False)
    # JSON-encoded formula spec, e.g.
    # {"kind": "combine", "op": "-", "a": {"indicator": "EMA", "period": 20},
    #  "b": {"indicator": "SMA", "period": 50}}
    # or {"kind": "threshold", "a": {"indicator": "RSI", "period": 14},
    #  "threshold": 70, "invert": true}
    # Validated against a fixed whitelist server-side
    # (services/custom_indicator_service.py) before ever being stored or
    # evaluated -- never arbitrary code.
    formula_json = Column(Text, nullable=False)
    color = Column(String(20), default="#f59e0b")
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (Index("idx_custom_indicator_user", "user_id"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "formula": json.loads(self.formula_json),
            "color": self.color,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def init_db():
    """Initialize database tables."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Custom Indicator DB", logger)


def create_custom_indicator(
    user_id: str, name: str, formula: dict[str, Any], color: str = "#f59e0b"
) -> dict[str, Any] | None:
    """Save a new custom indicator for a user. Returns the created
    indicator's dict form, or None on failure."""
    try:
        indicator = CustomIndicator(
            user_id=user_id,
            name=name,
            formula_json=json.dumps(formula),
            color=color,
        )
        db_session.add(indicator)
        db_session.commit()
        logger.info(f"Custom indicator created: id={indicator.id}, user={user_id}, name={name}")
        return indicator.to_dict()
    except Exception as e:
        logger.exception(f"Error creating custom indicator: {e}")
        db_session.rollback()
        return None


def get_custom_indicators(user_id: str) -> list[dict[str, Any]]:
    """Get all custom indicators belonging to a user."""
    try:
        indicators = (
            CustomIndicator.query.filter_by(user_id=user_id)
            .order_by(CustomIndicator.created_at.desc())
            .all()
        )
        return [ind.to_dict() for ind in indicators]
    except Exception as e:
        logger.exception(f"Error getting custom indicators: {e}")
        return []


def delete_custom_indicator(user_id: str, indicator_id: int) -> bool:
    """Delete a custom indicator, scoped to the owning user (ownership
    check baked into the query, not a separate check after fetch)."""
    try:
        indicator = CustomIndicator.query.filter_by(id=indicator_id, user_id=user_id).first()
        if not indicator:
            return False
        db_session.delete(indicator)
        db_session.commit()
        logger.info(f"Custom indicator deleted: id={indicator_id}, user={user_id}")
        return True
    except Exception as e:
        logger.exception(f"Error deleting custom indicator: {e}")
        db_session.rollback()
        return False
