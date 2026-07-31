# utils/config.py

import os

from dotenv import load_dotenv

# Load environment variables from .env file with override=True to ensure values are updated
load_dotenv(override=True)


def get_valid_brokers() -> list[str]:
    """
    Return every broker this codebase supports, auto-discovered from the
    broker/*/plugin.json directories. Deliberately NOT read from .env's
    VALID_BROKERS at all - not even as an intersection/restriction.

    Every existing production server's .env has a hand-typed VALID_BROKERS
    list that was correct the day it was written but never updated when a
    new broker shipped in code (a `git pull` brings the new broker/<name>/
    directory but never touches that server's own .env). This produced
    "Invalid broker 'sharekhan'. Valid brokers: ..." in production even
    though the broker plugin itself was fully wired and auto-discovered
    everywhere else in the app (see utils/plugin_loader.py's identical
    directory-scan approach) - a first version of this function tried to
    intersect with .env's value "so an operator could still restrict
    brokers if they wanted to," but that reintroduced the exact same bug:
    any server with a merely-stale (not empty) VALID_BROKERS would still
    silently exclude every broker added after that .env was last edited.
    Per explicit instruction, broker availability must never depend on a
    server's local .env being kept in sync with the codebase - full stop.

    Returns:
        list[str]: Sorted broker directory names.
    """
    broker_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "broker")
    broker_root = os.path.normpath(broker_root)

    discovered = []
    try:
        for entry in os.listdir(broker_root):
            if entry.startswith("__") or entry.startswith("."):
                continue
            entry_path = os.path.join(broker_root, entry)
            if os.path.isdir(entry_path) and os.path.exists(
                os.path.join(entry_path, "plugin.json")
            ):
                discovered.append(entry)
    except OSError:
        discovered = []

    return sorted(set(discovered))


def get_broker_api_key() -> str | None:
    """
    Retrieve the configured broker API key.

    Returns:
        str | None: The broker API key from environment variables, or None if not set.
    """
    return os.getenv("BROKER_API_KEY")


def get_broker_api_secret() -> str | None:
    """
    Retrieve the configured broker API secret.

    Returns:
        str | None: The broker API secret from environment variables, or None if not set.
    """
    return os.getenv("BROKER_API_SECRET")


# Hardcoded - deliberately NOT read from .env. Every broker connect/OAuth
# callback (login, reconnect, and every additional-broker connect in the
# multi-broker flow) counts against this same limit. The original
# 5/minute, 25/hour defaults were tuned for a single-broker world where a
# user logged in once a day; multi-broker support means a single
# legitimate session can involve connecting/reconnecting several brokers
# back to back, each potentially retried once or twice, and production
# was still hitting the OLD 5/minute value because .env-based overrides
# never reliably reach every server (this is a single-user self-hosted
# instance per CLAUDE.md, so the limit only needs to guard against
# runaway/automated retry loops, not real multi-broker setup traffic).
LOGIN_RATE_LIMIT_MIN_VALUE = "20 per minute"
LOGIN_RATE_LIMIT_HOUR_VALUE = "200 per hour"


def get_login_rate_limit_min() -> str:
    """
    Retrieve the rate limit for logins per minute. Hardcoded (see
    LOGIN_RATE_LIMIT_MIN_VALUE above) - not configurable via .env.

    Returns:
        str: The rate limit string.
    """
    return LOGIN_RATE_LIMIT_MIN_VALUE


def get_login_rate_limit_hour() -> str:
    """
    Retrieve the rate limit for logins per hour. Hardcoded (see
    LOGIN_RATE_LIMIT_HOUR_VALUE above) - not configurable via .env.

    Returns:
        str: The rate limit string.
    """
    return LOGIN_RATE_LIMIT_HOUR_VALUE


def get_host_server() -> str:
    """
    Retrieve the host server URL.

    Returns:
        str: The host server URL string.
    """
    return os.getenv("HOST_SERVER", "http://127.0.0.1:5000")


# Default WebSocket/ZMQ host+port. Centralized here (instead of scattered
# os.getenv(..., "8765") fallbacks across ~20 files) so there is exactly one
# place to change them. Still overridable via .env - install-multi.sh and
# install-docker-multi-custom-ssl.sh rely on that to stagger ports across
# multiple co-located instances of this same platform. The values were
# bumped from the previous 8765/5555 because those are the same defaults
# used by other unrelated Max Algos-based deployments on the same host
# (e.g. alphasync-trade); two instances sharing a host would otherwise
# silently collide with no live market data and no clear error.
WEBSOCKET_HOST_DEFAULT = "127.0.0.1"
WEBSOCKET_PORT_DEFAULT = 8785
ZMQ_HOST_DEFAULT = "127.0.0.1"
ZMQ_PORT_DEFAULT = 5575


def get_websocket_host() -> str:
    """
    Retrieve the WebSocket server bind/connect host.

    Returns:
        str: The WebSocket host address (WEBSOCKET_HOST env var, or the default).
    """
    return os.getenv("WEBSOCKET_HOST", WEBSOCKET_HOST_DEFAULT)


def get_websocket_port() -> int:
    """
    Retrieve the WebSocket server port.

    Returns:
        int: The WebSocket server port (WEBSOCKET_PORT env var, or the default).
    """
    return int(os.getenv("WEBSOCKET_PORT", WEBSOCKET_PORT_DEFAULT))


def get_websocket_url() -> str:
    """
    Retrieve the full WebSocket URL clients should connect to.

    Returns:
        str: WEBSOCKET_URL env var if set, else built from host/port.
    """
    return os.getenv("WEBSOCKET_URL") or f"ws://{get_websocket_host()}:{get_websocket_port()}"


def get_zmq_host() -> str:
    """
    Retrieve the internal ZeroMQ message bus bind/connect host.

    Returns:
        str: The ZeroMQ host address (ZMQ_HOST env var, or the default).
    """
    return os.getenv("ZMQ_HOST", ZMQ_HOST_DEFAULT)


def get_zmq_port() -> int:
    """
    Retrieve the internal ZeroMQ message bus port.

    Returns:
        int: The ZeroMQ port (ZMQ_PORT env var, or the default).
    """
    return int(os.getenv("ZMQ_PORT", ZMQ_PORT_DEFAULT))
