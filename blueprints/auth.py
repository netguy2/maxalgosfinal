import os
import re
import secrets

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    request,
    session,
    url_for,
)
from flask_wtf.csrf import generate_csrf

from database.auth_db import auth_cache, feed_token_cache, upsert_auth
from database.settings_db import get_smtp_settings, set_smtp_settings
from database.user_db import (  # Import the function
    User,
    add_user,
    authenticate_user,
    consume_email_verification_token,
    create_email_verification_token,
    db_session,
    find_user_by_email,
    find_user_by_exact_username,
    find_user_by_login_identifier,
    find_user_by_username,
    get_active_platform_subscription,
)
from extensions import socketio

# CSRF exemption for the /login view (a fresh visitor has no CSRF cookie
# yet, so it can't be required there): CANNOT be applied as an @csrf.exempt
# decorator here. That would need a `csrf` instance imported at module load
# time, but blueprints/auth.py is imported at app.py's TOP LEVEL (line ~41,
# `from blueprints.auth import auth_bp`), long before create_app() runs
# `csrf = CSRFProtect(app)` (~line 232) -- so `csrf` cannot exist yet at
# this point, in either extensions.py (which never defined it at all) or
# app.py. That mismatch is exactly what caused every deployed instance to
# crash-loop with `ImportError: cannot import name 'csrf' from 'extensions'`
# during gunicorn worker boot. The actual exemption is applied instead in
# app.py, AFTER create_app() creates the CSRFProtect instance and registers
# this blueprint, via `app.csrf.exempt(login)`.
from limiter import limiter  # Import the limiter instance
from utils.email_debug import debug_smtp_connection
from utils.email_utils import send_password_reset_email, send_test_email, send_verification_email
from utils.ip_helper import get_real_ip
from utils.logging import get_logger
from utils.session import check_session_validity, is_session_valid, revoke_user_tokens
from utils.socket_scope import emit_to_user

# Platform-fee subscription gate: ON by default for this commercial
# multi-tenant deployment. Non-admin users must hold an active
# PlatformSubscription to reach the dashboard; admins are always exempt.
# Set SUBSCRIPTION_GATE_ENABLED=false in .env to disable (e.g. for a
# private single-admin install). Keep this default in sync with the
# enforcement copy in utils/session.py::_subscription_blocks_request.
SUBSCRIPTION_GATE_ENABLED = os.getenv("SUBSCRIPTION_GATE_ENABLED", "True").lower() == "true"
REGISTRATION_RATE_LIMIT = os.getenv("REGISTRATION_RATE_LIMIT", "10 per hour")

# Initialize logger
logger = get_logger(__name__)

# Access environment variables
LOGIN_RATE_LIMIT_MIN = os.getenv("LOGIN_RATE_LIMIT_MIN", "5 per minute")
LOGIN_RATE_LIMIT_HOUR = os.getenv("LOGIN_RATE_LIMIT_HOUR", "25 per hour")
RESET_RATE_LIMIT = os.getenv("RESET_RATE_LIMIT", "15 per hour")  # Password reset rate limit

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


class _BrokerValidationTimeout(Exception):
    """Raised when broker-token validation during login-resume exceeds its
    wall-clock budget (broker API slow/unreachable). The login flow catches
    this, skips the resume, and proceeds to normal login instead of hanging."""


def _broker_validation_timeout(seconds: int):
    """Context manager that bounds a blocking broker call to `seconds`.

    Under the production gunicorn+eventlet worker, eventlet has monkey-
    patched sockets, so eventlet.Timeout is the correct, non-hanging way to
    interrupt a blocking green-threaded HTTP call (a raw thread + join is
    known to deadlock with eventlet in this codebase). On the plain dev
    server eventlet isn't active, so we return a no-op context manager --
    dev latency isn't critical and this only runs when resuming a real
    stored broker session.

    Raises _BrokerValidationTimeout on expiry so the caller can distinguish
    a timeout from other failures.
    """
    try:
        import eventlet

        # eventlet.Timeout(seconds, exc) raises `exc` in the current green
        # thread if the block doesn't finish in time. Only meaningful when
        # eventlet has actually patched the stdlib (production).
        if getattr(eventlet, "patcher", None) and eventlet.patcher.is_monkey_patched("socket"):
            return eventlet.Timeout(seconds, _BrokerValidationTimeout())
    except Exception:
        pass

    # Dev / eventlet-not-active: no-op timeout guard.
    from contextlib import nullcontext

    return nullcontext()


def _utcnow_iso() -> str:
    """ISO timestamp used for TOTP freshness markers in the session."""
    from datetime import datetime

    return datetime.utcnow().isoformat()


# How long the password→TOTP step is allowed to dawdle before the pending
# session marker is expired. Short window — we want a stolen browser session
# without the TOTP app to time out, not allow indefinite retry.
_PENDING_TOTP_MAX_AGE_SECS = 300  # 5 minutes


def _pending_totp_is_fresh() -> bool:
    """True if the password step happened within the last 5 minutes."""
    started = session.get("pending_totp_started_at")
    if not started:
        return False
    try:
        from datetime import datetime, timedelta

        ts = datetime.fromisoformat(started)
        return datetime.utcnow() - ts <= timedelta(seconds=_PENDING_TOTP_MAX_AGE_SECS)
    except (TypeError, ValueError):
        return False


def _clear_pending_totp() -> None:
    session.pop("pending_totp_user", None)
    session.pop("pending_totp_started_at", None)


def _stamp_last_login(user) -> None:
    """Record last_login_at on successful login. Best-effort -- never blocks
    the login flow on failure."""
    if user is None:
        return
    try:
        from datetime import datetime
        user.last_login_at = datetime.utcnow()
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Failed to stamp last_login_at for {user.username}: {e}")


@auth_bp.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(status="error", message="Too many login attempts. Please wait a minute and try again."), 429


@auth_bp.route("/csrf-token", methods=["GET"])
def get_csrf_token():
    """Return a CSRF token for React SPA to use in form submissions."""
    token = generate_csrf()
    return jsonify({"csrf_token": token})


@auth_bp.route("/broker-config", methods=["GET"])
def get_broker_config():
    """Return broker configuration for React SPA.

    broker_name is always returned (needed to display the broker login button).
    broker_api_key and redirect_url are only returned when authenticated.
    """
    broker_name = request.args.get("broker")

    # Get current user from session
    username = session.get("user")

    # Fetch this specific broker's saved credentials (if a broker was named
    # in the query string). If no broker_name yet, we don't know which
    # broker's credentials to fetch - resolve it below via redirect_url
    # first, then fetch.
    def _fetch_creds(name):
        if not (username and name):
            return {}
        from database.user_db import get_user_broker_credentials
        return get_user_broker_credentials(username, name)

    db_creds = _fetch_creds(broker_name)
    redirect_url = db_creds.get("redirect_url") or os.getenv("REDIRECT_URL")

    # If no broker name is passed, extract from redirect_url
    if not broker_name:
        if redirect_url:
            match = re.search(r"/([^/]+)/callback$", redirect_url)
            broker_name = match.group(1) if match else None
            if broker_name:
                # Now that we know the broker, fetch ITS credentials
                # specifically (the redirect_url-only lookup above had no
                # broker_name yet, so db_creds is still empty at this point).
                db_creds = _fetch_creds(broker_name)
                redirect_url = db_creds.get("redirect_url") or redirect_url

    if not broker_name:
        broker_name = "dhan_sandbox"

    # Dynamically format the redirect_url for the selected broker
    if not redirect_url or f"/{broker_name}/callback" not in redirect_url:
        host_server = os.getenv("HOST_SERVER") or "http://127.0.0.1:5001"
        host_server = host_server.rstrip("/")
        redirect_url = f"{host_server}/{broker_name}/callback"

    broker_api_key = None
    if username:
        broker_api_key = db_creds.get("broker_api_key") or os.getenv("BROKER_API_KEY")

    if username:
        return jsonify(
            {
                "status": "success",
                "broker_name": broker_name,
                "broker_api_key": broker_api_key,
                "redirect_url": redirect_url,
            }
        )

    # Unauthenticated: return broker name only so the login button is visible
    return jsonify(
        {
            "status": "success",
            "broker_name": broker_name,
            "broker_api_key": None,
            "redirect_url": redirect_url,
        }
    )


@auth_bp.route("/broker-status", methods=["GET"])
def get_broker_status():
    """Report the ACTUAL currently-connected broker and whether its stored
    token is still valid right now (live check against the broker's own
    API), rather than the client's cached/stale session value.

    This platform stores exactly one broker session per user (see
    database/auth_db.py Auth table - username is unique, one row per user),
    so "currently connected broker" is unambiguous: whatever is on that row.
    There is no concept of multiple simultaneously-connected brokers.
    """
    username = session.get("user")
    if not username:
        return jsonify({"status": "success", "connected": False, "broker": None})

    from database.auth_db import get_auth_token_dbquery

    auth_obj = get_auth_token_dbquery(username)
    if not auth_obj or auth_obj.is_revoked:
        return jsonify({"status": "success", "connected": False, "broker": None})

    broker = auth_obj.broker
    is_valid, reason = _check_broker_token_valid(username, auth_obj)

    return jsonify(
        {
            "status": "success",
            "connected": True,
            "broker": broker,
            "token_valid": is_valid,
            "issue": None if is_valid else reason,
        }
    )


