"""
Per-Broker Token Bucket Rate Limiter.

Prevents broker API rate limiting (HTTP 429 Too Many Requests) by enforcing
per-broker and per-user order dispatch rate limits.
"""

import os
import time
import threading
from typing import Dict, Tuple, Optional

from utils.logging import get_logger

logger = get_logger(__name__)

# Default rate limits (orders per second) per broker
BROKER_DEFAULT_RATES: Dict[str, float] = {
    "zerodha": 10.0,
    "angel": 20.0,
    "dhan": 20.0,
    "fyers": 15.0,
    "upstox": 15.0,
    "shoonya": 20.0,
    "deltaexchange": 20.0,
}
DEFAULT_ORDER_RATE = 15.0  # fallback orders per second for unlisted brokers


class TokenBucket:
    """Thread-safe Token Bucket implementation for rate limiting."""

    def __init__(self, rate: float, capacity: float = None):
        self.rate = rate  # tokens added per second
        self.capacity = capacity if capacity is not None else max(rate, 10.0)
        self.tokens = self.capacity
        self.last_update = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self, tokens: float = 1.0, timeout: float = 5.0) -> bool:
        """
        Acquire tokens from the bucket. Blocks up to `timeout` seconds if empty.
        Returns True if tokens acquired, False if timed out.
        """
        start_time = time.monotonic()

        while True:
            with self.lock:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now

                # Add newly generated tokens
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True

                # Calculate wait time for required tokens
                needed = tokens - self.tokens
                wait_time = needed / self.rate

            if (time.monotonic() - start_time) + wait_time > timeout:
                return False

            time.sleep(min(wait_time, 0.1))


class BrokerRateLimiter:
    """Registry of TokenBuckets per (broker_name, user_id)."""

    _instance: Optional["BrokerRateLimiter"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._buckets: Dict[Tuple[str, str], TokenBucket] = {}
        self._bucket_lock = threading.Lock()
        self._initialized = True

    def _get_rate_limit(self, broker_name: str) -> float:
        """Get order rate limit (orders/sec) for broker."""
        env_val = os.getenv(f"RATE_LIMIT_{broker_name.upper()}")
        if env_val:
            try:
                return float(env_val)
            except ValueError:
                pass
        return BROKER_DEFAULT_RATES.get(broker_name.lower(), DEFAULT_ORDER_RATE)

    def acquire_order_token(self, broker_name: str, user_id: str, timeout: float = 5.0) -> bool:
        """
        Acquire permission to send an order to `broker_name` for `user_id`.
        Blocks up to `timeout` seconds to smooth order bursts.
        """
        key = (broker_name.lower(), str(user_id))

        with self._bucket_lock:
            if key not in self._buckets:
                rate = self._get_rate_limit(broker_name)
                self._buckets[key] = TokenBucket(rate=rate)
            bucket = self._buckets[key]

        acquired = bucket.acquire(tokens=1.0, timeout=timeout)
        if not acquired:
            logger.warning(
                f"Broker rate limit timeout ({timeout}s) for broker '{broker_name}', user '{user_id}'"
            )
        return acquired


def get_broker_rate_limiter() -> BrokerRateLimiter:
    """Return global BrokerRateLimiter instance."""
    return BrokerRateLimiter()
