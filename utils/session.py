import os
from datetime import datetime, timedelta
from functools import wraps

import pytz
from cachetools import TTLCache
from flask import redirect, session, url_for

from utils.logging import get_logger

logger = get_logger(__name__)


def is_session_expiry_disabled():
    """Check if session expiry is disabled (e.g., for crypto brokers with 24/7 markets).

    Note: Each Max Algos instance serves a single broker, so this env var is
    instance-scoped — it only affects the broker configured for this instance,
    not all brokers globally.  The install script sets it automatically when
    a crypto broker (e.g. deltaexchange) is selected.
    """
    return os.getenv("DISABLE_SESSION_EXPIRY", "false").lower() == "true"


def get_session_expiry_time():
    """Get session expiry time set to 3 AM IST next day"""
    # Skip expiry for crypto brokers (24/7 markets)
    if is_session_expiry_disabled():
        logger.debug("Session expiry disabled (crypto broker / 24/7 market)")
        return timedelta(days=365)

    now_utc = datetime.now(pytz.timezone("UTC"))
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

    # Get configured expiry time or default to 3 AM
    expiry_time = os.getenv("SESSION_EXPIRY_TIME", "03:00")
    hour, minute = map(int, expiry_time.split(":"))

    target_time_ist = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If current time is past target time, set expiry to next day
    if now_ist > target_time_ist:
        target_time_ist += timedelta(days=1)

    remaining_time = target_time_ist - now_ist
    logger.debug(f"Session expiry time set to: {target_time_ist}")
    return remaining_time


def set_session_login_time():
    """Set the session login time in IST"""
    now_utc = datetime.now(pytz.timezone("UTC"))
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))
    session["login_time"] = now_ist.isoformat()
    logger.info(f"Session login time set to: {now_ist}")


def is_session_valid():
    """Check if the current session is valid"""
    if not session.get("logged_in"):
        logger.debug("Session invalid: 'logged_in' flag not set")
        return False

    # If no login time is set, consider session invalid
    if "login_time" not in session:
        logger.debug("Session invalid: 'login_time' not in session")
        return False

    # If session_id is set, verify that it is still active in DB (single session enforcement)
    session_id = session.get("session_id")
    username = session.get("user")
    if session_id and username:
        try:
            from database.auth_db import is_session_id_active

            if not is_session_id_active(username, session_id):
                logger.info(
                    f"Session invalid for {username}: session_id {session_id[:8]}... superseded by another device"
                )
                return False
        except Exception as err:
            logger.warning(f"Error checking active session_id in is_session_valid: {err}")

    # Skip expiry check for crypto brokers (24/7 markets)
    if is_session_expiry_disabled():
        logger.debug("Session expiry disabled (crypto broker / 24/7 market)")
        return True

    now_utc = datetime.now(pytz.timezone("UTC"))
    now_ist = now_utc.astimezone(pytz.timezone("Asia/Kolkata"))

    # Parse login time
    login_time = datetime.fromisoformat(session["login_time"])

    # Get configured expiry time
    expiry_time = os.getenv("SESSION_EXPIRY_TIME", "03:00")
    hour, minute = map(int, expiry_time.split(":"))

    # Get today's expiry time
    daily_expiry = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)

    # If current time is past expiry time and login was before expiry time
    if now_ist > daily_expiry and login_time < daily_expiry:
        logger.info(f"Session expired at {daily_expiry} IST")
        return False

    logger.debug(
        f"Session valid. Current time: {now_ist}, Login time: {login_time}, Daily expiry: {daily_expiry}"
    )
    return True