def _check_broker_token_valid(username, auth_obj):
    """Live-validate a stored broker token against the broker's own API.

    Shares the same validation approach as _try_resume_broker_session (a
    lightweight funds-API call), factored out so it can be used purely as
    a read-only health check without the side effect of re-establishing
    the login session.

    Returns (is_valid: bool, reason: str | None).
    """
    from database.auth_db import decrypt_token

    try:
        auth_token = decrypt_token(auth_obj.auth)
        if not auth_token:
            return False, "stored token could not be decrypted"

        broker = auth_obj.broker
        import importlib

        broker_module = importlib.import_module(f"broker.{broker}.api.funds")
        if hasattr(broker_module, "test_auth_token"):
            is_valid, error_message = broker_module.test_auth_token(auth_token)
            if not is_valid:
                return False, error_message or "token rejected by broker"

        funds_data = broker_module.get_margin_data(auth_token)
        failure_reason = _broker_validation_failure_reason(funds_data)
        if failure_reason:
            return False, failure_reason
        if not funds_data:
            return False, "empty funds response"

        return True, None
    except Exception as e:
        logger.info(f"Broker token health check failed for {username}: {e}")
        return False, str(e)


@auth_bp.route("/check-setup", methods=["GET"])
def check_setup_required():
    """Check if initial setup is required (no users exist)."""
    needs_setup = find_user_by_username() is None
    return jsonify({"status": "success", "needs_setup": needs_setup})


@auth_bp.route("/healthz", methods=["GET"])
@limiter.exempt
def healthz():
    """Container liveness probe. Deliberately does NO work.

    The Docker healthcheck used to call /check-setup, which runs a DB query
    on the SAME single gunicorn worker (--workers 1 is required for
    SocketIO) that serves every other request. When a runaway client
    saturated that worker -- as a render->fetch loop on the Strategy Builder
    did, firing thousands of /optiongreeks calls -- the probe could not
    answer inside its 10s timeout, Docker marked the container unhealthy,
    and nginx returned 504 for every route including the dashboard.

    This endpoint touches no database, no broker, and no session, so it
    answers as long as the worker is alive at all. It is also exempt from
    rate limiting: a liveness probe must never be throttled into failing,
    which would restart a perfectly healthy container.

    It reports LIVENESS, not readiness -- "is the process up", not "is the
    platform fully functional". That is the correct semantic for a
    restart-triggering healthcheck; restarting on a broker outage would
    make an external problem worse.
    """
    return jsonify({"status": "ok"}), 200


@auth_bp.route("/register", methods=["POST"])
@limiter.limit(REGISTRATION_RATE_LIMIT)
def register():
    """Self-service signup for the multi-tenant SaaS deployment.

    Distinct from /setup: this never creates an admin (is_admin is always
    False) and is reachable at any time (not gated on "zero users exist").
    Requires initial platform setup to already be complete -- if no admin
    account exists yet, this is a fresh install and /setup is the correct
    entry point.
    """
    if find_user_by_username() is None:
        return jsonify(
            {
                "status": "error",
                "message": "This install has not completed initial setup yet.",
                "redirect": "/setup",
            }
        ), 400

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or ""

    if not username or not email or not password:
        return jsonify(
            {"status": "error", "message": "Username, email and password are required"}
        ), 400
    if password != confirm_password:
        return jsonify({"status": "error", "message": "Passwords do not match"}), 400

    from utils.auth_utils import validate_password_strength

    is_valid, error_message = validate_password_strength(password)
    if not is_valid:
        return jsonify({"status": "error", "message": error_message}), 400

    user = add_user(
        username, email, password, is_admin=False,
        status="PENDING_VERIFICATION", email_verified=False,
    )
    if user is None:
        return jsonify(
            {"status": "error", "message": "Username or email already exists"}
        ), 409

    smtp_settings = get_smtp_settings()
    if not smtp_settings or not smtp_settings.get("smtp_server"):
        logger.warning(f"Registered {username} but SMTP is not configured - cannot send verification email")
        return jsonify(
            {
                "status": "success",
                "email_sent": False,
                "message": (
                    "Account created, but this platform hasn't set up email yet, so we "
                    "couldn't send a verification link. Please contact the site administrator "
                    "to verify your account."
                ),
            }
        ), 201

    token = create_email_verification_token(username)
    verify_link = url_for("auth.verify_email_link", token=token, _external=True)
    result = send_verification_email(email, verify_link, username)
    if not result.get("success"):
        logger.exception(f"Failed to send verification email to {email}: {result.get('message')}")
        return jsonify(
            {
                "status": "success",
                "email_sent": False,
                "message": (
                    "Account created, but sending the verification email failed. Please "
                    "contact the site administrator to verify your account."
                ),
            }
        ), 201

    return jsonify(
        {
            "status": "success",
            "email_sent": True,
            "message": "Account created. Please check your email to verify your account.",
        }
    ), 201


@auth_bp.route("/verify-email", methods=["POST"])
def verify_email_api():
    """Consume a verification token from the React verify-email page."""
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token:
        return jsonify({"status": "error", "message": "Token is required"}), 400

    user = consume_email_verification_token(token)
    if user is None:
        return jsonify(
            {"status": "error", "message": "Invalid or expired verification link."}
        ), 400

    logger.info(f"Email verified for user: {user.username}")
    return jsonify({"status": "success", "message": "Email verified. You can now log in."})


@auth_bp.route("/verify-email/<token>", methods=["GET"])
def verify_email_link(token):
    """Email-link landing route -- redirects to the React verify page which
    calls POST /auth/verify-email with the token from the URL."""
    return redirect(f"/verify-email?token={token}")


def _broker_validation_failure_reason(funds_data):
    """Return a reason when a broker funds response represents auth/API failure."""
    if not funds_data:
        return "empty funds response"

    if not isinstance(funds_data, dict):
        return None

    status = str(funds_data.get("status", "")).lower()
    if status in {"error", "failed", "failure"}:
        return str(
            funds_data.get("message")
            or funds_data.get("errorMessage")
            or funds_data.get("errors")
            or funds_data.get("error")
            or "broker returned error status"
        )

    for key in ("errorType", "errorCode", "errorMessage", "errors", "error"):
        value = funds_data.get(key)
        if value:
            return str(value)

    return None


def _try_resume_broker_session(username):
    """
    Check if the user has an existing valid broker session in the DB.
    If so, validate it with a lightweight funds API call and resume
    the session without requiring broker OAuth re-authentication.

    Returns a JSON response if session was resumed, or None to proceed
    with normal broker OAuth flow.
    """
    from database.auth_db import Auth, decrypt_token, get_auth_token_dbquery, get_broker_session

    try:
        auth_obj = get_auth_token_dbquery(username)
        if not auth_obj or auth_obj.is_revoked:
            # The data broker's own Auth row is invalid (daily 3AM IST
            # rollover, logout, or session expiry all revoke it) - but that
            # does NOT mean the broker itself is disconnected. If the same
            # broker still has a valid AuthBrokerSession token (multi-broker
            # support persists these independently, and they survive logout/
            # app-session-expiry - only an explicit Broker Management
            # disconnect touches them), silently restore the data broker
            # from that token instead of forcing a fresh OAuth login. This
            # is what lets 10 connected brokers survive a laptop
            # shutdown/reopen without the user re-authenticating each one.
            raw_auth_row = Auth.query.filter_by(name=username).first()
            preserved_broker = raw_auth_row.broker if raw_auth_row else None
            if not preserved_broker:
                from database.auth_db import list_broker_sessions
                live_sessions = [s for s in list_broker_sessions(username) if not s.get("is_revoked")]
                if live_sessions:
                    preserved_broker = live_sessions[0]["broker"]
            if not preserved_broker:
                return None

            fallback_session = get_broker_session(username, preserved_broker)
            if not fallback_session:
                return None

            auth_token, feed_token, user_id = fallback_session
            broker = preserved_broker
            logger.info(
                f"Data broker Auth row invalid for {username} - restoring from "
                f"{broker}'s own AuthBrokerSession token instead of requiring OAuth"
            )
        else:
            # Decrypt the stored broker token
            auth_token = decrypt_token(auth_obj.auth)
            if not auth_token:
                return None

            broker = auth_obj.broker
            feed_token = decrypt_token(auth_obj.feed_token) if auth_obj.feed_token else None
            user_id = auth_obj.user_id

        # Validate token with a lightweight broker API call (funds). Every
        # broker's funds/data module reads its OWN userid/client_id via
        # os.getenv("BROKER_API_KEY") (patched in app.py to resolve
        # dynamically) - not just the auth_token passed in explicitly. At
        # this point in the login flow session["broker"] may not be set
        # yet (only handle_auth_success sets it, further below), so without
        # forcing resolution here the ambient fallback would try to use
        # the CURRENT (possibly invalid/stale) session/Auth state instead
        # of the broker actually being validated - silently breaking the
        # AuthBrokerSession fallback above. Wrapping in
        # broker_credential_context guarantees this validation call always
        # resolves the correct broker's own credentials, matching how
        # every other multi-broker code path (order placement, fan-out)
        # already resolves credentials.
        import importlib

        from utils.broker_context import broker_credential_context

        try:
            # Cap broker-token validation at a few seconds so login never
            # blocks on an unreachable broker. These are live HTTP calls to
            # the broker's API and inherit the shared httpx client's 120s
            # timeout, so a slow/unreachable broker (market closed, network
            # blip, broker outage) would otherwise hang the whole login
            # request for up to two minutes ("Sign in spins forever").
            #
            # We use eventlet.Timeout under the production eventlet worker
            # (ThreadPoolExecutor is known to hang with eventlet here -- see
            # services/options_multiorder_service.py). eventlet.Timeout
            # interrupts the blocking green-threaded socket call cleanly. On
            # the dev server (no eventlet monkey-patch) we fall back to a
            # plain call -- dev isn't latency-critical and this path is only
            # hit when resuming a real stored broker session. On timeout we
            # skip the resume and fall through to normal login (user
            # reconnects their broker from /broker).
            _timeout_ctx = _broker_validation_timeout(8)
            with _timeout_ctx:
                with broker_credential_context(username, broker):
                    broker_module = importlib.import_module(f"broker.{broker}.api.funds")
                    if hasattr(broker_module, "test_auth_token"):
                        is_valid, error_message = broker_module.test_auth_token(auth_token)
                        if not is_valid:
                            logger.info(
                                f"Broker token expired or invalid for {username}: {error_message}"
                            )
                            return None
                    funds_data = broker_module.get_margin_data(auth_token)
            failure_reason = _broker_validation_failure_reason(funds_data)
            if failure_reason:
                logger.info(
                    f"Broker token expired or invalid for {username}: {failure_reason}"
                )
                return None
            # get_margin_data returns {} on failure (doesn't raise) — treat empty as invalid
            if not funds_data:
                logger.info(f"Broker token expired or invalid for {username} (empty funds response)")
                return None
        except _BrokerValidationTimeout:
            logger.warning(
                f"Broker token validation timed out for {username} (broker {broker} "
                "unreachable) - skipping resume, proceeding to normal login"
            )
            return None
        except Exception as e:
            logger.info(f"Broker token validation failed for {username}: {e}")
            return None

        # Token is valid — resume the session via handle_auth_success
        logger.info(f"Resuming existing broker session for {username} (broker: {broker})")

        from utils.auth_utils import handle_auth_success
        # Call handle_auth_success for its side effects (session setup, DB upsert,
        # master contract loading) but ignore its response format — the login
        # endpoint must always return JSON for the React frontend's fetch() call.
        try:
            handle_auth_success(
                auth_token=auth_token,
                user_session_key=username,
                broker=broker,
                feed_token=feed_token,
                user_id=user_id,
            )
        except Exception as e:
            logger.error(f"handle_auth_success failed during resume: {e}", exc_info=True)
            # Clear partial session state and fall through to OAuth
            session.pop("logged_in", None)
            session.pop("broker", None)
            session.pop("session_id", None)
            return None

        logger.info(f"Session resume complete for {username}, redirecting to dashboard")
        return jsonify({
            "status": "success",
            "message": "Broker session resumed",
            "redirect": "/dashboard",
            "broker": broker,
        }), 200

    except Exception as e:
        logger.error(f"Error trying to resume broker session: {e}", exc_info=True)
        return None


