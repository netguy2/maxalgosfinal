"""Loader for config/runtime.yaml — non-secret operational toggles.

Kept separate from .env so operators can flip switches like
TRUST_PROXY_HEADERS on a server by editing one small YAML file, without
touching .env (which holds API keys/secrets and is often locked down or
managed by a different process/CI step).

Each setting can still be overridden by an environment variable of the same
name (upper-cased) for container/CI setups that prefer passing config via
environment — the env var wins when present.
"""

import os
import threading

import yaml

from utils.logging import get_logger

logger = get_logger(__name__)

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "runtime.yaml")

_lock = threading.Lock()
_cache = None


def _load():
    global _cache
    with _lock:
        if _cache is not None:
            return _cache
        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                _cache = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.debug(f"{_CONFIG_PATH} not found, using defaults")
            _cache = {}
        return _cache


def get_bool(key: str, default: bool = False) -> bool:
    """Read a boolean runtime setting.

    Resolution order: env var of the same name (upper-cased) > config/runtime.yaml > default.
    """
    env_val = os.getenv(key.upper())
    if env_val is not None:
        return env_val.strip().lower() in ("true", "1", "yes", "t")

    value = _load().get(key.lower())
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "t")
