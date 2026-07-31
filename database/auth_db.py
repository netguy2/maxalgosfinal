# database/auth_db.py

import base64
import inspect
import os

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cachetools import TTLCache
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.sql import func

from database.engine_factory import create_db_engine
from utils.logging import get_logger

# Initialize logger
logger = get_logger(__name__)

# Initialize Argon2 hasher
ph = PasswordHasher()

DATABASE_URL = os.getenv("DATABASE_URL")

# Security: Require API_KEY_PEPPER environment variable (fail fast if missing)
# Pepper must be at least 32 bytes (64 hex characters) for cryptographic security
_pepper_value = os.getenv("API_KEY_PEPPER")
if not _pepper_value:
    raise RuntimeError(
        "CRITICAL: API_KEY_PEPPER environment variable is not set. "
        "This is required for secure password and API key hashing. "
        'Generate one using: python -c "import secrets; print(secrets.token_hex(32))"'
    )
if len(_pepper_value) < 32:
    raise RuntimeError(
        f"CRITICAL: API_KEY_PEPPER must be at least 32 characters (got {len(_pepper_value)}). "
        'Generate a secure pepper using: python -c "import secrets; print(secrets.token_hex(32))"'
    )
PEPPER = _pepper_value


# Setup Fernet encryption for auth tokens.
#
# The KDF salt has two sources, in order of preference:
#   1. FERNET_SALT env var (per-install random hex, 32+ chars). This is the
#      production path. utils/env_check.py auto-provisions it on first boot
#      (and migrates existing ciphertext) so by the time this module imports,
#      the env var is set.
#   2. The legacy hardcoded literal b"maxalgos_static_salt". This is the
#      fallback for one-off scripts that import auth_db directly without
#      going through the env_check bootstrap (CLI utilities, ad-hoc REPL,
#      docs/typecheck runs). A one-time stderr warning fires so the operator
#      notices if a real production process ever hits this path.
def _resolve_fernet_salt() -> bytes:
    raw = (os.getenv("FERNET_SALT") or "").strip()
    if raw and len(raw) >= 32:
        try:
            return bytes.fromhex(raw)
        except ValueError:
            pass
    # Fallback path. Print once so prod misuse is visible without spamming.
    if not getattr(_resolve_fernet_salt, "_warned", False):
        import sys as _sys
        _sys.stderr.write(
            "[auth_db] WARNING: FERNET_SALT not set or invalid; using legacy\n"
            "static salt. Run the app once via app.py so utils/env_check.py\n"
            "auto-provisions a per-install salt.\n"
        )
        _resolve_fernet_salt._warned = True  # type: ignore[attr-defined]
    return b"maxalgos_static_salt"