@auth_bp.route("/login", methods=["GET", "POST"])
# CSRF exemption for this view is applied in app.py via app.csrf.exempt(login)
# -- see the comment on the extensions import above for why it can't be a
# decorator here.
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def login():
    # Handle POST requests first (for React SPA / AJAX login)
    if request.method == "POST":
        logger.info(f"[LOGIN] POST from IP={get_real_ip()}, UA={request.headers.get('User-Agent', '')[:80]}")
        logger.info(f"[LOGIN] Session state: user={session.get('user')}, logged_in={session.get('logged_in')}, broker={session.get('broker')}")

        # Check if setup is required
        if find_user_by_username() is None:
            logger.info("[LOGIN] No users exist, redirecting to setup")
            return jsonify(
                {
                    "status": "error",
                    "message": "Please complete initial setup first.",
                    "redirect": "/setup",
                }
            ), 400

        # Check if already logged in (check logged_in first — it means
        # broker auth is complete; "user" alone means only password was done)
        if session.get("logged_in"):
            if is_session_valid():
                logger.info("[LOGIN] Already fully logged in, redirecting to /dashboard")
                return jsonify(
                    {"status": "success", "message": "Already logged in", "redirect": "/dashboard"}
                ), 200

            logger.info("[LOGIN] Existing session expired; clearing before password login")
            revoke_user_tokens()
            session.clear()

        if "user" in session:
            logger.info("[LOGIN] User in session, redirecting to /dashboard")
            return jsonify(
                {"status": "success", "message": "Already logged in", "redirect": "/dashboard"}
            ), 200

        if request.is_json or (request.content_type and "application/json" in request.content_type):
            json_data = request.get_json(silent=True) or {}
            login_identifier = json_data.get("username", "")
            password = json_data.get("password", "")
        else:
            login_identifier = request.form.get("username", "") or request.args.get("username", "")
            password = request.form.get("password", "") or request.args.get("password", "")

        if not login_identifier or not password:
            return jsonify({"status": "error", "message": "Username and password are required."}), 400

        ip = get_real_ip()
        ua = request.headers.get("User-Agent", "")

        # Accept username OR email in the login field. Resolve to the actual
        # username up front since authenticate_user/session["user"]/every
        # downstream table key on the username string, not email.
        identified_user = find_user_by_login_identifier(login_identifier)
        username = identified_user.username if identified_user else login_identifier

        # Suspended accounts are rejected before the password check even
        # runs, so a suspended user learns nothing about whether their
        # password is still correct.
        if identified_user is not None and identified_user.status == "SUSPENDED":
            from database.auth_db import log_login_attempt
            log_login_attempt(username, ip, ua, status="failed", login_type="password",
                              failure_reason="account_suspended")
            return jsonify({"status": "error", "message": "This account has been suspended."}), 403

        if authenticate_user(username, password):
            logger.info(f"[LOGIN] Password auth success for: {username}")

            # If the user has 2FA enabled for login, defer setting session["user"]
            # until TOTP is verified. This is the gate that prevents an attacker
            # with only the password from progressing to broker login. We park
            # the username on a transient key that POST /auth/login/totp will
            # consume on success, and clear on failure or timeout.
            # Reuses the row already fetched by find_user_by_login_identifier
            # above rather than a second query -- same user, since
            # authenticate_user() only just succeeded against `username`.
            user = identified_user or find_user_by_exact_username(username)

            if user is not None and user.status == "PENDING_VERIFICATION":
                return jsonify(
                    {"status": "error", "message": "Please verify your email before logging in."}
                ), 403

            if user is not None and user.is_totp_required_for("login"):
                session.pop("user", None)
                session["pending_totp_user"] = username
                session["pending_totp_started_at"] = _utcnow_iso()
                logger.info(f"[LOGIN] TOTP required for: {username}; awaiting second factor")
                return jsonify(
                    {"status": "totp_required", "message": "Enter the 6-digit code from your authenticator app."}
                ), 200

            session["user"] = username  # Set the username in the session
            session["logged_in"] = True
            from utils.session import set_session_login_time
            set_session_login_time()
            _stamp_last_login(user)

            # Multi-device session tracking & new device security email alert
            import secrets
            if "session_id" not in session:
                session["session_id"] = secrets.token_hex(32)

            session_id = session["session_id"]
            device_info_str = request.headers.get("User-Agent", "")[:500]
            ip_str = get_real_ip()

            from database.auth_db import register_session, is_known_device
            _is_new_device = not is_known_device(username, device_info_str, ip_str)

            register_session(
                username=username,
                session_id=session_id,
                device_info=device_info_str,
                ip_address=ip_str,
                broker=session.get("broker"),
            )

            if _is_new_device:
                try:
                    # find_user_by_login_identifier is already imported at
                    # module level (line ~29) -- a local re-import of the
                    # SAME name here made Python treat it as a local
                    # variable for this entire function, which raised
                    # UnboundLocalError at line 703's earlier use, on every
                    # single login attempt, before the local import
                    # statement ever executed.
                    from utils.email_utils import send_new_device_login_email
                    import datetime

                    user_obj = find_user_by_login_identifier(username)
                    if user_obj and user_obj.email:
                        login_time_str = datetime.datetime.now().strftime("%d %b %Y, %H:%M IST")
                        send_new_device_login_email(
                            recipient_email=user_obj.email,
                            user_name=user_obj.username or username,
                            device_info=device_info_str,
                            ip_address=ip_str,
                            login_time_str=login_time_str,
                        )
                        logger.info(f"[SECURITY] New device email sent to {user_obj.email} for {username}")
                except Exception as email_err:
                    logger.warning(f"Could not send new device login email for {username}: {email_err}")

            # Platform-fee gate: the user has proven their identity so they
            # get a session (the /payments subscription endpoints need one to
            # take their payment), but they are routed to /subscribe instead
            # of the dashboard. Server-side enforcement lives in
            # utils/session.py::check_session_validity, which blocks every
            # data endpoint except /auth/* and /payments/* for an
            # unsubscribed non-admin -- so the session alone grants no
            # product access.
            if SUBSCRIPTION_GATE_ENABLED and user is not None and not user.is_admin:
                if get_active_platform_subscription(username) is None:
                    logger.info(f"[LOGIN] No active subscription for: {username}")
                    from database.auth_db import log_login_attempt
                    log_login_attempt(username, ip, ua, status="success", login_type="password")
                    return jsonify(
                        {
                            "status": "subscription_required",
                            "message": "An active subscription is required to continue.",
                            "redirect": "/subscribe",
                        }
                    ), 200

            # Try to resume existing broker session (skip OAuth if token still valid)
            resumed = _try_resume_broker_session(username)
            logger.info(f"[LOGIN] Resume result: {resumed is not None}, type={type(resumed).__name__ if resumed else 'None'}")
            if resumed:
                logger.info("[LOGIN] Returning resume response to frontend")
                from database.auth_db import log_login_attempt, record_activity
                log_login_attempt(username, ip, ua, status="success",
                                  login_type="resume", broker=session.get("broker"))
                record_activity(username, "account", "Account", "Logged in successfully")
                return resumed

            # No valid broker session — redirect directly to /dashboard
            logger.info("[LOGIN] No valid broker session, redirecting to /dashboard")
            from database.auth_db import log_login_attempt, record_activity
            log_login_attempt(username, ip, ua, status="success", login_type="password")
            record_activity(username, "account", "Account", "Logged in successfully")
            return jsonify({"status": "success", "redirect": "/dashboard"}), 200
        else:
            from database.auth_db import log_login_attempt
            log_login_attempt(username, get_real_ip(),
                              request.headers.get("User-Agent", ""),
                              status="failed", login_type="password",
                              failure_reason="invalid_credentials")
            return jsonify({"status": "error", "message": "Invalid credentials"}), 401

    # Handle GET requests - redirect to React frontend
    if find_user_by_username() is None:
        return redirect("/setup")

    if session.get("logged_in"):
        if is_session_valid():
            return redirect("/dashboard")

        revoke_user_tokens()
        session.clear()

    if "user" in session:
        return redirect("/broker")

    return redirect("/login")


