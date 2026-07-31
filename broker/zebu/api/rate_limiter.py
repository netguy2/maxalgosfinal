"""Shared Zebu API rate limiter.

Zebu (Noren/MYNT) enforces 10 req/sec and 120 req/min PER USER ACCOUNT --
a single shared quota across every endpoint (quotes, depth, orders, order
book, etc.), not a separate quota per endpoint. Without a SHARED throttle,
Option Chain / Max Pain / IV / Greeks quote polling can exhaust the
account's per-minute quota (the batching in data.py only paced the
per-SECOND limit, so sustained 10/sec = 600/min blew straight past the
120/min cap), and Zebu rejects the excess with
"Invalid Input : Order Recieved N in a current minute exceeds Limit 120
for user".

This mirrors broker/bnr/api/rate_limiter.py verbatim (BNR has the same
Noren-family limits and this pattern is why BNR's quotes work where
Zebu's were failing). Import and call throttle_zebu_request() from every
Zebu module that makes an HTTP call to go.mynt.in, right before the
request.
"""

import time
from threading import Lock

_RATE_LOCK = Lock()
_request_times: list = []  # timestamps (seconds) of recent Zebu API calls
_MAX_PER_SEC = 10  # Zebu's documented hard limit -- no safety margin, per user request
_MAX_PER_MIN = 120  # Zebu's documented hard limit -- no safety margin, per user request


def throttle_zebu_request():
    """Block the calling thread briefly to manage rate limits. Never sleep for
    more than 1.5s total to prevent HTTP 504 Gateway Timeouts on web workers."""
    start_wait = time.time()
    while True:
        with _RATE_LOCK:
            now = time.time()
            # Drop timestamps older than 60s -- nothing before that matters.
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