def get_encryption_key():
    """Generate a Fernet key from PEPPER + per-install FERNET_SALT."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_resolve_fernet_salt(),
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(PEPPER.encode()))
    return Fernet(key)


# Initialize Fernet cipher
fernet = get_encryption_key()


# Calculate cache TTL based on session expiry time to minimize DB hits
def get_session_based_cache_ttl():
    """Calculate cache TTL based on daily session expiry time in .env"""
    # For security and rapid settings propagation (like switching data broker),
    # use a very short cache TTL (5 seconds).
    return 5


# Define auth token cache with TTL until session expiry to minimize DB hits
auth_cache = TTLCache(maxsize=1024, ttl=get_session_based_cache_ttl())
# Define feed token cache with same TTL
feed_token_cache = TTLCache(maxsize=1024, ttl=get_session_based_cache_ttl())
# Define a cache for broker names with a 5-second TTL (longer since broker rarely changes)
broker_cache = TTLCache(maxsize=1024, ttl=5)
# Define a cache for verified API keys with 24-hour TTL
# Security: Only caches user_id (not sensitive), invalidated on key regeneration
# Long TTL is safe because cache is invalidated when keys are regenerated
verified_api_key_cache = TTLCache(maxsize=1024, ttl=36000)  # 10 hours
# Define a cache for invalid API keys with shorter 5-minute TTL (prevent cache poisoning)
invalid_api_key_cache = TTLCache(maxsize=512, ttl=300)  # 5 minutes
# Order mode (auto/semi_auto) is checked on every order request; cache it to
# avoid a DB query per order. Invalidated by update_order_mode via
# invalidate_user_cache, so the TTL is only a backstop.
order_mode_cache = TTLCache(maxsize=128, ttl=60)

engine = create_db_engine(DATABASE_URL)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class Auth(Base):
    __tablename__ = "auth"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True, nullable=False)
    auth = Column(Text, nullable=False)
    feed_token = Column(
        Text, nullable=True
    )  # Make it nullable as not all brokers will provide this
    broker = Column(String(20), nullable=False)
    user_id = Column(String(255), nullable=True)  # Add user_id column
    is_revoked = Column(Boolean, default=False)

    # Samco 2FA fields
    secret_api_key = Column(Text, nullable=True)
    primary_ip = Column(String(45), nullable=True)
    secondary_ip = Column(String(45), nullable=True)
    ip_updated_at = Column(DateTime, nullable=True)

    # Generic auxiliary fields for any broker needing extra storage
    aux_param1 = Column(Text, nullable=True)
    aux_param2 = Column(Text, nullable=True)
    aux_param3 = Column(Text, nullable=True)
    aux_param4 = Column(Text, nullable=True)

    # Performance indexes for frequently queried columns
    __table_args__ = (
        Index("idx_auth_broker", "broker"),  # Speeds up get_broker_name() queries
        Index("idx_auth_user_id", "user_id"),  # Speeds up get_user_id() lookups
        Index("idx_auth_is_revoked", "is_revoked"),  # Speeds up token validity checks
    )


class AuthBrokerSession(Base):
    """Additional broker sessions for a user, beyond their single active
    "data broker" tracked by the Auth table above.

    This is purely additive: Auth and every one of its 34 existing readers
    (get_auth_token, get_auth_token_broker, get_auth_token_dbquery, the
    auth_cache/feed_token_cache/broker_cache, upsert_auth, the WebSocket
    adapter pool, the keepalive service) are completely unaware this table
    exists and are unaffected by it. This table exists only to support the
    multi-broker order fan-out feature: a user's Auth row is still "the
    data broker" used by every existing quote/order/position/etc. code
    path, while AuthBrokerSession holds tokens for OTHER brokers the user
    has separately connected so they don't need to re-authenticate every
    time a multi-broker order includes them.
    """
    __tablename__ = "auth_broker_sessions"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    broker = Column(String(20), nullable=False)
    auth = Column(Text, nullable=False)  # encrypted, same helpers as Auth.auth
    feed_token = Column(Text, nullable=True)  # encrypted
    user_id = Column(String(255), nullable=True)
    is_revoked = Column(Boolean, default=False)
    connected_at = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        UniqueConstraint("username", "broker", name="uq_auth_broker_session"),
        Index("idx_auth_broker_session_username", "username"),
    )


class ApiKeys(Base):
    __tablename__ = "api_keys"
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=False, unique=True)
    api_key_hash = Column(Text, nullable=False)  # For verification
    api_key_encrypted = Column(Text, nullable=False)  # For retrieval
    created_at = Column(DateTime(timezone=True), default=func.now())
    order_mode = Column(String(20), default="auto")  # 'auto' or 'semi_auto'

    # Performance indexes
    __table_args__ = (
        Index("idx_api_keys_order_mode", "order_mode"),  # Speeds up filtering by order mode
        Index("idx_api_keys_created_at", "created_at"),  # Speeds up time-based queries
    )


class ActiveSession(Base):
    """Tracks active login sessions across devices for a user."""
    __tablename__ = "active_sessions"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, index=True)
    session_id = Column(String(64), unique=True, nullable=False)  # Random token to identify session
    device_info = Column(String(500), nullable=True)  # User-Agent string
    ip_address = Column(String(45), nullable=True)
    broker = Column(String(20), nullable=True)
    login_time = Column(DateTime(timezone=True), default=func.now())
    last_seen = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("idx_active_sessions_username", "username"),
    )


class LoginAttempt(Base):
    """Records all login attempts (successful and failed) for security auditing."""
    __tablename__ = "login_attempts"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    ip_address = Column(String(45), nullable=True)
    device_info = Column(String(500), nullable=True)  # User-Agent
    status = Column(String(20), nullable=False)  # 'success', 'failed', 'resumed'
    login_type = Column(String(20), nullable=True)  # 'password', 'oauth', 'resume'
    broker = Column(String(20), nullable=True)
    failure_reason = Column(String(255), nullable=True)  # e.g. 'invalid_password', 'token_expired'
    timestamp = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("idx_login_attempts_username", "username"),
        Index("idx_login_attempts_timestamp", "timestamp"),
        Index("idx_login_attempts_status", "status"),
    )


def _now_ist():
    """Get current time in IST."""
    from datetime import datetime

    import pytz
    return datetime.now(pytz.timezone("Asia/Kolkata"))


def log_login_attempt(username, ip_address=None, device_info=None, status="failed",
                      login_type="password", broker=None, failure_reason=None):
    """Record a login attempt for audit purposes. All records are retained permanently."""
    try:
        attempt = LoginAttempt(
            username=username,
            ip_address=ip_address,
            device_info=device_info[:500] if device_info else None,
            status=status,
            login_type=login_type,
            broker=broker,
            failure_reason=failure_reason,
            timestamp=_now_ist(),
        )
        db_session.add(attempt)
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error logging login attempt: {e}")


def get_login_attempts(limit=100, status_filter=None, username=None):
    """Get recent login attempts, optionally filtered by status and/or
    username. `username` scoping is used by the admin per-user login-history
    view (blueprints/admin.py)."""
    try:
        query = LoginAttempt.query.order_by(LoginAttempt.timestamp.desc())
        if status_filter:
            query = query.filter(LoginAttempt.status == status_filter)
        if username:
            query = query.filter(LoginAttempt.username == username)
        attempts = query.limit(limit).all()
        return [
            {
                "username": a.username,
                "ip_address": a.ip_address,
                "device_info": a.device_info,
                "status": a.status,
                "login_type": a.login_type,
                "broker": a.broker,
                "failure_reason": a.failure_reason,
                "timestamp": a.timestamp.isoformat() if a.timestamp else None,
            }
            for a in attempts
        ]
    except Exception as e:
        logger.error(f"Error getting login attempts: {e}")
        return []


def clear_login_attempts():
    """Clear all login attempt records."""
    try:
        LoginAttempt.query.delete()
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error clearing login attempts: {e}")


class ActivityLog(Base):
    """Real system events for the dashboard's Recent Activity feed.

    Distinct from LoginAttempt (security audit, retained permanently) and
    OrderLog (raw API request/response payloads) -- this is a small,
    human-readable feed meant to be trimmed to a recent window per user.
    """
    __tablename__ = "activity_log"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    category = Column(String(30), nullable=False)  # 'system', 'broker', 'account', 'order'
    title = Column(String(100), nullable=False)
    message = Column(String(500), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("idx_activity_log_username", "username"),
        Index("idx_activity_log_timestamp", "timestamp"),
    )


def record_activity(username, category, title, message):
    """Insert one Recent Activity entry. Best-effort -- never raises."""
    if not username:
        return
    try:
        entry = ActivityLog(
            username=username,
            category=category,
            title=title[:100],
            message=message[:500],
            timestamp=_now_ist(),
        )
        db_session.add(entry)
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error recording activity: {e}")


# Debounce margin-alert activity entries the same way _last_pnl_snapshot
# debounces P&L samples below -- /auth/dashboard-data is polled frequently,
# and without this a sustained high-utilization account would write a new
# "Margin Alert" row on every poll instead of once per cooldown window.
_last_margin_alert: dict[str, float] = {}
_MARGIN_ALERT_MIN_INTERVAL = 1800.0  # seconds (30 min)


def maybe_record_margin_alert(username, ratio, threshold=0.8):
    """Record a "Margin Alert" activity entry when utilization crosses
    `threshold` (as a 0-1 ratio), at most once per _MARGIN_ALERT_MIN_INTERVAL
    per user. No-ops below threshold or within the cooldown window."""
    if not username or ratio < threshold:
        return
    import time as _time

    now = _time.monotonic()
    last = _last_margin_alert.get(username)
    if last and (now - last) < _MARGIN_ALERT_MIN_INTERVAL:
        return
    _last_margin_alert[username] = now
    record_activity(
        username,
        "account",
        "Margin Alert",
        f"Margin utilization at {ratio * 100:.1f}% of available balance",
    )


def get_recent_activity(username, limit=20):
    """Get the most recent activity entries for a user, newest first."""
    try:
        entries = (
            ActivityLog.query.filter_by(username=username)
            .order_by(ActivityLog.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "category": e.category,
                "title": e.title,
                "message": e.message,
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
            }
            for e in entries
        ]
    except Exception as e:
        logger.error(f"Error getting recent activity: {e}")
        return []


class PnlSnapshot(Base):
    """Periodic sample of margin P&L, sampled opportunistically whenever the
    dashboard fetches funds data. Powers the Portfolio Overview intraday
    curve -- a real (if coarse) history instead of a static mock chart.
    """
    __tablename__ = "pnl_snapshot"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False)
    m2munrealized = Column(String(30), nullable=False)
    m2mrealized = Column(String(30), nullable=False)
    timestamp = Column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("idx_pnl_snapshot_username", "username"),
        Index("idx_pnl_snapshot_timestamp", "timestamp"),
    )


# Debounce identical consecutive P&L snapshots. The dashboard polls every few
# seconds; without this, a flat market writes a duplicate row on every poll.
# We still capture every real change and at least one sample per ~15s window.
_last_pnl_snapshot: dict[str, tuple[str, str, float]] = {}
_PNL_SNAPSHOT_MIN_INTERVAL = 15.0  # seconds


def record_pnl_snapshot(username, m2munrealized, m2mrealized):
    """Append one P&L sample for today's curve. Best-effort -- never raises.

    Skips the write when the values are unchanged AND the last write for this
    user was within the debounce window, so a quiet market does not spam the
    table on every dashboard poll while still recording every real move.
    """
    if not username:
        return
    import time as _time

    m2mu, m2mr = str(m2munrealized), str(m2mrealized)
    prev = _last_pnl_snapshot.get(username)
    now = _time.monotonic()
    if prev and prev[0] == m2mu and prev[1] == m2mr and (now - prev[2]) < _PNL_SNAPSHOT_MIN_INTERVAL:
        return
    try:
        snap = PnlSnapshot(
            username=username,
            m2munrealized=m2mu,
            m2mrealized=m2mr,
            timestamp=_now_ist(),
        )
        db_session.add(snap)
        db_session.commit()
        _last_pnl_snapshot[username] = (m2mu, m2mr, now)
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error recording P&L snapshot: {e}")


def get_todays_pnl_history(username):
    """Return today's P&L snapshots for the given user, oldest first."""
    try:
        ist_today = _now_ist().date()
        start_of_day = ist_today.strftime("%Y-%m-%d 00:00:00")
        snaps = (
            PnlSnapshot.query.filter_by(username=username)
            .filter(PnlSnapshot.timestamp >= start_of_day)
            .order_by(PnlSnapshot.timestamp.asc())
            .all()
        )
        return [
            {
                "m2munrealized": s.m2munrealized,
                "m2mrealized": s.m2mrealized,
                "timestamp": s.timestamp.isoformat() if s.timestamp else None,
            }
            for s in snaps
        ]
    except Exception as e:
        logger.error(f"Error getting P&L history: {e}")
        return []
        logger.error(f"Error clearing login attempts: {e}")