@auth_bp.route("/login/totp", methods=["POST"])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def login_totp():
    """Second factor for the dashboard login flow.

    Only reachable after a successful password step on a user that has
    ``totp_required_for_login`` enabled. The password step deliberately
    leaves ``session["user"]`` unset and parks the username on
    ``session["pending_totp_user"]`` so an attacker with only the
    password cannot progress.

    On success: sets ``session["user"]`` and stamps
    ``session["totp_verified_at"]`` so downstream code (notably the
    Phase 2 OAuth ``/oauth/authorize`` endpoint) can require a fresh
    TOTP.
    """
    if not _pending_totp_is_fresh():
        _clear_pending_totp()
        return jsonify(
            {
                "status": "error",
                "message": "Login session expired. Please sign in again.",
                "redirect": "/login",
            }
        ), 401

    pending_username = session.get("pending_totp_user")
    if not pending_username:
        return jsonify({"status": "error", "message": "No pending login. Sign in first."}), 401

    data = request.get_json(silent=True) or {}
    totp_code = (data.get("totp_code") or request.form.get("totp_code") or "").strip()
    if not totp_code:
        return jsonify({"status": "error", "message": "TOTP code is required."}), 400

    user = find_user_by_exact_username(pending_username)
    if user is None or not user.verify_totp(totp_code):
        from database.auth_db import log_login_attempt

        log_login_attempt(
            pending_username,
            get_real_ip(),
            request.headers.get("User-Agent", ""),
            status="failed",
            login_type="totp",
            failure_reason="invalid_totp",
        )
        # Don't clear the pending marker on a single bad code — let the
        # rate limiter handle brute force. The 5-min freshness window
        # caps total attempts anyway.
        return jsonify({"status": "error", "message": "Invalid TOTP code."}), 401

    # Promote the pending login to a real session.
    session["user"] = pending_username
    session["totp_verified_at"] = _utcnow_iso()
    session["logged_in"] = True
    from utils.session import set_session_login_time
    set_session_login_time()
    _clear_pending_totp()

    ip = get_real_ip()
    ua = request.headers.get("User-Agent", "")
    from database.auth_db import log_login_attempt

    # Platform-fee gate for the TOTP path -- same rule as the password path
    # (see login()). Without this, only the password step gated
    # subscriptions and the second factor promoted straight to the
    # dashboard; the gate must hold at every session-establishment point.
    if SUBSCRIPTION_GATE_ENABLED and user is not None and not user.is_admin:
        if get_active_platform_subscription(pending_username) is None:
            logger.info(f"[LOGIN/TOTP] No active subscription for: {pending_username}")
            log_login_attempt(pending_username, ip, ua, status="success", login_type="totp")
            return jsonify(
                {
                    "status": "subscription_required",
                    "message": "An active subscription is required to continue.",
                    "redirect": "/subscribe",
                }
            ), 200

    # Try resuming an existing broker session, same path as plain login.
    resumed = _try_resume_broker_session(pending_username)
    if resumed:
        log_login_attempt(
            pending_username, ip, ua, status="success",
            login_type="totp_resume", broker=session.get("broker"),
        )
        return resumed

    log_login_attempt(pending_username, ip, ua, status="success", login_type="totp")
    return jsonify({"status": "success", "redirect": "/dashboard"}), 200


@auth_bp.route("/2fa/status", methods=["GET"])
@check_session_validity
def two_factor_status():
    """Return the signed-in user's current 2FA configuration."""
    user = find_user_by_exact_username(session["user"])
    if user is None:
        return jsonify({"status": "error", "message": "User not found."}), 404
    return jsonify(
        {
            "status": "success",
            "totp_enabled": bool(user.totp_enabled),
            "totp_required_for_login": bool(user.totp_required_for_login),
            "totp_required_for_mcp": bool(user.totp_required_for_mcp),
            "totp_required_for_password_reset": bool(user.totp_required_for_password_reset),
            "totp_required_for_api_key": bool(user.totp_required_for_api_key),
            "last_totp_verified_at": session.get("totp_verified_at"),
        }
    )


@auth_bp.route("/2fa/configure", methods=["POST"])
@check_session_validity
def two_factor_configure():
    """Enable / disable 2FA and set per-purpose flags atomically.

    The user must verify a current TOTP code in the same request whether
    they are turning the master switch on or off — both transitions are
    sensitive enough to demand proof of TOTP-app access. If the master is
    off in the new state, every per-purpose flag is forced to False as
    well so the stored config is consistent.
    """
    data = request.get_json(silent=True) or {}
    totp_code = (data.get("totp_code") or "").strip()
    if not totp_code:
        return jsonify({"status": "error", "message": "TOTP code is required to change 2FA settings."}), 400

    user = find_user_by_exact_username(session["user"])
    if user is None:
        return jsonify({"status": "error", "message": "User not found."}), 404

    if not user.verify_totp(totp_code):
        return jsonify({"status": "error", "message": "Invalid TOTP code."}), 401

    enabled = bool(data.get("totp_enabled", False))
    # Per-purpose flags are interpreted only when the master is on. When
    # the master is off they are forced False to avoid stale-on-disk
    # configuration that would silently re-engage on the next enable.
    purpose_login = bool(data.get("totp_required_for_login", False)) if enabled else False
    purpose_mcp = bool(data.get("totp_required_for_mcp", False)) if enabled else False
    purpose_reset = bool(data.get("totp_required_for_password_reset", False)) if enabled else False
    purpose_api_key = bool(data.get("totp_required_for_api_key", False)) if enabled else False

    user.totp_enabled = enabled
    user.totp_required_for_login = purpose_login
    user.totp_required_for_mcp = purpose_mcp
    user.totp_required_for_password_reset = purpose_reset
    user.totp_required_for_api_key = purpose_api_key
    db_session.commit()

    # Stamp the session so any downstream "fresh TOTP" check considers
    # this verification recent. Useful in the same-page UX where a user
    # toggles 2FA and immediately uses an OAuth flow.
    session["totp_verified_at"] = _utcnow_iso()

    logger.info(
        f"[2FA] User {user.username} set enabled={enabled} "
        f"login={purpose_login} mcp={purpose_mcp} reset={purpose_reset} api_key={purpose_api_key}"
    )

    return jsonify(
        {
            "status": "success",
            "totp_enabled": enabled,
            "totp_required_for_login": purpose_login,
            "totp_required_for_mcp": purpose_mcp,
            "totp_required_for_password_reset": purpose_reset,
            "totp_required_for_api_key": purpose_api_key,
        }
    )


@auth_bp.route("/broker", methods=["GET", "POST"])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def broker_login():
    # A pending auth_error means the user just landed here after a FAILED
    # broker OAuth attempt (see handle_auth_failure). Skip the "already
    # logged in with a valid token" bounce-back below in that case - the
    # valid token still on file belongs to the PREVIOUS broker (e.g. BNR),
    # not the one that just failed (e.g. Zebu), so redirecting to /dashboard
    # here would silently swallow the failure and leave the user thinking
    # nothing happened.
    auth_error = request.args.get("auth_error")

    if session.get("logged_in") and not auth_error:
        # Only bounce to the dashboard when the stored broker token is still
        # valid. When it is revoked/expired (daily rollover, broker-side
        # revocation), this page is the canonical re-auth entry point --
        # unconditionally redirecting away left users stranded with no UI
        # path to reconnect (issue #1400).
        from database.auth_db import get_auth_token

        if get_auth_token(session.get("user")):
            return redirect("/dashboard")
        logger.info(
            f"Broker token invalid for {session.get('user')} - allowing re-authentication"
        )
    if request.method == "GET":
        if "user" not in session:
            return redirect("/login")

        # Redirect to React broker selection page, forwarding the error (if
        # any) so the UI can display why the previous attempt failed.
        if auth_error:
            from urllib.parse import urlencode

            return redirect(f"/broker?{urlencode({'auth_error': auth_error})}")
        return redirect("/broker")


