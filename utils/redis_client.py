"""
Redis Client Manager & Distributed Cache Service.

Provides an optional, thread-safe Redis client interface for distributed caching
(user settings, deployment state, session caching) and SocketIO multi-worker scale.
Falls back gracefully when Redis is not configured or unavailable.
"""

import os
import threading
from typing import Any, Optional

from utils.logging import get_logger

logger = get_logger(__name__)

_redis_client = None
_redis_lock = threading.Lock()
_redis_checked = False


def get_redis_client():
    """
    Get or initialize the shared Redis client instance.
    Returns None if REDIS_URL is not set or redis library is unavailable.
    """
    global _redis_client, _redis_checked

    if _redis_checked:
        return _redis_client

    with _redis_lock:
        if _redis_checked:
            return _redis_client

        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            host = os.getenv("REDIS_HOST", "127.0.0.1")
            port = os.getenv("REDIS_PORT")
            if port:
                redis_url = f"redis://{host}:{port}/0"

        if not redis_url:
            logger.debug("REDIS_URL not configured; running in local in-memory mode")
            _redis_checked = True
            _redis_client = None
            return None

        try:
            import redis

            client = redis.Redis.from_url(
                redis_url,
                socket_timeout=2.0,
                socket_connect_timeout=2.0,
                decode_responses=True,
            )
            # Ping Redis server to verify connectivity
            client.ping()
            _redis_client = client
            logger.info(f"Successfully connected to Redis at {redis_url}")
        except ImportError:
            logger.warning("redis library not installed; falling back to in-memory mode")
            _redis_client = None
        except Exception as e:
            logger.warning(f"Failed to connect to Redis ({redis_url}): {e}. Falling back to in-memory mode")
            _redis_client = None

        _redis_checked = True
        return _redis_client


def is_redis_available() -> bool:
    """Return True if Redis is connected and available."""
    client = get_redis_client()
    if not client:
        return False
    try:
        return bool(client.ping())
    except Exception:
        return False


def redis_get(key: str, default: Any = None) -> Any:
    """Get a value from Redis cache with fallback."""
    client = get_redis_client()
    if not client:
        return default
    try:
        val = client.get(key)
        return val if val is not None else default
    except Exception as e:
        logger.debug(f"Redis get error for key '{key}': {e}")
        return default


def redis_set(key: str, value: str, ttl: Optional[int] = None) -> bool:
    """Set a value in Redis cache with optional TTL in seconds."""
    client = get_redis_client()
    if not client:
        return False
    try:
        if ttl:
            client.setex(key, ttl, value)
        else:
            client.set(key, value)
        return True
    except Exception as e:
        logger.debug(f"Redis set error for key '{key}': {e}")
        return False


def redis_delete(key: str) -> bool:
    """Delete a key from Redis cache."""
    client = get_redis_client()
    if not client:
        return False
    try:
        client.delete(key)
        return True
    except Exception as e:
        logger.debug(f"Redis delete error for key '{key}': {e}")
        return False