# Default changed to multi-device: traders legitimately watch/manage
# positions from phone + desktop simultaneously, and forcing a re-login on
# every new device was also compounding with LOGIN_RATE_LIMIT_MIN (5/min)
# during normal multi-device use. Set SINGLE_SESSION_PER_USER=true to
# restore the old force-logout-other-devices behavior.
SINGLE_SESSION_PER_USER = os.getenv("SINGLE_SESSION_PER_USER", "false").lower() == "true"
MAX_SESSIONS_PER_USER = 1 if SINGLE_SESSION_PER_USER else int(os.getenv("MAX_SESSIONS_PER_USER", "5"))


def register_session(username, session_id, device_info=None, ip_address=None, broker=None):
    """Register a new active session for a user.

    Enforces single active session per user account (or up to MAX_SESSIONS_PER_USER).
    When a new login occurs on another device/browser, prior active sessions for that
    user are invalidated and notified via SocketIO force_logout push event.
    """
    try:
        # Find existing active sessions for this user to invalidate
        existing_sessions = ActiveSession.query.filter_by(username=username).all()
        for old_sess in existing_sessions:
            if old_sess.session_id != session_id:
                # Notify the old session via SocketIO room f"session_{old_sess.session_id}"
                try:
                    from extensions import socketio
                    socketio.emit(
                        "force_logout",
                        {
                            "status": "error",
                            "reason": "logged_in_another_device",
                            "message": "Your account was logged in from another device or browser.",
                        },
                        room=f"session_{old_sess.session_id}",
                    )
                    # Also notify general user room so any listener catches it
                    socketio.emit(
                        "force_logout",
                        {
                            "status": "error",
                            "reason": "logged_in_another_device",
                            "message": "Your account was logged in from another device or browser.",
                        },
                        room=f"user_{username}",
                    )
                    logger.info(f"Displaced previous session {old_sess.session_id[:8]}... for user {username}")
                except Exception as socket_err:
                    logger.warning(f"Failed to send force_logout to old session: {socket_err}")

        # Delete all old sessions for this user when single session per user is active
        if SINGLE_SESSION_PER_USER:
            ActiveSession.query.filter_by(username=username).delete()
        elif ip_address:
            # Remove stale sessions from the same device (same user + IP)
            ActiveSession.query.filter_by(username=username, ip_address=ip_address).delete()

        # Enforce per-user session cap — remove oldest if at limit
        current_count = ActiveSession.query.filter_by(username=username).count()
        if current_count >= MAX_SESSIONS_PER_USER:
            oldest = (
                ActiveSession.query.filter_by(username=username)
                .order_by(ActiveSession.login_time.asc())
                .first()
            )
            if oldest:
                db_session.delete(oldest)

        now = _now_ist()
        active = ActiveSession(
            username=username,
            session_id=session_id,
            device_info=device_info,
            ip_address=ip_address,
            broker=broker,
            login_time=now,
            last_seen=now,
        )
        db_session.add(active)
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error registering session: {e}")
        return False


def is_session_id_active(username, session_id):
    """Check if a specific session_id is active in DB for a user."""
    if not username or not session_id:
        return False
    try:
        record = ActiveSession.query.filter_by(username=username, session_id=session_id).first()
        return record is not None
    except Exception as e:
        logger.error(f"Error checking session_id active status: {e}")
        # Fail open on DB hiccup to avoid logging users out erroneously
        return True


def remove_session(session_id):
    """Remove a session when user logs out."""
    try:
        ActiveSession.query.filter_by(session_id=session_id).delete()
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error removing session: {e}")


def get_active_sessions(username):
    """Get all active sessions for a user."""
    try:
        sessions = ActiveSession.query.filter_by(username=username).order_by(
            ActiveSession.last_seen.desc()
        ).all()
        return [
            {
                "session_id": s.session_id,
                "device_info": s.device_info,
                "ip_address": s.ip_address,
                "broker": s.broker,
                "login_time": s.login_time.isoformat() if s.login_time else None,
                "last_seen": s.last_seen.isoformat() if s.last_seen else None,
            }
            for s in sessions
        ]
    except Exception as e:
        logger.error(f"Error getting active sessions: {e}")
        return []


def update_session_last_seen(session_id):
    """Update last_seen timestamp for a session."""
    try:
        active = ActiveSession.query.filter_by(session_id=session_id).first()
        if active:
            active.last_seen = _now_ist()
            db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error updating session last_seen: {e}")


def clear_user_sessions(username):
    """Clear all sessions for a user (e.g., on token revocation at 3 AM)."""
    try:
        ActiveSession.query.filter_by(username=username).delete()
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error clearing user sessions: {e}")