@auth_bp.route("/reset-password", methods=["GET", "POST"])
@limiter.limit(RESET_RATE_LIMIT)  # Password reset rate limit
def reset_password():
    # GET requests are handled by React frontend - redirect there
    if request.method == "GET":
        return redirect("/reset-password")

    # Handle JSON requests from React frontend
    if request.is_json:
        data = request.get_json()
        step = data.get("step")
        email = data.get("email")
    else:
        # Fall back to form data for compatibility
        step = request.form.get("step")
        email = request.form.get("email")

    # Debug logging for CSRF issues
    logger.debug(f"Password reset step: {step}, Session: {session.keys()}")

    if step == "email":
        user = find_user_by_email(email)

        # Always show the same response to prevent user enumeration
        if user:
            session["reset_email"] = email

        # Return success regardless of whether email exists (prevents enumeration)
        return jsonify({"status": "success", "message": "Email verified"})

    elif step == "select_totp":
        session["reset_method"] = "totp"
        return jsonify({"status": "success", "method": "totp"})

    elif step == "select_email":
        user = find_user_by_email(email)

        # Per-user 2FA gate: when the account has password-reset 2FA enabled,
        # the email path is intentionally unavailable. Forces the TOTP route.
        # The check runs ONLY for known emails — for unknown emails we fall
        # through to the generic "email sent if account exists" response so
        # we don't leak whether the account exists.
        if user is not None and user.is_totp_required_for("password_reset"):
            return jsonify(
                {
                    "status": "error",
                    "message": "This account requires TOTP for password reset. "
                    "Please choose 'Authenticator app' instead.",
                }
            ), 400

        session["reset_method"] = "email"

        # Check if SMTP is configured
        smtp_settings = get_smtp_settings()
        if not smtp_settings or not smtp_settings.get("smtp_server"):
            return jsonify(
                {
                    "status": "error",
                    "message": "Email reset is not available. Please use TOTP authentication.",
                }
            ), 400

        if user:
            try:
                # Generate a secure token for the email reset
                token = secrets.token_urlsafe(32)
                session["reset_token"] = token
                session["reset_email"] = email

                # Create reset link
                reset_link = url_for("auth.reset_password_email", token=token, _external=True)
                send_password_reset_email(email, reset_link, user.username)
                logger.info(f"Password reset email sent to {email}")

            except Exception as e:
                logger.exception(f"Failed to send password reset email to {email}: {e}")
                return jsonify(
                    {
                        "status": "error",
                        "message": "Failed to send reset email. Please try TOTP authentication instead.",
                    }
                ), 500

        # Return success regardless of whether email exists (prevents enumeration)
        return jsonify({"status": "success", "message": "Reset email sent if account exists"})

    elif step == "totp":
        if request.is_json:
            totp_code = data.get("totp_code")
        else:
            totp_code = request.form.get("totp_code")

        user = find_user_by_email(email)

        if user and user.verify_totp(totp_code):
            # Generate a secure token for the password reset
            token = secrets.token_urlsafe(32)
            session["reset_token"] = token
            session["reset_email"] = email

            return jsonify({"status": "success", "message": "TOTP verified", "token": token})
        else:
            return jsonify(
                {"status": "error", "message": "Invalid TOTP code. Please try again."}
            ), 400

    elif step == "password":
        if request.is_json:
            token = data.get("token")
            password = data.get("password")
        else:
            token = request.form.get("token")
            password = request.form.get("password")

        # Verify token from session (handles both TOTP and email reset tokens)
        valid_token = token == session.get("reset_token") or token == session.get(
            "email_reset_token"
        )
        if not valid_token or email != session.get("reset_email"):
            return jsonify({"status": "error", "message": "Invalid or expired reset token."}), 400

        # Validate password strength
        from utils.auth_utils import validate_password_strength

        is_valid, error_message = validate_password_strength(password)
        if not is_valid:
            return jsonify({"status": "error", "message": error_message}), 400

        user = find_user_by_email(email)
        if user:
            user.set_password(password)
            db_session.commit()

            # Security: a password reset means we cannot trust any other
            # active session for this account. Kick every device — the
            # operator (or attacker) chose the reset path because they
            # could prove control of the email/TOTP, not because every
            # logged-in browser is theirs. Force re-login everywhere.
            from database.auth_db import clear_user_sessions
            clear_user_sessions(user.username)
            # room= scopes this to the user's OWN connected devices -- an
            # unscoped emit broadcasts to every connected client on the
            # platform, logging out every other user too (issue: any user's
            # password reset was force-logging out unrelated users once this
            # became a multi-tenant deployment).
            socketio.emit("force_logout", {
                "message": "Your password was reset. Please log in again with the new password.",
            }, room=f"user_{user.username}")

            # Clear reset session data for security
            session.pop("reset_token", None)
            session.pop("reset_email", None)
            session.pop("reset_method", None)
            session.pop("email_reset_token", None)

            return jsonify(
                {"status": "success", "message": "Your password has been reset successfully."}
            )
        else:
            return jsonify({"status": "error", "message": "Error resetting password."}), 400

    return jsonify({"status": "error", "message": "Invalid step"}), 400


@auth_bp.route("/reset-password-email/<token>", methods=["GET"])
def reset_password_email(token):
    """Handle password reset via email link - validates token and redirects to React"""
    try:
        # Validate the token format
        if not token or len(token) != 43:  # URL-safe base64 tokens are 43 chars for 32 bytes
            flash("Invalid reset link.", "error")
            return redirect("/reset-password?error=invalid_link")

        # Check if this token was issued (stored in session during email send)
        if token != session.get("reset_token"):
            flash("Invalid or expired reset link.", "error")
            return redirect("/reset-password?error=expired_link")

        # Get the email associated with this reset token
        reset_email = session.get("reset_email")
        if not reset_email:
            flash("Reset session expired. Please start again.", "error")
            return redirect("/reset-password?error=session_expired")

        # Set up session for password reset (email verification counts as verified)
        session["email_reset_token"] = token

        # Redirect to React password reset page with token and email in URL
        # React will read these and show the password form
        return redirect(f"/reset-password?token={token}&email={reset_email}&verified=true")

    except Exception as e:
        logger.exception(f"Error processing email reset link: {e}")
        flash("Invalid or expired reset link.", "error")
        return redirect("/reset-password?error=processing_error")


@auth_bp.route("/change", methods=["GET", "POST"])
@check_session_validity
def change_password():
    if "user" not in session:
        # If the user is not logged in, redirect to login page
        if request.is_json:
            return jsonify({"status": "error", "message": "Not authenticated"}), 401
        return redirect("/login")

    # GET requests redirect to React profile page
    if request.method == "GET":
        return redirect("/profile")

    # Handle POST requests - change password
    # Support both JSON and form data
    if request.is_json:
        data = request.get_json()
        old_password = data.get("old_password") or data.get("current_password")
        new_password = data.get("new_password")
        confirm_password = data.get("confirm_password", new_password)
    else:
        old_password = request.form.get("old_password") or request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password", new_password)

    username = session["user"]
    user = User.query.filter_by(username=username).first()

    if user and user.check_password(old_password):
        if new_password == confirm_password:
            # Validate password strength
            from utils.auth_utils import validate_password_strength

            is_valid, error_message = validate_password_strength(new_password)
            if not is_valid:
                return jsonify({"status": "error", "message": error_message}), 400

            user.set_password(new_password)
            db_session.commit()

            # Security: a password change is a strong signal of suspected
            # compromise (or routine rotation). Either way, every active
            # session for this account should be re-authenticated. Kick all
            # devices — including the current one — and let the user log
            # in again with the new password. This prevents an attacker
            # who already has a valid cookie from continuing to hold it.
            from database.auth_db import clear_user_sessions
            clear_user_sessions(username)
            # room= scopes this to the user's own devices -- see the
            # reset-password force_logout above for why an unscoped emit is
            # wrong on a multi-tenant deployment.
            socketio.emit("force_logout", {
                "message": "Your password was changed. Please log in again with the new password.",
            }, room=f"user_{username}")
            session.clear()

            return jsonify(
                {"status": "success", "message": "Your password has been changed successfully."}
            )
        else:
            return jsonify(
                {"status": "error", "message": "New password and confirm password do not match."}
            ), 400
    else:
        return jsonify({"status": "error", "message": "Current password is incorrect."}), 400


