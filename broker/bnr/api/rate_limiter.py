"""Shared BNR API rate limiter.

BNR enforces 10 req/sec and 120 req/min PER USER ACCOUNT - a single
shared quota across every endpoint (quotes, depth, orders, order book,
etc.), not a separate quota per endpoint. data.py and order_api.py each
had their own get_api_response(); without a SHARED throttle, one file's
calls (e.g. Option Chain's quote polling in data.py) can exhaust the
account's quota while order_api.py's counter still thinks it has budget
left, and the resulting order request gets rejected by BNR anyway with
"Order Recieved N in a current minute exceeds Limit 120 for user".

Import and call throttle_bnr_request() from every BNR module that makes
an HTTP call to prime.bnrsecurities.com, right before the request.
"""

import time
from threading import Lock

_RATE_LOCK = Lock()
_request_times: list = []  # timestamps (seconds) of recent BNR API calls
_MAX_PER_SEC = 10  # BNR's documented hard limit -- no safety margin, per user request
_MAX_PER_MIN = 120  # BNR's documented hard limit -- no safety margin, per user request


def throttle_bnr_request():
    """Block the calling thread briefly to manage rate limits. Never sleep for
    more than 1.5s total to prevent HTTP 504 Gateway Timeouts on web workers."""
    start_wait = time.time()
    while True:
        with _RATE_LOCK:
            now = time.time()
            # Drop timestamps older than 60s - nothing before that matters.
            while _request_times and now - _request_times[0] > 60:
                _request_times.pop(0)

            in_last_second = sum(1 for t in _request_times if now - t < 1.0)
            in_last_minute = len(_request_times)

            if in_last_second < _MAX_PER_SEC and in_last_minute < _MAX_PER_MIN:
                _request_times.append(now)
                return

            # If we've already waited more than 1.5s total, break out to prevent 504 Gateway Timeout
            if now - start_wait > 1.5:
                _request_times.append(now)
                return

            if in_last_minute >= _MAX_PER_MIN:
                wait_for = min(60 - (now - _request_times[0]) + 0.05, 0.5)
            else:
                oldest_in_second = next(t for t in _request_times if now - t < 1.0)
                wait_for = 1.0 - (now - oldest_in_second) + 0.05
        time.sleep(max(min(wait_for, 0.5), 0.05))
