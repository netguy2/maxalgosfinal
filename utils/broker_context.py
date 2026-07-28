"""
Sequential multi-broker credential context.

Every broker module in broker/<name>/ reads credentials via
os.getenv("BROKER_API_KEY") etc. (patched in app.py to resolve dynamically
per-request). That pattern is universal across all 30+ brokers and was
deliberately left untouched (see plan: "never break working stuff").

For the new multi-broker order fan-out feature (services/multi_broker_order_service.py),
one Flask request needs to act on SEVERAL different brokers in sequence -
never concurrently, since os.environ-style resolution is process-wide, not
per-broker. This module provides that serialization:

    with broker_credential_context(username, "zebu"):
        # app.py's os.getenv patch resolves Zebu's credentials here
        ...place order via broker.zebu.api.order_api...
    # override cleared; next broker in the fan-out loop uses its own credentials

The override is stored in a contextvars.ContextVar, NOT threading.local()
and NOT a plain module global - both of those were tried and both are
wrong for different reasons:

  - threading.local() does not propagate into NEW worker threads (e.g.
    services/basket_order_service.py's process_basket_order_with_auth
    places a basket's individual orders concurrently via its own
    ThreadPoolExecutor), so those workers saw no override and silently
    fell back to the session's data-broker credentials - the "basket
    works for one broker but fails for the other" bug.

  - A plain module-level global is worse: since Flask serves multiple
    CONCURRENT requests in different threads, a global override set by
    one request's multi-broker order (e.g. Option Chain's continuous
    background quote polling) is visible to every OTHER in-flight
    request too, for as long as the lock is held - a cross-request
    credential leak. That is what broke Option Chain and other unrelated
    reads the moment a second broker existed and any multi-broker action
    ran concurrently with them.

contextvars.ContextVar gets both properties right: each Flask request
already runs in its own context (so concurrent requests never see each
other's override - no leak), and unlike threading.local() its value CAN
be explicitly propagated into a spawned worker thread via
`contextvars.copy_context()` + `ctx.run(...)` (see
basket_order_service.py's ThreadPoolExecutor.submit(ctx.run, ...) calls).

No process-wide lock is used here (a prior version held a
threading.Lock() across the whole `with` block, including the broker
network call inside it - this serialized EVERY caller of this context
manager across the ENTIRE app: multi-broker order fan-out, OAuth
callbacks, session-resume validation, and the WebSocket
proxy/streaming connection manager all call this function. One slow
broker call anywhere in that list stalled every other one, which is
what caused Option Chain's live feed to 500 right after an unrelated
multi-broker order attempt. The ContextVar is already isolated per
request/context, so no lock is needed for correctness - each caller
only ever touches its own (username, broker) pair in its own context).
"""

import contextvars
from contextlib import contextmanager

_override_var: contextvars.ContextVar = contextvars.ContextVar(
    "broker_credential_override", default=None
)


def get_active_broker_override():
    """Return (username, broker) if a broker_credential_context is
    currently active in this request's context (or a context explicitly
    propagated from it via contextvars.copy_context()), else None."""
    return _override_var.get()


@contextmanager
def broker_credential_context(username: str, broker: str):
    """Scope credential resolution to a single explicit (username,
    broker) pair for the duration of the block. Only visible within this
    request's own context (and any thread that explicitly runs inside a
    copy of it - see module docstring) - never leaks to other concurrent
    requests. Used only by the multi-broker order fan-out path -
    single-broker flows never call this and are completely unaffected."""
    token = _override_var.set((username, broker))
    try:
        yield
    finally:
        _override_var.reset(token)