@auth_bp.route("/smtp-config", methods=["POST"])
@check_session_validity
def configure_smtp():
    if "user" not in session:
        # For AJAX requests, return JSON
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"status": "error", "message": "Not authenticated"}), 401
        flash("You must be logged in to configure SMTP settings.", "warning")
        return redirect(url_for("auth.login"))

    # SMTP is a platform-wide setting shared by every registration/password-
    # reset email this install sends -- admin-only. This route predates
    # multi-tenant self-registration (see /admin/api/smtp for the canonical
    # admin-panel path going forward); kept working for the existing Profile
    # SMTP tab, but now gated the same way.
    from blueprints.admin import _get_current_user_admin_status

    _current_username, is_admin = _get_current_user_admin_status()
    if not is_admin:
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify({"status": "error", "message": "Admin access required"}), 403
        flash("Admin access required to configure SMTP settings.", "error")
        return redirect(url_for("auth.change_password") + "?tab=smtp")

    try:
        smtp_server = request.form.get("smtp_server")
        smtp_port = int(request.form.get("smtp_port", 587))
        smtp_username = request.form.get("smtp_username")
        smtp_password = request.form.get("smtp_password")
        smtp_use_tls = request.form.get("smtp_use_tls") == "on"
        smtp_from_email = request.form.get("smtp_from_email")
        smtp_helo_hostname = request.form.get("smtp_helo_hostname")

        # Only update password if provided
        if smtp_password and smtp_password.strip():
            set_smtp_settings(
                smtp_server=smtp_server,
                smtp_port=smtp_port,
                smtp_username=smtp_username,
                smtp_password=smtp_password,
                smtp_use_tls=smtp_use_tls,
                smtp_from_email=smtp_from_email,
                smtp_helo_hostname=smtp_helo_hostname,
            )
        else:
            # Update without password change
            set_smtp_settings(
                smtp_server=smtp_server,
                smtp_port=smtp_port,
                smtp_username=smtp_username,
                smtp_use_tls=smtp_use_tls,
                smtp_from_email=smtp_from_email,
                smtp_helo_hostname=smtp_helo_hostname,
            )

        logger.info(f"SMTP settings updated by user: {session['user']}")

        # For AJAX requests, return JSON
        if (
            request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or request.is_json
            or "multipart/form-data" in request.content_type
        ):
            return jsonify({"status": "success", "message": "SMTP settings updated successfully"})

        flash("SMTP settings updated successfully.", "success")

    except Exception as e:
        logger.exception(f"Error updating SMTP settings: {str(e)}")
        # For AJAX requests, return JSON
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json:
            return jsonify(
                {"status": "error", "message": f"Error updating SMTP settings: {str(e)}"}
            ), 500
        flash(f"Error updating SMTP settings: {str(e)}", "error")

    return redirect(url_for("auth.change_password") + "?tab=smtp")


@auth_bp.route("/test-smtp", methods=["POST"])
@check_session_validity
def test_smtp():
    if "user" not in session:
        return jsonify(
            {"success": False, "message": "You must be logged in to test SMTP settings."}
        ), 401

    from blueprints.admin import _get_current_user_admin_status

    _current_username, is_admin = _get_current_user_admin_status()
    if not is_admin:
        return jsonify({"success": False, "message": "Admin access required"}), 403

    try:
        test_email = request.form.get("test_email")
        if not test_email:
            return jsonify(
                {"success": False, "message": "Please provide a test email address."}
            ), 400

        # Validate email format
        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, test_email):
            return jsonify(
                {"success": False, "message": "Please provide a valid email address."}
            ), 400

        # Send test email
        result = send_test_email(test_email, sender_name=session["user"])

        if result["success"]:
            logger.info(f"Test email sent successfully by user: {session['user']} to {test_email}")
            return jsonify({"success": True, "message": result["message"]}), 200
        else:
            logger.warning(f"Test email failed for user: {session['user']} - {result['message']}")
            return jsonify({"success": False, "message": result["message"]}), 400

    except Exception as e:
        error_msg = f"Error sending test email: {str(e)}"
        logger.exception(f"Test email error for user {session['user']}: {e}")
        return jsonify({"success": False, "message": error_msg}), 500


@auth_bp.route("/debug-smtp", methods=["POST"])
@check_session_validity
def debug_smtp():
    if "user" not in session:
        return jsonify(
            {"success": False, "message": "You must be logged in to debug SMTP settings."}
        ), 401

    from blueprints.admin import _get_current_user_admin_status

    _current_username, is_admin = _get_current_user_admin_status()
    if not is_admin:
        return jsonify({"success": False, "message": "Admin access required"}), 403

    try:
        logger.info(f"SMTP debug requested by user: {session['user']}")
        result = debug_smtp_connection()

        return jsonify(
            {
                "success": result["success"],
                "message": result["message"],
                "details": result["details"],
            }
        ), 200

    except Exception as e:
        error_msg = f"Error debugging SMTP: {str(e)}"
        logger.exception(f"SMTP debug error for user {session['user']}: {e}")
        return jsonify(
            {"success": False, "message": error_msg, "details": [f"Unexpected error: {e}"]}
        ), 500


@auth_bp.route("/session-status", methods=["GET"])
def get_session_status():
    """Return current session status for React SPA."""
    if "user" not in session:
        # Return 200 with authenticated: false instead of 401
        # This prevents unnecessary console errors in the browser
        return jsonify(
            {"status": "success", "message": "Not authenticated", "authenticated": False, "logged_in": False}
        ), 200

    # Resolve the current user's admin flag once so every response branch can
    # expose it. The frontend uses this to hide admin-only navigation/pages
    # from non-admins (the backend still enforces access with 403s -- this is
    # UX, not the security boundary).
    _current_user = find_user_by_exact_username(session.get("user"))
    is_admin = bool(_current_user and _current_user.is_admin)

    # Platform-fee state, so the SPA can route unsubscribed users to
    # /subscribe. Enforcement itself lives in utils/session.py's
    # check_session_validity (every data endpoint 403s until subscribed).
    subscription_required = bool(
        SUBSCRIPTION_GATE_ENABLED
        and _current_user is not None
        and not is_admin
        and get_active_platform_subscription(_current_user.username) is None
    )

    # Always resolve broker state from the DB — the session cookie cannot be the
    # gate because Device 2 (password-only login, resume skipped/timed-out) has
    # session["user"] and session["logged_in"] but NO session["broker"].
    # The Auth table is the single source of truth and is shared across all devices.
    #
    # Resolve the broker to REPORT from the Auth table row, not the session["broker"]
    # scalar — the scalar can go stale (e.g. set at OAuth-callback time, then never
    # updated/cleared if the user later starts-but-abandons connecting a *different*
    # broker), which otherwise makes this endpoint (and the header pill it feeds via
    # AuthSync → useAuthStore) report a broker name that doesn't match which broker's
    # token is actually live. Same fix as /auth/dashboard-data and mirrors
    # /auth/broker-status, which already derives from this row correctly.
    #
    # get_auth_token_dbquery returns None whenever the data broker's own Auth row is
    # revoked (daily ~3AM IST token expiry, or the user explicitly disconnected it) —
    # that used to fall straight through to the stale session["broker"] scalar below,
    # even when a DIFFERENT broker the user connected afterwards (via multi-broker
    # support, AuthBrokerSession) is the one actually live right now. That produced
    # exactly the top-bar-vs-Broker-Management mismatch from issue reports.
    from database.auth_db import (
        get_api_key_for_tradingview,
        get_auth_token,
        get_auth_token_dbquery,
        get_active_sessions,
        list_broker_sessions,
    )

    _auth_row = get_auth_token_dbquery(session.get("user"))
    if _auth_row and not _auth_row.is_revoked:
        reported_broker = _auth_row.broker
    else:
        _live_sessions = [
            s for s in list_broker_sessions(session.get("user")) if not s["is_revoked"]
        ]
        reported_broker = _live_sessions[0]["broker"] if _live_sessions else session.get("broker")

    # Backfill the session cookie so downstream cookie-reading paths (order placement,
    # WS auth, broker-status) work correctly on Device 2 without requiring a re-login.
    # Only backfill when the DB gives us a definitive broker name and the cookie is
    # missing it — never overwrite an explicitly set cookie value.
    if reported_broker and not session.get("broker"):
        session["broker"] = reported_broker
        session.modified = True
        logger.info(
            f"Session-status: backfilled session['broker']={reported_broker} "
            f"for user {session.get('user')} from DB (Device 2 / password-only login)"
        )

    active_count = len(get_active_sessions(session.get("user")))

    # Only check the live auth token when we know a broker was ever connected.
    # If reported_broker is None the user simply hasn't connected any broker yet —
    # that's not an "expired" state, just a fresh account.
    if reported_broker:
        from utils.broker_context import broker_credential_context
        with broker_credential_context(session.get("user"), reported_broker):
            auth_token = get_auth_token(session.get("user"))
        if auth_token is None:
            # The BROKER token is gone (daily rollover / revocation) but the
            # APP session is still valid. Do NOT clear or downgrade the session
            # here: `logged_in` doubles as the app-session flag in
            # utils/session.is_session_valid(), so popping it makes every
            # @check_session_validity route (including /auth/dashboard-data)
            # hard-logout the user before the reconnect UI can render (issue #1400).
            # Keep the session intact and just flag the state; /auth/dashboard-data
            # returns BROKER_SESSION_EXPIRED and the dashboard renders the Reconnect
            # Broker action, while /auth/broker admits the user for re-authentication.
            logger.info(
                f"Session status: broker token invalid for user {session.get('user')} - "
                "broker reconnect required"
            )
            return jsonify(
                {
                    "status": "success",
                    "authenticated": True,
                    "logged_in": True,
                    "user": session.get("user"),
                    "is_admin": is_admin,
                    "subscription_required": subscription_required,
                    "broker": reported_broker,
                    "broker_session_expired": True,
                    "active_sessions": active_count,
                }
            ), 200

    # Get API key for the user — auto-generate one if missing so the
    # WebSocket/REST data feed works without a separate /apikey step.
    # Previously only returned for sessions that had session["broker"] in the cookie,
    # which blocked Device 2's WS data feed even when the broker IS connected.
    api_key = get_api_key_for_tradingview(session.get("user"))
    if not api_key:
        try:
            import secrets as _secrets
            from database.auth_db import upsert_api_key
            auto_key = _secrets.token_hex(32)
            if upsert_api_key(session.get("user"), auto_key):
                api_key = auto_key
                logger.info(
                    f"Auto-generated platform API key for user {session.get('user')} "
                    "via session-status"
                )
        except Exception as _e:
            logger.warning(f"Failed to auto-generate API key via session-status: {_e}")

    return jsonify(
        {
            "status": "success",
            "authenticated": True,
            "logged_in": session.get("logged_in", False),
            "user": session.get("user"),
            "is_admin": is_admin,
            "subscription_required": subscription_required,
            "broker": reported_broker,
            "api_key": api_key,
            "active_sessions": active_count,
        }
    )