def revoke_user_tokens(revoke_db_tokens=True):
    """
    Revoke auth tokens for the current user when session expires.

    Also publishes cache invalidation events via ZeroMQ for multi-process deployments.
    This ensures WebSocket proxy and other processes clear their stale cached tokens.
    See GitHub issue #765 for details on the cross-process cache synchronization problem.

    Args:
        revoke_db_tokens (bool): If True, revokes the token in the database (Invalidates API Key).
                                 If False, only clears local caches (Preserves API Key).
    """
    if "user" in session:
        username = session.get("user")
        try:
            from database.auth_db import auth_cache, feed_token_cache, upsert_auth

            # Clear cache entries first to prevent stale data access
            cache_key_auth = f"auth-{username}"
            cache_key_feed = f"feed-{username}"
            if cache_key_auth in auth_cache:
                del auth_cache[cache_key_auth]
            if cache_key_feed in feed_token_cache:
                del feed_token_cache[cache_key_feed]

            # Publish cache invalidation event via ZeroMQ for other processes
            # This notifies WebSocket proxy and other processes to clear their stale caches
            try:
                from database.cache_invalidation import publish_all_cache_invalidation
                publish_all_cache_invalidation(username)
                logger.debug(f"Published cache invalidation for user: {username}")
            except Exception as invalidation_error:
                # Don't fail logout if cache invalidation fails
                logger.warning(f"Failed to publish cache invalidation for user {username}: {invalidation_error}")

            # Clear symbol cache on logout/session expiry
            try:
                from database.master_contract_cache_hook import clear_cache_on_logout

                clear_cache_on_logout()
            except Exception as cache_error:
                logger.exception(f"Error clearing symbol cache: {cache_error}")

            # Clear settings cache on logout/session expiry
            try:
                from database.settings_db import clear_settings_cache

                clear_settings_cache()
            except Exception as cache_error:
                logger.exception(f"Error clearing settings cache: {cache_error}")

            # Clear strategy cache on logout/session expiry
            try:
                from database.strategy_db import clear_strategy_cache

                clear_strategy_cache()
            except Exception as cache_error:
                logger.exception(f"Error clearing strategy cache: {cache_error}")

            if revoke_db_tokens:
                # Revoke the auth token in database. Preserve the broker
                # name on revoke (don't pass "") so that once the broker's
                # token is later found to still be valid via its own
                # AuthBrokerSession entry (multi-broker resume path in
                # blueprints/auth.py's _try_resume_broker_session), the app
                # knows WHICH broker to silently restore as the data broker
                # instead of forcing the user through a fresh OAuth login
                # every time this daily/session revoke fires.
                from database.auth_db import get_auth_token_dbquery as _get_auth_row
                _existing_auth = _get_auth_row(username)
                _broker_to_preserve = _existing_auth.broker if _existing_auth else ""
                inserted_id = upsert_auth(username, "", _broker_to_preserve, revoke=True)
                if inserted_id is not None:
                    logger.info(f"Auto-expiry: Revoked auth tokens for user: {username}")
                else:
                    logger.error(f"Auto-expiry: Failed to revoke auth tokens for user: {username}")

                # Clear all active sessions for this user (tokens are invalid now)
                try:
                    from database.auth_db import clear_user_sessions
                    clear_user_sessions(username)
                    logger.info(f"Auto-expiry: Cleared active sessions for user: {username}")
                except Exception as session_error:
                    logger.warning(f"Error clearing active sessions: {session_error}")

                try:
                    from extensions import socketio

                    # room= scopes this to the expiring user's own devices --
                    # an unscoped emit broadcast to EVERY connected client on
                    # the platform, so one user's daily 3 AM IST token
                    # rollover force-logged out every other logged-in user
                    # too. Matches the same room convention joined in
                    # app.py's default-namespace connect handler.
                    room = f"user_{username}"
                    socketio.emit(
                        "force_logout",
                        {
                            "message": (
                                "Session expired at market close. Please log in again "
                                "and complete broker authentication."
                            ),
                        },
                        room=room,
                    )
                    socketio.emit(
                        "active_sessions_update",
                        {
                            "count": 0,
                            "sessions": [],
                        },
                        room=room,
                    )
                    logger.info(f"Auto-expiry: Sent force logout for user: {username}")
                except Exception as socket_error:
                    logger.warning(f"Error broadcasting auto-expiry logout: {socket_error}")
            else:
                logger.info(
                    f"Auto-expiry: Skipped DB revocation for user: {username} (Preserving API access)"
                )

        except Exception as e:
            logger.exception(f"Error revoking tokens during auto-expiry for user {username}: {e}")


