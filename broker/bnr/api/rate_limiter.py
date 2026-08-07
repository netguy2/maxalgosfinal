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


class BnrRateLimitExceeded(Exception):
    """Raised instead of sending a request we know is over BNR's quota.

    See throttle_bnr_request() for why this is preferable to sending it
    anyway and letting BNR reject it.
    """


def throttle_bnr_request():
    """Block the calling thread briefly to manage rate limits.

    Never sleeps more than 1.5s total, to prevent HTTP 504 Gateway Timeouts
    on web workers. If the quota is STILL exhausted after that wait, this
    raises BnrRateLimitExceeded rather than sending the request anyway.

    Sending anyway is what the previous version did, and it produced
    actively misleading failures: BNR rejects an over-quota request with an
    opaque auth-shaped error ("Session Expired : Invalid Session Key"),
    which surfaced to users as "your broker session died" on a token that
    was perfectly valid -- while the real cause was a burst of signals
    briefly exceeding the 120/min account quota. Users saw a scary,
    wrong diagnosis and had no reason to suspect rate limiting.

    Failing fast with an accurate, self-describing error is strictly
    better: the caller reports what actually happened, the request that
    could never have succeeded is not sent, and the wasted call does not
    consume more of the very quota that is already exhausted.
    """
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

            # Waited as long as we safely can without risking a 504.
            if now - start_wait > 1.5:
                raise BnrRateLimitExceeded(
                    f"BNR account rate limit reached ({in_last_second}/{_MAX_PER_SEC} "
                    f"per second, {in_last_minute}/{_MAX_PER_MIN} per minute) and it "
                    "did not clear within 1.5s. Request not sent. This is a temporary "
                    "throttle on your broker account's shared quota, NOT a login or "
                    "session problem -- retry in a moment, or reduce how frequently "
                    "your strategies poll."
                )

            if in_last_minute >= _MAX_PER_MIN:
                wait_for = min(60 - (now - _request_times[0]) + 0.05, 0.5)
            else:
                oldest_in_second = next(t for t in _request_times if now - t < 1.0)
                wait_for = 1.0 - (now - oldest_in_second) + 0.05
        time.sleep(max(min(wait_for, 0.5), 0.05))