@auth_bp.route("/active-sessions", methods=["GET"])
@check_session_validity
def active_sessions():
    """Return the list of active sessions for the current user."""
    if "user" not in session:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401

    from database.auth_db import get_active_sessions
    sessions = get_active_sessions(session["user"])
    current_session_id = session.get("session_id")

    return jsonify({
        "status": "success",
        "count": len(sessions),
        "current_session_id": current_session_id,
        "sessions": sessions,
    })


@auth_bp.route("/active-sessions/<session_id>", methods=["DELETE"])
@check_session_validity
def revoke_session(session_id):
    """Revoke ONE specific session (log out that device only).

    Deliberately does NOT call upsert_auth(revoke=True) or touch the
    broker token the way logout() does -- another device may still be
    actively trading on that same broker session, and this endpoint's
    whole point is to end ONE device's app session without disturbing
    the others.
    """
    username = session.get("user")
    if not username:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401

    from database.auth_db import get_active_sessions, remove_session

    remove_session(session_id)

    # room= scopes this to the ONE revoked device -- joined on connect,
    # see app.py's join_room(f"session_{session_id}").
    socketio.emit(
        "force_logout",
        {"message": "This device was logged out remotely."},
        room=f"session_{session_id}",
    )

    active = get_active_sessions(username)
    emit_to_user(
        "active_sessions_update",
        {"count": len(active), "sessions": active},
        username,
    )

    return jsonify({"status": "success", "sessions": active})


@auth_bp.route("/active-sessions/logout-others", methods=["POST"])
@check_session_validity
def logout_other_sessions():
    """Revoke every session for this user EXCEPT the one making this
    request. Same broker-token-preserving reasoning as revoke_session."""
    username = session.get("user")
    current_session_id = session.get("session_id")
    if not username:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401

    from database.auth_db import ActiveSession
    from database.auth_db import db_session as auth_db_session
    from database.auth_db import get_active_sessions

    others = ActiveSession.query.filter(
        ActiveSession.username == username,
        ActiveSession.session_id != current_session_id,
    ).all()

    for other_sess in others:
        socketio.emit(
            "force_logout",
            {
                "message": "You were logged out (another device requested "
                "'log out all other devices')."
            },
            room=f"session_{other_sess.session_id}",
        )
        auth_db_session.delete(other_sess)
    auth_db_session.commit()

    active = get_active_sessions(username)
    emit_to_user(
        "active_sessions_update",
        {"count": len(active), "sessions": active},
        username,
    )

    return jsonify({"status": "success", "sessions": active})


@auth_bp.route("/app-info", methods=["GET"])
def get_app_info():
    """Return app information including version for React SPA."""
    from utils.version import get_version

    return jsonify({"status": "success", "version": get_version(), "name": "Max Algos"})