def is_known_device(username, device_info, ip_address):
    """Return True if this device_info+ip_address combo has been seen before for this user.

    Used by the new-device email alert: fires once for a genuinely first-time
    device/IP combination, not on every subsequent login from the same device.

    Matching strategy: exact IP *and* User-Agent prefix match (first 200 chars,
    since UA strings are long but stable per device/browser).  Deliberately
    conservative -- we'd rather miss an alert for a slightly different UA than
    spam the user every time their browser auto-updates.
    """
    if not username:
        return True  # Fail-safe: don't fire if we have no username

    ua_prefix = (device_info or "")[:200]
    ip = ip_address or ""
    try:
        sessions = ActiveSession.query.filter_by(username=username).all()
        for s in sessions:
            known_ua_prefix = (s.device_info or "")[:200]
            known_ip = s.ip_address or ""
            if known_ua_prefix == ua_prefix and known_ip == ip:
                return True
        return False  # No matching row found → new device
    except Exception as e:
        logger.error(f"Error in is_known_device: {e}")
        return True  # Fail open on DB error — don't send spurious alerts


def init_db():
    """Initialize the authentication database tables.

    Creates the ``auth`` and ``api_keys`` tables if they do not
    already exist, using the shared ``db_init_helper`` for
    consistent startup logging.
    """
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Auth DB", logger)


def safe_decrypt_token(value):
    """Decrypt a Fernet-encrypted value, falling back to the raw value
    when decryption fails (typical reason: the column still holds plaintext
    from before the rotate_pepper.py migration). Returns None for empty input.

    This is the read-path helper used by columns that transitioned from
    plaintext to ciphertext (totp_secret, samco secret_api_key, flow api_key,
    telegram bot token). Callers must pass values encrypted with the same
    Fernet key (i.e. the auth_db one) — telegram_db and settings_db have
    their own derivations and use their own helpers.
    """
    if not value:
        return None
    decrypted = decrypt_token(value)
    return decrypted if decrypted is not None else value


def encrypt_token(token):
    """Encrypt auth token"""
    if not token:
        return ""
    return fernet.encrypt(token.encode()).decode()


# Track ciphertext fingerprints we've already failed to decrypt so we log each
# orphan row's full traceback once, then suppress the noise on every subsequent
# call. Without this, a single un-migrated row encrypted under a lost salt
# (e.g. the row left as-is after a Fernet salt rotation, see issue #1394)
# triggers a full ERROR + traceback on every WebSocket re-connect attempt,
# spamming the logs with hundreds of identical entries.
_decrypt_failure_fingerprints: set[str] = set()


def decrypt_token(encrypted_token):
    """Decrypt auth token"""
    if not encrypted_token:
        return ""
    try:
        return fernet.decrypt(encrypted_token.encode()).decode()
    except Exception as e:
        # Hash the ciphertext (not the plaintext — there is no plaintext yet)
        # so we don't keep the full token in memory just to dedupe log lines.
        import hashlib

        try:
            payload = (
                encrypted_token.encode()
                if isinstance(encrypted_token, str)
                else encrypted_token
            )
            fp = hashlib.blake2s(payload, digest_size=8).hexdigest()
        except Exception:
            fp = "unknown"

        if fp in _decrypt_failure_fingerprints:
            # Already reported the full traceback once — keep the signal
            # but at debug level so it doesn't spam ERROR logs.
            logger.debug(f"Repeat decrypt failure (fingerprint={fp})")
        else:
            _decrypt_failure_fingerprints.add(fp)
            logger.exception(
                f"Error decrypting token (fingerprint={fp}): {e}. "
                "This row may have been encrypted under a previous "
                "API_KEY_PEPPER or FERNET_SALT and survived a rotation. "
                "Re-authenticate the affected broker / user to overwrite "
                "the orphan ciphertext with a fresh value."
            )
        return None


def upsert_auth(name, auth_token, broker, feed_token=None, user_id=None, revoke=False):
    """Store encrypted auth token and feed token if provided.

    Also publishes cache invalidation events via ZeroMQ for multi-process deployments.
    This ensures WebSocket proxy and other processes clear their stale cached tokens.
    See GitHub issue #765 for details on the cross-process cache synchronization problem.
    """
    encrypted_token = encrypt_token(auth_token)
    encrypted_feed_token = encrypt_token(feed_token) if feed_token else None

    auth_obj = Auth.query.filter_by(name=name).first()
    if auth_obj:
        auth_obj.auth = encrypted_token
        auth_obj.feed_token = encrypted_feed_token
        auth_obj.broker = broker
        auth_obj.user_id = user_id
        auth_obj.is_revoked = revoke
    else:
        auth_obj = Auth(
            name=name,
            auth=encrypted_token,
            feed_token=encrypted_feed_token,
            broker=broker,
            user_id=user_id,
            is_revoked=revoke,
        )
        db_session.add(auth_obj)
    db_session.commit()

    # CRITICAL: Clear ENTIRE auth_cache on token update to prevent stale token issues
    # This is necessary because get_auth_token_broker() uses a different cache key format
    # (sha256(api_key)_include_feed_token) than upsert_auth() uses (auth-{name}).
    # Without clearing all entries, old cached tokens from get_auth_token_broker()
    # would persist and cause 401 Unauthorized errors after re-login.
    # See GitHub issue #851 for details on this cache key mismatch bug.
    auth_cache.clear()
    feed_token_cache.clear()
    broker_cache.clear()  # Also clear broker cache to ensure fresh data
    logger.info(f"Cleared all auth caches after token update for user: {name}")

    # Publish cache invalidation event via ZeroMQ for other processes
    # This notifies WebSocket proxy and other processes to clear their stale caches
    try:
        from database.cache_invalidation import publish_all_cache_invalidation
        publish_all_cache_invalidation(name)
        logger.debug(f"Published cache invalidation for user: {name}")
    except Exception as e:
        # Don't fail auth operation if cache invalidation fails
        # The database fallback in other processes will handle it
        logger.warning(f"Failed to publish cache invalidation for user {name}: {e}")

    # Same-process invalidation. Production runs `gunicorn -w 1` per CLAUDE.md
    # (single worker required for SocketIO state), so the WebSocket proxy's
    # _POOLED_ADAPTERS registry lives in this very process. The ZeroMQ
    # publish above is for hypothetical multi-process deployments; without
    # also discarding the in-process cache here, the next WS connect after
    # re-login reuses the pool that was initialised with the *old* token
    # and fails with "Adapter initialization failed: No authentication
    # token found" until the process is restarted. See issue #1394.
    try:
        from websocket_proxy.broker_factory import cleanup_pools_for_user
        cleanup_pools_for_user(name, broker_name=broker)
    except Exception as e:
        # Don't fail auth on cleanup error — the user can still trade via
        # HTTP endpoints; only the WS layer is affected.
        logger.warning(f"Failed to invalidate WS adapter pool for {name}/{broker}: {e}")

    return auth_obj.id


