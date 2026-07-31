# database/ai_settings_db.py
"""
Per-user AI provider settings for the "AI Insight" advisory feature on
the Charts page (pages/Charts.tsx). Stores the user's own AI provider API
key (OpenAI/Anthropic/Gemini/OpenAI-compatible custom endpoint) and,
optionally, a news provider API key for a future fast-follow -- both
Fernet-encrypted at rest, following the exact pattern
database/telegram_db.py already uses for its own encrypted bot/API
tokens: a dedicated salt constant + PBKDF2HMAC-SHA256 (100k iterations)
over the shared PEPPER from database/auth_db.py, deriving an independent
Fernet keyspace so this feature's secrets are not decryptable with the
Telegram module's key (or vice versa).

Follows the exact module structure of database/chart_drawing_db.py /
database/indicator_preset_db.py: its own engine/session/Base, NullPool
for SQLite, user identity as the username string (see database/user_db.py's
own comment -- username/email are the only identity columns every other
table in this app keys on).
"""

import base64
import os
from datetime import datetime
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.sql import func

from database.auth_db import PEPPER
from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

AI_KEY_SALT = os.getenv("AI_KEY_SALT", "ai-maxalgos-salt").encode()


def get_encryption_key() -> Fernet:
    """Derives a Fernet key for encrypting AI/news provider API keys --
    same PBKDF2HMAC-SHA256 (100k iterations) shape as
    telegram_db.py's get_encryption_key(), with a distinct salt so this
    keyspace is independent of Telegram's."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=AI_KEY_SALT,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(PEPPER.encode()))
    return Fernet(key)


fernet = get_encryption_key()

engine = create_db_engine(DATABASE_URL)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

VALID_PROVIDERS = {"openai", "anthropic", "gemini", "custom"}


class AiSettings(Base):
    __tablename__ = "ai_settings"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, unique=True)
    provider = Column(String(20), nullable=False)  # 'openai' | 'anthropic' | 'gemini' | 'custom'
    encrypted_api_key = Column(Text, nullable=False)
    model = Column(String(100), nullable=True)
    # Only meaningful for provider='custom' -- the OpenAI-compatible endpoint's base URL.
    base_url = Column(String(500), nullable=True)
    # Fast-follow news integration -- reserved now so it doesn't need a
    # migration later; unused until the news feature ships.
    encrypted_news_api_key = Column(Text, nullable=True)
    news_provider = Column(String(50), nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    updated_at = Column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    def to_public_dict(self) -> dict[str, Any]:
        """Never includes the decrypted key -- only whether one is configured."""
        return {
            "provider": self.provider,
            "model": self.model,
            "baseUrl": self.base_url,
            "hasApiKey": bool(self.encrypted_api_key),
            "newsProvider": self.news_provider,
            "hasNewsApiKey": bool(self.encrypted_news_api_key),
        }


def init_db():
    """Initialize database tables."""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "AI Settings DB", logger)


def save_ai_settings(
    user_id: str,
    provider: str,
    api_key: str,
    model: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any] | None:
    """Upsert the user's AI provider settings. Encrypts api_key before storing."""
    if provider not in VALID_PROVIDERS:
        logger.error(f"Rejected AI settings save: invalid provider '{provider}'")
        return None
    try:
        settings = AiSettings.query.filter_by(user_id=user_id).first()
        encrypted = fernet.encrypt(api_key.encode()).decode()
        if settings:
            settings.provider = provider
            settings.encrypted_api_key = encrypted
            settings.model = model
            settings.base_url = base_url
        else:
            settings = AiSettings(
                user_id=user_id,
                provider=provider,
                encrypted_api_key=encrypted,
                model=model,
                base_url=base_url,
            )
            db_session.add(settings)
        db_session.commit()
        logger.info(f"AI settings saved: user={user_id}, provider={provider}")
        return settings.to_public_dict()
    except Exception as e:
        logger.exception(f"Error saving AI settings: {e}")
        db_session.rollback()
        return None


def get_ai_settings_public(user_id: str) -> dict[str, Any] | None:
    """Public-safe settings (no decrypted key) for the frontend."""
    try:
        settings = AiSettings.query.filter_by(user_id=user_id).first()
        return settings.to_public_dict() if settings else None
    except Exception as e:
        logger.exception(f"Error getting AI settings: {e}")
        return None


def get_ai_settings_decrypted(user_id: str) -> dict[str, Any] | None:
    """Internal use only (services/ai_insight_service.py) -- includes the
    decrypted API key. Never expose this dict's apiKey field to an HTTP
    response."""
    try:
        settings = AiSettings.query.filter_by(user_id=user_id).first()
        if not settings:
            return None
        return {
            "provider": settings.provider,
            "apiKey": fernet.decrypt(settings.encrypted_api_key.encode()).decode(),
            "model": settings.model,
            "baseUrl": settings.base_url,
        }
    except Exception as e:
        logger.exception(f"Error decrypting AI settings: {e}")
        return None


def delete_ai_settings(user_id: str) -> bool:
    """Delete a user's AI settings, ownership-checked (query already scoped to user_id)."""
    try:
        settings = AiSettings.query.filter_by(user_id=user_id).first()
        if not settings:
            return False
        db_session.delete(settings)
        db_session.commit()
        logger.info(f"AI settings deleted: user={user_id}")
        return True
    except Exception as e:
        logger.exception(f"Error deleting AI settings: {e}")
        db_session.rollback()
        return False


def save_news_settings(user_id: str, news_provider: str, news_api_key: str) -> dict[str, Any] | None:
    """Upsert the news-provider fast-follow fields. Requires an existing
    AiSettings row (AI provider must be configured first)."""
    try:
        settings = AiSettings.query.filter_by(user_id=user_id).first()
        if not settings:
            logger.error(f"Cannot save news settings: no AI settings row for user={user_id}")
            return None
        settings.news_provider = news_provider
        settings.encrypted_news_api_key = fernet.encrypt(news_api_key.encode()).decode()
        db_session.commit()
        logger.info(f"News settings saved: user={user_id}, provider={news_provider}")
        return settings.to_public_dict()
    except Exception as e:
        logger.exception(f"Error saving news settings: {e}")
        db_session.rollback()
        return None