# ---------------------------------------------------------------------------
# Platform-fee subscription enforcement
# ---------------------------------------------------------------------------
# When SUBSCRIPTION_GATE_ENABLED is on, a non-admin user without an active
# PlatformSubscription gets a session at login (so the payment endpoints can
# identify them) but must be blocked from every data endpoint until they
# subscribe. check_session_validity is the single decorator every
# session-protected data route already goes through, so enforcing here gives
# the gate real teeth: typing /dashboard into the URL bar renders the SPA
# shell, but every API behind it returns 403 subscription_required.
#
# /auth/* and /payments/* stay reachable -- those are exactly the endpoints
# an unsubscribed user needs to check their session and pay the fee.
# /api/v1/killswitch/* is exempt too -- an emergency stop must work even for
# an unsubscribed account (e.g. mid-billing-dispute), matching the design
# doc's "kill switch endpoints must not be gated by kill switch itself, nor
# by anything else that could leave a user unable to stop their own trading."
_SUBSCRIPTION_EXEMPT_PREFIXES = ("/auth/", "/payments/", "/api/v1/killswitch/")

# Short cache of username -> access decision so this doesn't add a DB lookup
# to every request. Kept small (30s): after payment, the verify route calls
# invalidate_subscription_cache() so the user is unblocked immediately.
_subscription_access_cache = TTLCache(maxsize=512, ttl=30)


def invalidate_subscription_cache(username: str) -> None:
    """Drop the cached gate decision for a user -- called right after their
    subscription is activated so access opens without waiting out the TTL."""
    _subscription_access_cache.pop(username, None)


def _subscription_blocks_request(username: str) -> bool:
    """True if the platform-fee gate should block this user's data access."""
    gate_on = os.getenv("SUBSCRIPTION_GATE_ENABLED", "True").lower() == "true"
    if not gate_on or not username:
        return False

    cached = _subscription_access_cache.get(username)
    if cached is not None:
        return cached

    # Lazy imports: utils/session is imported before the DB modules during
    # app startup (same convention as revoke_user_tokens above).
    try:
        from database.user_db import find_user_by_exact_username, get_active_platform_subscription

        user = find_user_by_exact_username(username)
        if user is None or user.is_admin:
            blocked = False
        else:
            blocked = get_active_platform_subscription(username) is None
    except Exception as e:
        # Fail-open on infrastructure errors: a DB hiccup must not lock every
        # paying user out of the product.
        logger.exception(f"Subscription gate check failed for {username}: {e}")
        blocked = False

    _subscription_access_cache[username] = blocked
    return blocked


def check_session_validity(f):
    """Decorator to check session validity before executing route"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            # Revoke local app session/caches while preserving DB broker token
            # (another device may be logged in and using the DB broker token)
            revoke_user_tokens(revoke_db_tokens=False)
            session.clear()

            # Check if this is an AJAX/fetch request
            from flask import jsonify, request

            is_ajax = (
                request.headers.get("X-Requested-With") == "XMLHttpRequest"
                or request.headers.get("Accept", "").startswith("application/json")
                or request.content_type == "application/json"
                or request.is_json
            )

            if is_ajax:
                # Return JSON response for AJAX requests instead of redirect
                logger.info("Invalid/displaced session detected - returning 401 for AJAX request")
                return jsonify(
                    {
                        "status": "error",
                        "error": "session_expired",
                        "reason": "logged_in_another_device",
                        "message": "Your account was logged in from another device. Please log in again.",
                    }
                ), 401

            logger.info("Invalid session detected - redirecting to login")
            return redirect(url_for("auth.login"))

        # Platform-fee gate: block data endpoints for unsubscribed non-admin
        # users (session itself stays valid so they can pay via /payments/*).
        from flask import jsonify, request

        if not request.path.startswith(_SUBSCRIPTION_EXEMPT_PREFIXES):
            username = session.get("user")
            if isinstance(username, str) and _subscription_blocks_request(username):
                logger.info(
                    f"Subscription gate blocked {username} on {request.path}"
                )
                return jsonify(
                    {
                        "status": "error",
                        "error": "subscription_required",
                        "message": "An active subscription is required to continue.",
                        "redirect": "/subscribe",
                    }
                ), 403

        logger.debug("Session validated successfully")
        return f(*args, **kwargs)

    return decorated_function


def invalidate_session_if_invalid(f):
    """Decorator to invalidate session if invalid without redirecting"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            logger.info("Invalid session detected - clearing session")
            # Revoke tokens before clearing session
            revoke_user_tokens()
            session.clear()
        return f(*args, **kwargs)

    return decorated_function