# ─────────────────────────────────────────────────────────────────────────
# AuthBrokerSession helpers — additive multi-broker support.
#
# These never touch the Auth table, its caches, or its 34 existing readers.
# Auth remains "the data broker" exactly as today; these functions manage
# OTHER brokers a user has separately connected for multi-broker order
# fan-out (see services/multi_broker_order_service.py).
# ─────────────────────────────────────────────────────────────────────────


def _invalidate_ws_pool_for_broker_session_change(username, broker):
    """Tear down the WebSocket proxy's pooled adapter for (username, broker)
    after an AuthBrokerSession row changes (connect, reconnect, or
    disconnect of a NON-data-broker connection via upsert_broker_session /
    revoke_broker_session).

    Mirrors upsert_auth's identical invalidation (ZMQ publish + in-process
    cleanup_pools_for_user) below -- that path only ever ran for the single
    data-broker Auth row, so disconnecting or reconnecting any OTHER
    connected broker left `websocket_proxy`'s _POOLED_ADAPTERS entry for it
    completely untouched. The pool kept reusing the old adapter object
    (built from the now-stale token) indefinitely: ConnectionPool's
    "already subscribed" short-circuit (see connection_manager.py) trusts
    that stale adapter's `connected` flag rather than ever re-issuing a
    fresh subscribe, so live ticks silently froze after any disconnect+
    reconnect of a secondary broker, or after a second device's login
    session ended up sharing that same stale pooled adapter.
    """
    try:
        from database.cache_invalidation import publish_all_cache_invalidation
        publish_all_cache_invalidation(username)
    except Exception as e:
        logger.warning(f"Failed to publish cache invalidation for user {username}: {e}")

    try:
        from websocket_proxy.broker_factory import cleanup_pools_for_user
        cleanup_pools_for_user(username, broker_name=broker)
    except Exception as e:
        logger.warning(f"Failed to invalidate WS adapter pool for {username}/{broker}: {e}")


def upsert_broker_session(username, broker, auth_token, feed_token=None, user_id=None):
    """Store (or refresh) a connected broker's session, independent of the
    user's Auth row / data broker. Finds-or-creates by (username, broker),
    so connecting a second broker never touches the first's row."""
    encrypted_token = encrypt_token(auth_token)
    encrypted_feed_token = encrypt_token(feed_token) if feed_token else None

    session_obj = AuthBrokerSession.query.filter_by(username=username, broker=broker).first()
    if session_obj:
        session_obj.auth = encrypted_token
        session_obj.feed_token = encrypted_feed_token
        session_obj.user_id = user_id
        session_obj.is_revoked = False
    else:
        session_obj = AuthBrokerSession(
            username=username,
            broker=broker,
            auth=encrypted_token,
            feed_token=encrypted_feed_token,
            user_id=user_id,
            is_revoked=False,
        )
        db_session.add(session_obj)
    db_session.commit()

    # A reconnect (or first connect) of this broker means any pooled WS
    # adapter built from its PREVIOUS token is stale -- rebuild it on next
    # subscribe rather than silently reusing dead/mismatched credentials.
    _invalidate_ws_pool_for_broker_session_change(username, broker)

    return session_obj.id


def get_broker_session(username, broker):
    """Return (auth_token, feed_token, user_id) for a connected broker, or
    None if not connected / revoked."""
    session_obj = AuthBrokerSession.query.filter_by(
        username=username, broker=broker, is_revoked=False
    ).first()
    if session_obj:
        auth_token = decrypt_token(session_obj.auth)
        if auth_token:
            feed_token = decrypt_token(session_obj.feed_token) if session_obj.feed_token else None
            return auth_token, feed_token, session_obj.user_id

    # Fallback to primary Auth table if requested broker matches the primary Auth row
    auth_obj = Auth.query.filter_by(name=username, is_revoked=False).first()
    if auth_obj and auth_obj.broker == broker:
        auth_token = decrypt_token(auth_obj.auth)
        if auth_token:
            feed_token = decrypt_token(auth_obj.feed_token) if auth_obj.feed_token else None
            return auth_token, feed_token, auth_obj.name

    return None


def list_broker_sessions(username):
    """Return every broker a user has connected via the multi-broker flow,
    as a list of dicts: [{"broker": ..., "connected_at": ..., "is_revoked": ...}, ...].
    Used by the Broker Management page - does not include token material."""
    sessions = AuthBrokerSession.query.filter_by(username=username).all()
    return [
        {
            "broker": s.broker,
            "connected_at": s.connected_at.isoformat() if s.connected_at else None,
            "is_revoked": s.is_revoked,
        }
        for s in sessions
    ]


def revoke_broker_session(username, broker):
    """Disconnect a single broker without touching any other connected
    broker or the user's Auth/data-broker row."""
    session_obj = AuthBrokerSession.query.filter_by(username=username, broker=broker).first()
    if not session_obj:
        return False
    session_obj.is_revoked = True
    auth_cache.clear()
    db_session.commit()

    # Without this, disconnecting a broker never told the WebSocket proxy
    # anything happened -- it kept serving (or trying to serve) client
    # subscriptions through the now-revoked session's pooled adapter
    # forever, since nothing else in this codebase re-checks a pooled
    # adapter against the DB's current connection state. See
    # _invalidate_ws_pool_for_broker_session_change's docstring.
    _invalidate_ws_pool_for_broker_session_change(username, broker)

    return True


def revoke_session_by_token(auth_token):
    """Mark auth session as revoked in Auth and AuthBrokerSession tables when broker rejects token."""
    if not auth_token:
        return False
    try:
        auth_cache.clear()
        revoked_any = False

        # Mark in AuthBrokerSession
        sessions = AuthBrokerSession.query.filter_by(is_revoked=False).all()
        for s in sessions:
            if s.auth and decrypt_token(s.auth) == auth_token:
                s.is_revoked = True
                revoked_any = True
                logger.warning(f"Revoked AuthBrokerSession for user '{s.username}', broker '{s.broker}' due to expired session.")

        # Mark in Auth table
        auth_records = Auth.query.filter_by(is_revoked=False).all()
        for a in auth_records:
            if a.auth and decrypt_token(a.auth) == auth_token:
                a.is_revoked = True
                revoked_any = True
                logger.warning(f"Revoked Auth for user '{a.name}', broker '{a.broker}' due to expired session.")

        if revoked_any:
            db_session.commit()
        return revoked_any
    except Exception as e:
        logger.exception(f"Error revoking session by token: {e}")
        return False


def _get_broker_from_stack():
    """Detect the broker name from the caller call stack."""
    try:
        for frame_info in inspect.stack():
            module = inspect.getmodule(frame_info.frame)
            if module and module.__name__:
                parts = module.__name__.split('.')
                if len(parts) > 1 and parts[0] == 'broker':
                    return parts[1].lower()
    except Exception:
        pass
    return None


