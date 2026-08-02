"""
Per-user Socket.IO emit scoping.

`socketio.emit(event, payload)` with no `room=` broadcasts to EVERY
connected client on the platform. On a single-admin deployment that was
harmless; on a multi-user instance (each user with their own broker
connections -- see CLAUDE.md "Security and Deployment Model") it means
User A's activity fires toasts, notification-drawer entries and state
updates in User B's browser.

That bug was found and fixed piecemeal three times already -- app.py's
`force_logout` room, subscribers/socketio_subscriber.py's order events,
services/signal_engine.py's webhook/deployment events -- each time by
hand-rolling the same `room=f"user_{username}"` logic locally. This module
is that logic in one place, so the remaining emitters (broker connect /
master contract, kill switch, master risk, pending orders, analyzer,
historify jobs) can be fixed once and any new
emitter has an obvious right thing to call.

Two entry points:

  emit_to_user(event, payload, username)
      When the acting user is already known (a username string).

  emit_to_current_user(event, payload)
      When it isn't -- resolves the user from, in order: an explicit
      `user_scope()` override (set by background/threaded call paths that
      have no Flask session), then the Flask session. Used by the broker
      master-contract download path, where the emit happens ~25 broker
      modules deep on a background thread and threading a username
      through every signature would mean touching every broker.

Unresolvable == DROP, never broadcast. See _emit_scoped's docstring.
"""

import contextvars
from contextlib import contextmanager

from utils.logging import get_logger

logger = get_logger(__name__)

_user_scope_var: contextvars.ContextVar = contextvars.ContextVar(
    "socket_emit_user_scope", default=None
)


@contextmanager
def user_scope(username: str | None):
    """Declare which user the work in this block acts on behalf of, so
    `emit_to_current_user()` called anywhere inside it (including many
    frames deep in a broker module) scopes its emit correctly.

    Uses contextvars, not threading.local(), for the same reasons
    utils/broker_context.py documents at length: a ContextVar is isolated
    per concurrent request (no cross-request leak -- which would be the
    very bug this module exists to fix) while still being explicitly
    propagatable into a spawned worker thread via
    `contextvars.copy_context()` + `ctx.run(...)`.
    """
    token = _user_scope_var.set(username)
    try:
        yield
    finally:
        _user_scope_var.reset(token)


def get_scoped_username() -> str | None:
    """Return the username set by an active `user_scope()`, else None."""
    return _user_scope_var.get()


def resolve_current_username() -> str | None:
    """Best-effort "who is this work for?": explicit `user_scope()` first
    (works off-request, on background threads), then the Flask session
    (works for ordinary request-bound emits). None if neither applies."""
    scoped = _user_scope_var.get()
    if scoped:
        return scoped

    try:
        from flask import has_request_context
        from flask import session as flask_session

        if has_request_context():
            username = flask_session.get("user")
            if isinstance(username, str) and username:
                return username
    except Exception:
        # No app/request context, or session unavailable -- fall through to
        # None so the caller drops the emit rather than broadcasting.
        logger.debug("No Flask session available while resolving emit scope")

    return None


def username_from_api_key(api_key: str | None) -> str | None:
    """Resolve the owning username from a Max Algos API key, for emitters
    whose only handle on the acting user is the key the request carried."""
    if not api_key:
        return None
    try:
        from database.auth_db import verify_api_key

        return verify_api_key(api_key) or None
    except Exception:
        logger.debug("Could not resolve username from api_key for socketio room scoping")
        return None


def emit_to_user(event_name: str, payload, username: str | None) -> bool:
    """Emit `event_name` only to `username`'s own connected clients.

    Returns True if emitted, False if dropped because the user could not
    be resolved. Callers generally ignore the return value; it exists so
    tests can assert the drop behaviour.
    """
    return _emit_scoped(event_name, payload, username)


def emit_to_current_user(event_name: str, payload) -> bool:
    """Emit `event_name` only to the current acting user's own clients,
    resolved via `resolve_current_username()`."""
    return _emit_scoped(event_name, payload, resolve_current_username())


class _ScopedSocketIOProxy:
    """Drop-in stand-in for `extensions.socketio` exposing only `.emit()`,
    which scopes to the current acting user instead of broadcasting.

    Exists for the ~28 `broker/*/database/master_contract_db.py` modules.
    Each ends its download with `socketio.emit("master_contract_download",
    ...)` (several with `return socketio.emit(...)`, so the return value is
    load-bearing to callers as a truthiness/None signal). Swapping the
    single import line

        from extensions import socketio
    ->  from utils.socket_scope import scoped_socketio as socketio

    fixes every emit in that file without touching the emit call sites
    themselves -- far less invasive, and far less risky across 28
    independently-written broker modules, than rewriting each call.

    The acting user comes from the `user_scope()` set in
    utils/auth_utils.async_master_contract_download.
    """

    @staticmethod
    def emit(event_name: str, payload=None, *args, **kwargs) -> bool:
        # An explicit room= from the caller wins -- nothing in the broker
        # modules passes one today, but honour it rather than silently
        # overriding a future caller that knows better.
        room = kwargs.pop("room", None)
        if room is not None:
            try:
                from extensions import socketio as _socketio

                _socketio.emit(event_name, payload, *args, room=room, **kwargs)
                return True
            except Exception:
                logger.exception(f"Failed to emit '{event_name}' to room {room}")
                return False
        return _emit_scoped(event_name, payload, resolve_current_username())


scoped_socketio = _ScopedSocketIOProxy()


def _emit_scoped(event_name: str, payload, username: str | None) -> bool:
    """Emit into `user_<username>`, the room every browser tab joins on
    connect (app.py `_join_user_room`).

    When `username` is None the emit is DROPPED, not broadcast. That is a
    deliberate fail-closed choice, matching the convention already set in
    subscribers/socketio_subscriber.py: the cost of dropping is that one
    user misses a live toast for an action whose durable state (order
    book, broker-connection status, job status row) is still correct and
    still visible on refresh. The cost of broadcasting is showing one
    user's trading activity to every other account on the instance --
    strictly worse, and the actual reported bug.
    """
    if not username:
        logger.debug(
            f"Dropping '{event_name}' socketio emit -- no acting user could be "
            "resolved to scope it to (see utils/socket_scope.py)"
        )
        return False

    try:
        from extensions import socketio

        socketio.emit(event_name, payload, room=f"user_{username}")
        return True
    except Exception:
        logger.exception(f"Failed to emit '{event_name}' to user room")
        return False