@auth_bp.route("/analyzer-mode", methods=["GET"])
@check_session_validity
def get_analyzer_mode_status():
    """Return current analyzer mode status for React SPA."""
    if "user" not in session:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401

    try:
        from database.settings_db import get_analyze_mode

        current_mode = get_analyze_mode()

        return jsonify(
            {
                "status": "success",
                "data": {
                    "mode": "analyze" if current_mode else "live",
                    "analyze_mode": current_mode,
                },
            }
        )
    except Exception as e:
        logger.exception(f"Error getting analyzer mode: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@auth_bp.route("/analyzer-toggle", methods=["POST"])
@check_session_validity
def toggle_analyzer_mode_session():
    """Toggle analyzer mode for React SPA using session authentication."""
    if "user" not in session:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401

    if not session.get("logged_in"):
        return jsonify({"status": "error", "message": "Broker not connected"}), 401

    try:
        from database.settings_db import get_analyze_mode, set_analyze_mode

        # Get current mode and toggle it
        current_mode = get_analyze_mode()
        new_mode = not current_mode

        # Set the new mode
        set_analyze_mode(new_mode)

        # Start/stop execution engine and squareoff scheduler based on mode
        from sandbox.execution_thread import start_execution_engine, stop_execution_engine
        from sandbox.squareoff_thread import start_squareoff_scheduler, stop_squareoff_scheduler

        if new_mode:
            # Analyzer mode ON - start both threads
            start_execution_engine()
            start_squareoff_scheduler()

            # Run catch-up settlement for any missed settlements while app was stopped
            from sandbox.position_manager import catchup_missed_settlements

            try:
                catchup_missed_settlements()
                logger.info("Catch-up settlement check completed")
            except Exception as e:
                logger.exception(f"Error in catch-up settlement: {e}")

            logger.info("Analyzer mode enabled - Execution engine and square-off scheduler started")
        else:
            # Analyzer mode OFF - stop both threads
            stop_execution_engine()
            stop_squareoff_scheduler()
            logger.info(
                "Analyzer mode disabled - Execution engine and square-off scheduler stopped"
            )

        return jsonify(
            {
                "status": "success",
                "data": {
                    "mode": "analyze" if new_mode else "live",
                    "analyze_mode": new_mode,
                    "message": f"Switched to {'Analyze' if new_mode else 'Live'} mode",
                },
            }
        )

    except Exception as e:
        logger.exception(f"Error toggling analyzer mode: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@auth_bp.route("/dashboard-data", methods=["GET"])
@check_session_validity
def get_dashboard_data():
    """Return dashboard funds data using session authentication for React SPA."""
    if "user" not in session:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401

    if not session.get("logged_in"):
        # App session valid, broker not connected (fresh login or downgraded
        # by session-status after a token rollover) -- the right CTA is the
        # broker reconnect flow, not /login (issue #1400).
        return jsonify(
            {
                "status": "error",
                "code": "BROKER_SESSION_EXPIRED",
                "message": "Broker not connected - please connect your broker",
            }
        ), 401

    login_username = session["user"]

    try:
        from database.auth_db import (
            get_api_key_for_tradingview,
            get_auth_token,
            get_auth_token_dbquery,
        )
        from database.settings_db import get_analyze_mode
        from services.funds_service import get_funds

        # Resolve the broker from the Auth table row -- the single source of
        # truth for "which broker is currently connected" (mirrors
        # /auth/broker-status, which already does this correctly). Do NOT
        # trust session["broker"]: it's a scalar set at OAuth-callback time
        # and never reliably cleared when a connect attempt is started but
        # abandoned (e.g. clicking "Connect" on a broker row navigates to
        # /broker?broker=X without completing OAuth) -- if a stale value
        # from an earlier incomplete/different broker lingers, using it here
        # sends a BNR/Angel/etc token to a mismatched broker's API (e.g.
        # Zebu), which that broker rejects, producing a confusing
        # "session expired" even though the real Auth row is still valid.
        auth_row = get_auth_token_dbquery(login_username)
        broker = auth_row.broker if auth_row and not auth_row.is_revoked else None

        if not broker:
            return jsonify(
                {
                    "status": "error",
                    "code": "BROKER_SESSION_EXPIRED",
                    "message": "Broker not connected - please connect your broker",
                }
            ), 401

        AUTH_TOKEN = get_auth_token(login_username)

        if AUTH_TOKEN is None:
            # Diagnostic: we already confirmed auth_row exists and is not
            # revoked (broker was resolved from it above), so AUTH_TOKEN
            # being None here specifically means decrypt_token() failed --
            # log it explicitly rather than presenting an identical-looking
            # "session expired" for a completely different failure mode.
            logger.warning(
                f"BROKER_SESSION_EXPIRED for {login_username}: Auth row exists "
                f"(broker={auth_row.broker}) and is not revoked, but decrypt_token() "
                f"returned None/empty -- likely a decrypt failure (e.g. FERNET_SALT "
                f"rotated), not an actual broker expiry"
            )

            # The APP session is still valid -- it is the BROKER token that is
            # revoked/expired. The machine-readable code lets the dashboard
            # point the user at /broker (reconnect) instead of /login, which
            # would just bounce them back (issue #1400).
            logger.warning(f"No auth token found for user {login_username}")
            return jsonify(
                {
                    "status": "error",
                    "code": "BROKER_SESSION_EXPIRED",
                    "message": "Broker session expired - please reconnect your broker",
                }
            ), 401

        # Check if in analyze mode
        if get_analyze_mode():
            api_key = get_api_key_for_tradingview(login_username)
            if api_key:
                success, response, status_code = get_funds(api_key=api_key)
            else:
                return jsonify(
                    {"status": "error", "message": "API key required for analyze mode"}
                ), 400
        else:
            success, response, status_code = get_funds(auth_token=AUTH_TOKEN, broker=broker)

        if not success:
            logger.error(f"Failed to get funds data: {response.get('message', 'Unknown error')}")
            return jsonify(
                {"status": "error", "message": response.get("message", "Failed to get funds")}
            ), status_code

        margin_data = response.get("data")
        if not margin_data or not isinstance(margin_data, dict):
            margin_data = {
                "availablecash": "0.00",
                "utiliseddebits": "0.00",
                "m2munrealized": "0.00",
                "m2mrealized": "0.00",
                "net": "0.00",
            }

        from database.auth_db import maybe_record_margin_alert, record_pnl_snapshot

        record_pnl_snapshot(
            login_username,
            margin_data.get("m2munrealized", "0"),
            margin_data.get("m2mrealized", "0"),
        )

        try:
            available = float(margin_data.get("availablecash") or 0)
            utilised = float(margin_data.get("utiliseddebits") or 0)
            if available > 0:
                maybe_record_margin_alert(login_username, utilised / available, threshold=0.8)
        except (TypeError, ValueError):
            pass

        return jsonify({"status": "success", "data": margin_data})

    except Exception as e:
        logger.exception(f"Error fetching dashboard data: {e}")
        return jsonify({"status": "error", "message": "Internal server error"}), 500


@auth_bp.route("/activity", methods=["GET"])
@check_session_validity
def get_recent_activity_route():
    """Return the current user's recent activity feed for the dashboard."""
    if "user" not in session:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401

    from database.auth_db import get_recent_activity

    limit = request.args.get("limit", 20, type=int)
    limit = max(1, min(limit, 50))
    entries = get_recent_activity(session["user"], limit=limit)
    return jsonify({"status": "success", "data": entries})


@auth_bp.route("/pnl-history", methods=["GET"])
@check_session_validity
def get_pnl_history_route():
    """Return today's sampled P&L curve for the Portfolio Overview chart."""
    if "user" not in session:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401

    from database.auth_db import get_todays_pnl_history

    entries = get_todays_pnl_history(session["user"])
    return jsonify({"status": "success", "data": entries})


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    if session.get("logged_in"):
        username = session["user"]

        # Clear cache entries before database update to prevent stale data access
        cache_key_auth = f"auth-{username}"
        cache_key_feed = f"feed-{username}"
        if cache_key_auth in auth_cache:
            del auth_cache[cache_key_auth]
            logger.info(f"Cleared auth cache for user: {username}")
        if cache_key_feed in feed_token_cache:
            del feed_token_cache[cache_key_feed]
            logger.info(f"Cleared feed token cache for user: {username}")

        # Clear symbol cache on logout
        try:
            from database.master_contract_cache_hook import clear_cache_on_logout

            clear_cache_on_logout()
            logger.info("Cleared symbol cache on logout")
        except Exception as cache_error:
            logger.exception(f"Error clearing symbol cache on logout: {cache_error}")

        # writing to database. Preserve the broker name on revoke (don't
        # pass "") - logging out of the APP should not sever which broker
        # was the data broker; only an explicit broker disconnect
        # (Broker Management's Disconnect / Clear All Sessions) should do
        # that. Preserving it lets the next login silently resume from the
        # broker's own still-valid AuthBrokerSession token instead of
        # forcing a fresh OAuth login every time (see
        # _try_resume_broker_session's AuthBrokerSession fallback).
        from database.auth_db import get_auth_token_dbquery
        existing_auth_obj = get_auth_token_dbquery(username)
        broker_to_preserve = existing_auth_obj.broker if existing_auth_obj else ""
        inserted_id = upsert_auth(username, "", broker_to_preserve, revoke=True)
        if inserted_id is not None:
            logger.info(f"Database Upserted record with ID: {inserted_id}")
            logger.info(f"Auth Revoked in the Database for user: {username}")
        else:
            logger.error(f"Failed to upsert auth token for user: {username}")

        # Clear ALL sessions for this user (logout means all devices)
        from database.auth_db import clear_user_sessions
        clear_user_sessions(username)

        # Notify this user's OTHER connected devices to logout immediately.
        # room= is essential here: this is the plain /auth/logout route, hit
        # on every single logout by every user -- an unscoped emit meant
        # ANY user logging out anywhere on the platform force-logged out
        # every OTHER logged-in user too.
        socketio.emit("force_logout", {
            "message": "You have been logged out from another device.",
        }, room=f"user_{username}")

        # Update session count to 0 -- scoped to this user's own devices,
        # same reasoning as the force_logout room= fix above.
        socketio.emit("active_sessions_update", {
            "count": 0,
            "sessions": [],
        }, room=f"user_{username}")

        # Clear entire session to ensure complete logout
        session.clear()
        logger.info(f"Session cleared for user: {username}")

    # For POST requests (AJAX from React), return JSON
    if request.method == "POST":
        return jsonify({"status": "success", "message": "Logged out successfully"})

    # For GET requests (traditional), redirect to login page
    return redirect(url_for("auth.login"))


@auth_bp.route("/profile-data", methods=["GET"])
@check_session_validity
def get_profile_data():
    """Return profile data for React SPA."""
    if "user" not in session:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401

    username = session["user"]

    try:
        # SMTP is a platform-wide admin setting (see /admin/api/smtp) --
        # only surface it to admins here. Non-admins get null and the
        # Profile SMTP tab hides itself accordingly.
        from blueprints.admin import _get_current_user_admin_status

        _current_username, is_admin = _get_current_user_admin_status()

        smtp_settings = get_smtp_settings() if is_admin else None

        # Mask SMTP password - just indicate if it's set
        if smtp_settings and smtp_settings.get("smtp_password"):
            smtp_settings = dict(smtp_settings)
            smtp_settings["smtp_password"] = True
        elif smtp_settings:
            smtp_settings = dict(smtp_settings)
            smtp_settings["smtp_password"] = False

        # Generate TOTP QR code
        user = User.query.filter_by(username=username).first()
        qr_code = None
        totp_secret = None

        if user:
            try:
                import base64
                import io

                import qrcode

                qr = qrcode.QRCode(version=1, box_size=10, border=5)
                qr.add_data(user.get_totp_uri())
                qr.make(fit=True)

                img_buffer = io.BytesIO()
                qr.make_image(fill_color="black", back_color="white").save(img_buffer, format="PNG")
                qr_code = base64.b64encode(img_buffer.getvalue()).decode()
                # Use the public getter that decrypts the at-rest ciphertext.
                # `user.totp_secret` is the raw column value (ciphertext);
                # `get_totp_secret()` returns the plaintext with a fallback
                # for pre-migration rows.
                totp_secret = user.get_totp_secret()
            except Exception as e:
                logger.exception(f"Error generating TOTP QR code: {e}")

        return jsonify(
            {
                "status": "success",
                "data": {
                    "username": username,
                    "smtp_settings": smtp_settings,
                    "qr_code": qr_code,
                    "totp_secret": totp_secret,
                    # user.to_public_dict() deliberately omits uuid -- the
                    # internal id is never surfaced to any client, admin or
                    # otherwise. user_code (e.g. "MAX000123") is the
                    # support-facing identifier.
                    **(user.to_public_dict() if user else {}),
                },
            }
        )

    except Exception as e:
        logger.exception(f"Error getting profile data: {e}")
        return jsonify({"status": "error", "message": "Failed to get profile data"}), 500


@auth_bp.route("/change-password", methods=["POST"])
@check_session_validity
def change_password_api():
    """Change password API endpoint for React SPA."""
    if "user" not in session:
        return jsonify({"status": "error", "message": "Not authenticated"}), 401

    username = session["user"]
    old_password = request.form.get("old_password")
    new_password = request.form.get("new_password")
    confirm_password = request.form.get("confirm_password")

    if not all([old_password, new_password, confirm_password]):
        return jsonify({"status": "error", "message": "All fields are required"}), 400

    user = User.query.filter_by(username=username).first()

    if not user or not user.check_password(old_password):
        return jsonify({"status": "error", "message": "Current password is incorrect"}), 400

    if new_password != confirm_password:
        return jsonify({"status": "error", "message": "New passwords do not match"}), 400

    # Validate password strength
    from utils.auth_utils import validate_password_strength

    is_valid, error_message = validate_password_strength(new_password)
    if not is_valid:
        return jsonify({"status": "error", "message": error_message}), 400

    try:
        user.set_password(new_password)
        db_session.commit()
        logger.info(f"Password changed successfully for user: {username}")

        # Security: a password change should invalidate every active session
        # for this account, including the current browser. The user logs in
        # again with the new password — typical 5-second flow — and any
        # attacker holding a stolen cookie is kicked out at the same moment.
        from database.auth_db import clear_user_sessions
        clear_user_sessions(username)
        # room= scopes this to the user's own devices -- see logout()/
        # reset-password's force_logout above.
        socketio.emit("force_logout", {
            "message": "Your password was changed. Please log in again with the new password.",
        }, room=f"user_{username}")
        session.clear()

        return jsonify({"status": "success", "message": "Password changed successfully"})
    except Exception as e:
        logger.exception(f"Error changing password: {e}")
        return jsonify({"status": "error", "message": "Failed to change password"}), 500