def get_auth_token(name, bypass_cache: bool = False):
    """Get decrypted auth token.

    Args:
        name: The user identifier to get the token for
        bypass_cache: If True, skip the cache and query the database directly.
                     Use this when retrying after a 403 error to get fresh credentials.
                     See GitHub issue #765 for details.

    Returns:
        The decrypted auth token, or None if not found/revoked
    """
    # Handle None or empty name gracefully
    if not name:
        logger.debug("get_auth_token called with empty/None name, returning None")
        return None

    broker = _get_broker_from_stack()
    if broker:
        cache_key = f"auth-{name}-{broker}"
    else:
        cache_key = f"auth-{name}"

    # Bypass cache if requested (e.g., after 403 error for fresh token)
    if bypass_cache:
        logger.debug(f"Bypassing cache for user: {name} (fresh token requested)")
        # Clear stale cache entry
        if cache_key in auth_cache:
            del auth_cache[cache_key]

        # Check AuthBrokerSession first
        if broker:
            session_obj = AuthBrokerSession.query.filter_by(
                username=name, broker=broker, is_revoked=False
            ).first()
            if session_obj:
                auth_cache[cache_key] = session_obj
                return decrypt_token(session_obj.auth)

        # Fallback to Auth table
        auth_obj = get_auth_token_dbquery(name)
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            # Update cache with fresh data
            auth_cache[cache_key] = auth_obj
            return decrypt_token(auth_obj.auth)
        return None

    # Normal cache-first lookup
    if cache_key in auth_cache:
        cached_obj = auth_cache[cache_key]
        if hasattr(cached_obj, "is_revoked") and not cached_obj.is_revoked:
            if hasattr(cached_obj, "auth"):
                return decrypt_token(cached_obj.auth)

        # If invalid/revoked, clear cache
        if cache_key in auth_cache:
            del auth_cache[cache_key]
        return None
    else:
        # Check AuthBrokerSession first
        if broker:
            session_obj = AuthBrokerSession.query.filter_by(
                username=name, broker=broker, is_revoked=False
            ).first()
            if session_obj:
                auth_cache[cache_key] = session_obj
                return decrypt_token(session_obj.auth)

        # Fallback to Auth table
        auth_obj = get_auth_token_dbquery(name)
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            auth_cache[cache_key] = auth_obj
            return decrypt_token(auth_obj.auth)
        return None


def get_auth_token_fresh(name):
    """Get fresh auth token directly from database, bypassing cache.

    This is a convenience function for use after authentication failures (403 errors).
    It clears the local cache and fetches the latest token from the database.
    See GitHub issue #765 for details on when to use this.

    Args:
        name: The user identifier to get the token for

    Returns:
        The decrypted auth token, or None if not found/revoked
    """
    return get_auth_token(name, bypass_cache=True)


def get_auth_token_dbquery(name):
    """Fetch the auth token record directly from the database.

    Args:
        name: The user identifier (username) to look up.

    Returns:
        The ``Auth`` ORM instance if a valid record exists,
        otherwise ``None``.
    """
    try:
        # Handle None or empty name gracefully
        if not name:
            logger.debug("get_auth_token_dbquery called with empty/None name")
            return None

        auth_obj = Auth.query.filter_by(name=name).first()
        if auth_obj and not auth_obj.is_revoked:
            return auth_obj
        else:
            # Only log warning for actual usernames, not None/empty
            if name:
                logger.warning(f"No valid auth token found for name '{name}'.")
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database for auth token: {e}")
        return None


def get_feed_token(name):
    """Get the feed token for a user.

    Args:
        name: The user identifier (username) to look up.

    Returns:
        The feed token string, or ``None`` if unavailable.
    """
    # Handle None or empty name gracefully
    if not name:
        logger.debug("get_feed_token called with empty/None name, returning None")
        return None

    broker = _get_broker_from_stack()
    if broker:
        cache_key = f"feed-{name}-{broker}"
    else:
        cache_key = f"feed-{name}"

    if cache_key in feed_token_cache:
        cached_obj = feed_token_cache[cache_key]
        if hasattr(cached_obj, "is_revoked") and not cached_obj.is_revoked:
            if hasattr(cached_obj, "feed_token") and cached_obj.feed_token:
                return decrypt_token(cached_obj.feed_token)
            return None
        else:
            if cache_key in feed_token_cache:
                del feed_token_cache[cache_key]
            return None
    else:
        # Check AuthBrokerSession first
        if broker:
            session_obj = AuthBrokerSession.query.filter_by(
                username=name, broker=broker, is_revoked=False
            ).first()
            if session_obj:
                feed_token_cache[cache_key] = session_obj
                return decrypt_token(session_obj.feed_token) if session_obj.feed_token else None

        # Fallback to Auth table
        auth_obj = get_feed_token_dbquery(name)
        if isinstance(auth_obj, Auth) and not auth_obj.is_revoked:
            feed_token_cache[cache_key] = auth_obj
            return decrypt_token(auth_obj.feed_token) if auth_obj.feed_token else None
        return None


def get_feed_token_dbquery(name):
    """Fetch the feed token record directly from the database.

    Args:
        name: The user identifier (username) to look up.

    Returns:
        The ``Auth`` ORM instance if a valid record exists,
        otherwise ``None``.
    """
    try:
        # Handle None or empty name gracefully
        if not name:
            logger.debug("get_feed_token_dbquery called with empty/None name")
            return None

        auth_obj = Auth.query.filter_by(name=name).first()
        if auth_obj and not auth_obj.is_revoked:
            return auth_obj
        else:
            # Only log warning for actual usernames, not None/empty
            if name:
                logger.warning(f"No valid feed token found for name '{name}'.")
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database for feed token: {e}")
        return None


def get_user_id(name):
    """Get the stored user_id (DefinEdge uid) for a user"""
    try:
        if not name:
            logger.debug("get_user_id called with empty/None name")
            return None

        broker = _get_broker_from_stack()
        if broker:
            session_obj = AuthBrokerSession.query.filter_by(
                username=name, broker=broker, is_revoked=False
            ).first()
            if session_obj:
                return session_obj.user_id

        # Fallback to Auth table
        auth_obj = Auth.query.filter_by(name=name).first()
        if auth_obj and not auth_obj.is_revoked:
            return auth_obj.user_id  # This should return "1272808" for DefinEdge
        else:
            if name:
                logger.warning(f"No valid user_id found for name '{name}'.")
            return None
    except Exception as e:
        logger.exception(f"Error while querying the database for user_id: {e}")
        return None


def invalidate_user_cache(user_id):
    """
    Invalidate all cached data for a user when their credentials change.
    Security: Ensures old API keys/tokens are not usable after regeneration.
    """
    # Clear all caches that might contain this user's data
    auth_cache.clear()
    broker_cache.clear()
    feed_token_cache.clear()
    verified_api_key_cache.clear()
    invalid_api_key_cache.clear()
    order_mode_cache.clear()
    logger.info(f"Cleared all caches for user_id: {user_id}")


def upsert_api_key(user_id, api_key):
    """Store both hashed and encrypted API key"""
    # Hash with Argon2 for verification
    peppered_key = api_key + PEPPER
    hashed_key = ph.hash(peppered_key)

    # Encrypt for retrieval
    encrypted_key = encrypt_token(api_key)

    api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
    if api_key_obj:
        api_key_obj.api_key_hash = hashed_key
        api_key_obj.api_key_encrypted = encrypted_key
    else:
        api_key_obj = ApiKeys(
            user_id=user_id, api_key_hash=hashed_key, api_key_encrypted=encrypted_key
        )
        db_session.add(api_key_obj)
    db_session.commit()

    # Security: Invalidate all caches when API key changes
    invalidate_user_cache(user_id)

    return api_key_obj.id


def get_api_key(user_id):
    """Check if user has an API key"""
    try:
        api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
        return api_key_obj is not None
    except Exception as e:
        logger.exception(f"Error while querying the database for API key: {e}")
        return None


def get_api_key_for_tradingview(user_id):
    """Get decrypted API key for TradingView configuration"""
    try:
        api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
        if api_key_obj and api_key_obj.api_key_encrypted:
            return decrypt_token(api_key_obj.api_key_encrypted)
        return None
    except Exception as e:
        logger.exception(f"Error while querying the database for API key: {e}")
        return None


def get_first_available_api_key():
    """
    Get the first available decrypted API key from the database.
    Used for background services that don't have session context.

    Only returns keys for users who have an active (non-revoked) auth session
    with a broker configured. This prevents returning orphaned API keys for
    deleted users or users with revoked sessions.
    """
    try:
        # Join api_keys with auth to only return keys for users with active sessions
        api_keys = ApiKeys.query.all()
        for api_key_obj in api_keys:
            if not api_key_obj.api_key_encrypted:
                continue
            # Check if this user has an active auth session with a broker
            auth_obj = Auth.query.filter_by(name=api_key_obj.user_id).first()
            if auth_obj and not auth_obj.is_revoked and auth_obj.broker:
                return decrypt_token(api_key_obj.api_key_encrypted)
        return None
    except Exception as e:
        logger.exception(f"Error getting first available API key: {e}")
        return None


def verify_api_key(provided_api_key):
    """
    Verify an API key using Argon2 with intelligent caching.

    Security measures:
    - Only caches user_id (not sensitive data)
    - Uses SHA256 hash as cache key (never stores plaintext)
    - Invalid keys cached for 5min (prevents brute force)
    - Valid keys cached for 1hr (balances security vs performance)
    - Cache invalidated on key regeneration
    """
    import hashlib

    from flask import has_request_context

    from database.traffic_db import InvalidAPIKeyTracker
    from utils.ip_helper import get_real_ip

    # Generate secure cache key (SHA256 hash of API key)
    # Security: Never store plaintext API key in cache
    cache_key = hashlib.sha256(provided_api_key.encode()).hexdigest()

    # Step 1: Check invalid cache first (fast rejection of known bad keys)
    if cache_key in invalid_api_key_cache:
        logger.debug("API key rejected from invalid cache")
        return None

    # Step 2: Check valid cache (fast path for legitimate requests)
    if cache_key in verified_api_key_cache:
        user_id = verified_api_key_cache[cache_key]
        logger.debug(f"API key verified from cache for user_id: {user_id}")
        return user_id

    # Step 3: Cache miss - perform expensive Argon2 verification
    peppered_key = provided_api_key + PEPPER
    try:
        # Query all API keys
        api_keys = ApiKeys.query.all()

        # Try to verify against each stored hash
        for api_key_obj in api_keys:
            try:
                ph.verify(api_key_obj.api_key_hash, peppered_key)
                # Valid key found - cache it
                verified_api_key_cache[cache_key] = api_key_obj.user_id
                logger.debug(f"API key verified and cached for user_id: {api_key_obj.user_id}")
                return api_key_obj.user_id
            except VerifyMismatchError:
                continue

        # If we reach here, the API key is invalid
        # Cache the invalid result to prevent repeated expensive verifications
        invalid_api_key_cache[cache_key] = True
        logger.debug("Invalid API key cached")

        # Track the invalid attempt
        try:
            # Check if we're in a request context
            if has_request_context():
                client_ip = get_real_ip()
            else:
                client_ip = "127.0.0.1"

            # Hash the API key for tracking (don't store plaintext)
            api_key_hash = hashlib.sha256(provided_api_key.encode()).hexdigest()[:16]

            # Track the invalid API key attempt
            InvalidAPIKeyTracker.track_invalid_api_key(client_ip, api_key_hash)

        except Exception as track_error:
            logger.warning(f"Could not track invalid API key attempt: {track_error}")

        return None
    except Exception as e:
        logger.exception(f"Error verifying API key: {e}")
        return None


def get_username_by_apikey(provided_api_key):
    """Get username for a given API key"""
    return verify_api_key(provided_api_key)


def get_broker_name(provided_api_key):
    """Get only the broker name for a valid API key with caching"""
    # Check if broker name is in cache
    if provided_api_key in broker_cache:
        return broker_cache[provided_api_key]

    # Not in cache, need to look it up
    user_id = verify_api_key(provided_api_key)

    if user_id:
        try:
            auth_obj = Auth.query.filter_by(name=user_id).first()
            if auth_obj and not auth_obj.is_revoked:
                # Cache the broker name
                broker_cache[provided_api_key] = auth_obj.broker
                return auth_obj.broker
            else:
                logger.warning(f"No valid broker found for user_id '{user_id}'.")
                return None
        except Exception as e:
            logger.exception(f"Error while querying the database for broker name: {e}")
            return None
    return None


def get_auth_token_broker(provided_api_key, include_feed_token=False):
    """
    Get auth token, feed token (optional) and broker for a valid API key with caching.

    Security measures:
    - Always checks is_revoked status (even for cached data)
    - Cache cleared on credential changes
    - TTL based on session expiry time
    """
    import hashlib

    # Generate cache key
    cache_key = f"{hashlib.sha256(provided_api_key.encode()).hexdigest()}_{include_feed_token}"

    # Check cache first (but still verify revocation status)
    if cache_key in auth_cache:
        cached_result = auth_cache[cache_key]
        # Security: Still check if auth is revoked even with cached data
        user_id = verify_api_key(provided_api_key)
        if user_id:
            try:
                auth_obj = Auth.query.filter_by(name=user_id).first()
                if auth_obj and auth_obj.is_revoked:
                    # Token was revoked, remove from cache
                    del auth_cache[cache_key]
                    logger.warning(f"Cached auth token was revoked for user_id '{user_id}'.")
                    return (None, None, None) if include_feed_token else (None, None)
                # Not revoked, return cached result
                logger.debug(f"Auth token retrieved from cache for user_id: {user_id}")
                return cached_result
            except Exception as e:
                logger.exception(f"Error checking revocation status: {e}")
                # On error, don't use cache
                del auth_cache[cache_key]

    # Cache miss or revocation check failed - fetch from database
    user_id = verify_api_key(provided_api_key)

    if user_id:
        try:
            auth_obj = Auth.query.filter_by(name=user_id).first()
            if auth_obj and not auth_obj.is_revoked:
                decrypted_token = decrypt_token(auth_obj.auth)
                if include_feed_token:
                    decrypted_feed_token = (
                        decrypt_token(auth_obj.feed_token) if auth_obj.feed_token else None
                    )
                    result = (decrypted_token, decrypted_feed_token, auth_obj.broker)
                else:
                    result = (decrypted_token, auth_obj.broker)

                # Cache the result
                auth_cache[cache_key] = result
                logger.debug(f"Auth token cached for user_id: {user_id}")
                return result
            else:
                # Cache the negative result to prevent repeated DB queries and log spam
                # (e.g., orphaned users with revoked sessions polled by background services)
                negative_result = (None, None, None) if include_feed_token else (None, None)
                auth_cache[cache_key] = negative_result
                logger.warning(f"No valid auth token or broker found for user_id '{user_id}'. Cached negative result.")
                return negative_result
        except Exception as e:
            logger.exception(f"Error while querying the database for auth token and broker: {e}")
            return (None, None, None) if include_feed_token else (None, None)
    else:
        return (None, None, None) if include_feed_token else (None, None)


def get_order_mode(user_id):
    """
    Get the order mode for a user (auto or semi_auto)

    Args:
        user_id: User identifier

    Returns:
        str: 'auto' or 'semi_auto', defaults to 'auto' if not set
    """
    cached_mode = order_mode_cache.get(user_id)
    if cached_mode is not None:
        return cached_mode

    try:
        api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
        mode = api_key_obj.order_mode if api_key_obj and api_key_obj.order_mode else "auto"
        order_mode_cache[user_id] = mode
        return mode
    except Exception as e:
        logger.exception(f"Error getting order mode for user {user_id}: {e}")
        return "auto"  # Default to auto on error


def update_order_mode(user_id, mode):
    """
    Update the order mode for a user

    Args:
        user_id: User identifier
        mode: 'auto' or 'semi_auto'

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        if mode not in ["auto", "semi_auto"]:
            logger.error(f"Invalid order mode: {mode}")
            return False

        api_key_obj = ApiKeys.query.filter_by(user_id=user_id).first()
        if api_key_obj:
            api_key_obj.order_mode = mode
            db_session.commit()

            # Clear caches when mode changes
            invalidate_user_cache(user_id)

            logger.info(f"Order mode updated to '{mode}' for user: {user_id}")
            return True
        else:
            logger.error(f"No API key found for user: {user_id}")
            return False
    except Exception as e:
        logger.exception(f"Error updating order mode: {e}")
        db_session.rollback()
        return False


# ============================================================
# Samco 2FA Helper Functions
# Uses dedicated columns on the Auth table:
#   secret_api_key, primary_ip, secondary_ip, ip_updated_at
# ============================================================


def _get_samco_auth(user_id):
    """Get the Auth record for a Samco user by name."""
    try:
        return Auth.query.filter_by(broker="samco", name=user_id).first()
    except Exception as e:
        logger.error(f"Error getting samco auth for {user_id}: {e}")
        return None


def samco_save_secret_key(user_id, secret_api_key):
    """Save or update the secret API key for a Samco user.
    Creates a placeholder auth record if one doesn't exist yet (pre-login setup).

    The secret_api_key is encrypted at rest with the auth_db Fernet (PBKDF2
    over API_KEY_PEPPER). Pre-migration rows containing plaintext are
    transparently handled by safe_decrypt_token on read.
    """
    try:
        record = _get_samco_auth(user_id)
        if not record:
            record = Auth(
                name=user_id,
                auth="pending",
                broker="samco",
                is_revoked=True,
            )
            db_session.add(record)
            logger.info(f"Created placeholder auth record for samco user {user_id}")
        record.secret_api_key = encrypt_token(secret_api_key) if secret_api_key else None
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error saving secret key for {user_id}: {e}")
        return False


def samco_get_ip_status(user_id):
    """Get IP registration status and whether editing is allowed."""
    from datetime import datetime, timedelta

    record = _get_samco_auth(user_id)
    if not record:
        return {
            "primary_ip": None,
            "secondary_ip": None,
            "editable": True,
            "ip_updated_at": None,
            "next_editable_date": None,
        }

    editable = True
    next_editable_date = None

    if record.ip_updated_at:
        now = datetime.utcnow()
        unlock_date = record.ip_updated_at + timedelta(days=7)
        if now < unlock_date:
            editable = False
            next_editable_date = unlock_date.strftime("%Y-%m-%d")

    return {
        "primary_ip": record.primary_ip,
        "secondary_ip": record.secondary_ip,
        "editable": editable,
        "ip_updated_at": record.ip_updated_at.isoformat() if record.ip_updated_at else None,
        "next_editable_date": next_editable_date,
    }


def samco_save_ip_info(user_id, primary_ip, secondary_ip=None, ip_updated_at=None):
    """Save IP registration info for a Samco user."""
    from datetime import datetime

    try:
        record = _get_samco_auth(user_id)
        if record:
            record.primary_ip = primary_ip
            record.secondary_ip = secondary_ip
            record.ip_updated_at = ip_updated_at or datetime.utcnow()
            db_session.commit()
            return True
        else:
            logger.error(f"No auth record found for samco user {user_id}")
            return False
    except Exception as e:
        db_session.rollback()
        logger.error(f"Error saving IP info for {user_id}: {e}")
        return False


def samco_has_secret_key(user_id):
    """Check if a Samco user has a secret API key stored."""
    record = _get_samco_auth(user_id)
    return record is not None and record.secret_api_key is not None


def samco_get_secret_key(user_id):
    """Get the stored secret API key for a Samco user (decrypted).

    Falls back to the raw column value if Fernet decryption fails — that's
    a pre-migration plaintext row, which keeps working until the operator
    runs upgrade/rotate_pepper.py.
    """
    record = _get_samco_auth(user_id)
    if record and record.secret_api_key:
        return safe_decrypt_token(record.secret_api_key)
    return None


def samco_has_registered_ip(user_id):
    """Check if a Samco user has registered IPs."""
    record = _get_samco_auth(user_id)
    return record is not None and record.primary_ip is not None
