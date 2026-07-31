# database/user_db.py

import os
import uuid as uuid_module
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone
    UTC = timezone.utc

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cachetools import TTLCache
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.sql import expression, func

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

# Initialize Argon2 hasher
ph = PasswordHasher()

# Database connection details
DATABASE_URL = os.getenv("DATABASE_URL")

# Security: Require API_KEY_PEPPER environment variable (fail fast if missing)
# Pepper must be at least 32 bytes (64 hex characters) for cryptographic security
_pepper_value = os.getenv("API_KEY_PEPPER")
if not _pepper_value:
    raise RuntimeError(
        "CRITICAL: API_KEY_PEPPER environment variable is not set. "
        "This is required for secure password hashing. "
        'Generate one using: python -c "import secrets; print(secrets.token_hex(32))"'
    )
if len(_pepper_value) < 32:
    raise RuntimeError(
        f"CRITICAL: API_KEY_PEPPER must be at least 32 characters (got {len(_pepper_value)}). "
        'Generate a secure pepper using: python -c "import secrets; print(secrets.token_hex(32))"'
    )
PASSWORD_PEPPER = _pepper_value

# Engine and session setup
engine = create_db_engine(DATABASE_URL, echo=False)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# Define a cache for the usernames with a max size and a 30-second TTL
username_cache = TTLCache(maxsize=1024, ttl=30)

# Short-lived record of just-consumed email verification tokens (token ->
# username), so a harmless repeat hit on the same link within a couple
# minutes of the first successful verification reports success again
# instead of "invalid or expired" -- see consume_email_verification_token().
# NOT a security boundary (the real single-use enforcement is the DB row
# deletion); this only smooths over duplicate requests for the same
# already-verified token.
_recently_verified_tokens = TTLCache(maxsize=256, ttl=120)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)  # Increased length for Argon2 hash
    # Widened from 32 -> 255 to fit Fernet ciphertext (~100 chars).
    # SQLite ignores VARCHAR length so existing rows are unaffected; the
    # change matters only on Postgres/MySQL.
    totp_secret = Column(String(255), nullable=False)  # Fernet-encrypted at rest
    is_admin = Column(Boolean, default=False)

    # ----- Public identity -----
    # `uuid` is the internal, never-displayed identifier -- generated once at
    # creation, used only for future cross-service references. `user_code`
    # (e.g. "MAX000123") is the support-facing public id, derived from the
    # existing autoincrement `id` (already unique + monotonic, so no separate
    # counter table is needed). `username`/`email` remain the ONLY identity
    # columns every other table in this app keys on (see auth_db.py,
    # strategy_db.py, sandbox_db.py, etc.) -- uuid/user_code are additive
    # display fields, not new foreign keys, by design (see CLAUDE.md /
    # architecture notes: repo-wide migration off username-keying is a
    # separate, later effort).
    uuid = Column(String(36), unique=True, nullable=True, index=True)
    user_code = Column(String(10), unique=True, nullable=True, index=True)

    # ----- Lifecycle -----
    # PENDING_VERIFICATION: self-service signup, email not yet confirmed.
    # ACTIVE: normal usable account (also the value for every pre-existing
    # row, backfilled by _backfill_identity_columns()).
    # SUSPENDED: admin-disabled; login is rejected before the password check.
    status = Column(String(20), nullable=False, default="ACTIVE", server_default="ACTIVE")
    email_verified = Column(Boolean, nullable=False, default=False, server_default=expression.false())
    created_at = Column(DateTime(timezone=True), nullable=True, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=True, default=func.now(), onupdate=func.now())
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    # ----- 2FA (TOTP) controls -----
    # ``totp_enabled`` is the master switch. When False, every per-purpose
    # flag below is ignored and the install behaves exactly as it did
    # before this feature landed (password-only login, existing reset
    # options, no extra MCP gate). When True, the user picks which
    # purposes the second factor applies to.
    #
    # Defaults are False so existing installs are not silently locked out.
    # The settings UI surfaces the three purpose toggles together when the
    # master is on; flipping master off does NOT clear the purpose flags
    # so the user's preferences are remembered if they re-enable later.
    totp_enabled = Column(Boolean, default=False, nullable=False)
    totp_required_for_login = Column(Boolean, default=False, nullable=False)
    totp_required_for_mcp = Column(Boolean, default=False, nullable=False)
    totp_required_for_password_reset = Column(Boolean, default=False, nullable=False)
    # SEBI's algo trading circular requires 2FA for API access. This flag
    # lets a user opt into requiring TOTP to regenerate their API key
    # (blueprints/apikey.py's generate_api_key route) -- defaults to False,
    # same non-breaking opt-in pattern as the other purposes, so existing
    # installs/users are never silently locked out of a key they already
    # depend on. Note: SEBI's requirement is for this to be MANDATORY, not
    # opt-in; making it mandatory platform-wide is a deliberate product/
    # rollout decision deferred to the operator (see the compliance
    # findings doc), not something this flag defaulting to True would be
    # safe to force silently.
    totp_required_for_api_key = Column(Boolean, default=False, nullable=False)

    def is_totp_required_for(self, purpose: str) -> bool:
        """Return True if 2FA is enabled AND required for this purpose.

        ``purpose`` must be one of: ``"login"``, ``"mcp"``,
        ``"password_reset"``, ``"api_key"``. Unknown purposes return False
        (fail-open for purposes the caller hasn't explicitly opted in —
        defense against drift between callers and config).
        """
        if not self.totp_enabled:
            return False
        flag = {
            "login": self.totp_required_for_login,
            "mcp": self.totp_required_for_mcp,
            "password_reset": self.totp_required_for_password_reset,
            "api_key": self.totp_required_for_api_key,
        }.get(purpose, False)
        return bool(flag)

    def get_totp_secret(self):
        """Return the user's TOTP secret in plaintext.

        Encrypted-at-rest with auth_db Fernet (PBKDF2 over API_KEY_PEPPER).
        Pre-migration plaintext rows are transparently handled by
        safe_decrypt_token's fallback. This is the only correct way to read
        the secret — never use ``self.totp_secret`` directly outside this
        class, since that returns the raw column value (ciphertext or stale
        plaintext).
        """
        from database.auth_db import safe_decrypt_token
        return safe_decrypt_token(self.totp_secret) or self.totp_secret

    def set_password(self, password):
        """Hash password using Argon2 with pepper"""
        peppered_password = password + PASSWORD_PEPPER
        self.password_hash = ph.hash(peppered_password)

    def check_password(self, password):
        """Verify password using Argon2 with pepper, with fallbacks for unpeppered and legacy hashes."""
        if not password or not self.password_hash:
            return False

        peppered_password = password + PASSWORD_PEPPER
        try:
            ph.verify(self.password_hash, peppered_password)
            if ph.check_needs_rehash(self.password_hash):
                self.set_password(password)
                db_session.commit()
            return True
        except VerifyMismatchError:
            pass
        except Exception as e:
            logger.warning(f"Argon2 peppered verify failed for {self.username}: {e}")

        # Fallback 1: Unpeppered Argon2 hash
        try:
            ph.verify(self.password_hash, password)
            self.set_password(password)
            db_session.commit()
            return True
        except Exception:
            pass

        # Fallback 2: Werkzeug check_password_hash (legacy werkzeug scrypt/pbkdf2 hashes)
        try:
            from werkzeug.security import check_password_hash as _werkzeug_check
            if _werkzeug_check(self.password_hash, password):
                self.set_password(password)
                db_session.commit()
                return True
        except Exception:
            pass

        return False

    def get_totp_uri(self):
        """Get the TOTP URI for QR code generation"""
        return pyotp.totp.TOTP(self.get_totp_secret()).provisioning_uri(
            name=self.email, issuer_name="Max Algos"
        )

    def verify_totp(self, token):
        """Verify TOTP token.

        valid_window=1 accepts the previous/current/next 30s step (90s total)
        to tolerate normal clock drift on the user's authenticator app and
        input latency near a window boundary — pyotp's default of 0 requires
        an exact match to the current server-side step, which is stricter
        than what Google/GitHub-style TOTP implementations use.
        """
        totp = pyotp.TOTP(self.get_totp_secret())
        return totp.verify(token, valid_window=1)

    def to_public_dict(self):
        """Fields safe to show the user themselves (never includes uuid)."""
        return {
            "user_code": self.user_code,
            "username": self.username,
            "email": self.email,
            "status": self.status,
            "email_verified": bool(self.email_verified),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


class UserBrokerCredential(Base):
    """Model for storing user-specific broker credentials securely.

    One row per (username, broker_name) - a user can hold saved credentials
    for multiple brokers simultaneously without one overwriting another.
    """
    __tablename__ = "user_broker_credentials"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False)
    broker_name = Column(String(20), nullable=False)
    broker_api_key = Column(Text, nullable=True)          # Encrypted at rest
    broker_api_secret = Column(Text, nullable=True)       # Encrypted at rest
    broker_api_key_market = Column(Text, nullable=True)   # Encrypted at rest
    broker_api_secret_market = Column(Text, nullable=True) # Encrypted at rest
    redirect_url = Column(Text, nullable=True)

    # ----- Auto session refresh (opt-in, password+TOTP brokers only) -----
    # See docs/plans/2026-07-16-broker-auto-session-refresh-plan.md.
    # SECURITY: totp_seed_encrypted stores the user's broker 2FA seed so the
    # platform can generate codes and re-authenticate unattended each
    # morning (broker tokens die ~3 AM IST). This is a deliberate,
    # explicitly-opted-in tradeoff -- storing a 2FA seed is against most
    # brokers' ToS and a breach exposes unattended trading access. Encrypted
    # at rest with the same Fernet(PBKDF2 over API_KEY_PEPPER) scheme as the
    # other credential fields. Default off; only the 5 in-scope brokers
    # (angel, fivepaisa, motilal, shoonya, zebu) ever expose the opt-in.
    totp_seed_encrypted = Column(Text, nullable=True)
    # Encrypted JSON of the non-TOTP login params each broker needs:
    #   angel/fivepaisa -> {"clientcode": ..., "pin": ...}
    #   motilal         -> {"userid": ..., "pin": ..., "dob": ...}
    # Stored as one encrypted blob rather than a column-per-field so the
    # schema doesn't need a new column every time a broker wants a slightly
    # different param set.
    auto_login_params_encrypted = Column(Text, nullable=True)
    auto_refresh_enabled = Column(Boolean, default=False, nullable=False, server_default=expression.false())
    auto_refresh_last_status = Column(String(20), nullable=True)  # 'success' | 'failed' | None
    auto_refresh_last_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("username", "broker_name", name="uq_user_broker_credential"),
    )


class EmailVerification(Base):
    """Signup email-verification tokens. One row per outstanding token; the
    row is deleted once consumed (see consume_email_verification_token)."""
    __tablename__ = "email_verifications"
    id = Column(Integer, primary_key=True)
    username = Column(String(80), nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)


class PlatformSubscription(Base):
    """Whole-platform recurring subscription (distinct from
    strategy_db.py's Subscription, which is marketplace-strategy-scoped).
    One row per Razorpay subscription; `user_id` is the username string for
    consistency with every other table in this app (see database/auth_db.py
    and friends -- all keyed by username, not User.id)."""
    __tablename__ = "platform_subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=False, index=True)
    razorpay_subscription_id = Column(String(64), unique=True, nullable=False, index=True)
    plan = Column(String(50), nullable=False, default="default")
    # created -> pending Razorpay activation (first charge not yet captured)
    # active -> usable, gates login
    # past_due -> a renewal charge failed; grace period, still gates as active
    #             until explicitly cancelled (kept simple for this phase)
    # cancelled -> no longer gates login as active
    status = Column(String(20), nullable=False, default="created")
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())


def get_user_broker_credentials(username: str, broker_name: str) -> dict:
    """Get decrypted broker credentials for a user's specific broker."""
    try:
        cred = UserBrokerCredential.query.filter_by(
            username=username, broker_name=broker_name
        ).first()
        if not cred:
            return {}

        from database.auth_db import decrypt_token
        def decrypt_val(val):
            if not val:
                return ""
            try:
                return decrypt_token(val)
            except Exception:
                return val

        return {
            "broker_api_key": decrypt_val(cred.broker_api_key),
            "broker_api_secret": decrypt_val(cred.broker_api_secret),
            "broker_api_key_market": decrypt_val(cred.broker_api_key_market),
            "broker_api_secret_market": decrypt_val(cred.broker_api_secret_market),
            "redirect_url": cred.redirect_url or "",
        }
    except Exception as e:
        logger.exception(f"Error fetching user broker credentials for {username}/{broker_name}: {e}")
        return {}


def list_user_broker_credentials(username: str) -> list[str]:
    """Return the list of broker names this user has saved credentials for
    (no secret material - just which brokers). Used by the Broker
    Management page to show "brokers you've configured"."""
    try:
        rows = UserBrokerCredential.query.filter_by(username=username).all()
        return [r.broker_name for r in rows]
    except Exception as e:
        logger.exception(f"Error listing broker credentials for {username}: {e}")
        return []


def update_user_broker_credentials(username: str, broker_name: str, data: dict) -> bool:
    """Create or update encrypted broker credentials for a user's specific broker."""
    try:
        from database.auth_db import encrypt_token
        def encrypt_val(val):
            if not val:
                return None
            return encrypt_token(val)

        cred = UserBrokerCredential.query.filter_by(
            username=username, broker_name=broker_name
        ).first()

        broker_api_key = encrypt_val(data.get("broker_api_key"))
        broker_api_secret = encrypt_val(data.get("broker_api_secret"))
        broker_api_key_market = encrypt_val(data.get("broker_api_key_market"))
        broker_api_secret_market = encrypt_val(data.get("broker_api_secret_market"))
        redirect_url = data.get("redirect_url")

        if cred:
            # Only update if key/secret are provided (not empty or masked placeholders)
            if data.get("broker_api_key") and not data.get("broker_api_key").endswith("********"):
                cred.broker_api_key = broker_api_key
            if data.get("broker_api_secret") and not data.get("broker_api_secret").endswith("********"):
                cred.broker_api_secret = broker_api_secret
            if data.get("broker_api_key_market") and not data.get("broker_api_key_market").endswith("********"):
                cred.broker_api_key_market = broker_api_key_market
            if data.get("broker_api_secret_market") and not data.get("broker_api_secret_market").endswith("********"):
                cred.broker_api_secret_market = broker_api_secret_market
            if redirect_url is not None:
                cred.redirect_url = redirect_url
        else:
            cred = UserBrokerCredential(
                username=username,
                broker_name=broker_name,
                broker_api_key=broker_api_key,
                broker_api_secret=broker_api_secret,
                broker_api_key_market=broker_api_key_market,
                broker_api_secret_market=broker_api_secret_market,
                redirect_url=redirect_url,
            )
            db_session.add(cred)

        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error updating user broker credentials for {username}/{broker_name}: {e}")
        return False


# Brokers where unattended daily re-auth is architecturally possible:
# their authenticate_broker() takes clientcode + PIN + TOTP directly (a
# real password login), so the platform can generate the TOTP from a
# stored seed and re-auth with no browser. Verified against each broker's
# actual auth_api.py:
#   angel     -> (clientcode, broker_pin, totp_code)
#   fivepaisa -> (clientcode, broker_pin, totp_code)
#   motilal   -> (userid, broker_pin, totp_code, date_of_birth)
# NOTE: shoonya and zebu were in the original plan but turned out to use
# the Noren OAuth GenAcsTok flow (authenticate_broker(code) where `code`
# comes from an interactive redirect) -- NOT direct password+TOTP -- so
# they are NOT auto-refreshable and are deliberately excluded. Every other
# broker likewise requires an interactive login each day.
AUTO_REFRESH_SUPPORTED_BROKERS = ("angel", "fivepaisa", "motilal")


def is_auto_refresh_supported(broker_name: str) -> bool:
    return broker_name in AUTO_REFRESH_SUPPORTED_BROKERS


def enable_broker_auto_refresh(
    username: str, broker_name: str, totp_seed: str, login_params: dict
) -> bool:
    """Store the encrypted TOTP seed + broker-specific login params and turn
    on auto-refresh for this (user, broker). Only permitted for supported
    brokers. The row must already exist (user has saved API credentials
    first). ``login_params`` is the non-TOTP field set the broker's
    authenticate_broker() needs (clientcode/userid, pin, dob)."""
    if not is_auto_refresh_supported(broker_name):
        logger.warning(f"Auto-refresh not supported for broker {broker_name}; refusing to enable")
        return False
    try:
        import json

        from database.auth_db import encrypt_token

        cred = UserBrokerCredential.query.filter_by(
            username=username, broker_name=broker_name
        ).first()
        if not cred:
            logger.warning(
                f"Cannot enable auto-refresh for {username}/{broker_name}: no saved credentials"
            )
            return False
        cred.totp_seed_encrypted = encrypt_token(totp_seed) if totp_seed else None
        cred.auto_login_params_encrypted = (
            encrypt_token(json.dumps(login_params)) if login_params else None
        )
        cred.auto_refresh_enabled = True
        cred.auto_refresh_last_status = None
        cred.auto_refresh_last_at = None
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error enabling auto-refresh for {username}/{broker_name}: {e}")
        return False


def disable_broker_auto_refresh(username: str, broker_name: str) -> bool:
    """Turn off auto-refresh and CLEAR the stored seed/params (don't just
    flip the flag -- once disabled, the sensitive material shouldn't
    linger)."""
    try:
        cred = UserBrokerCredential.query.filter_by(
            username=username, broker_name=broker_name
        ).first()
        if not cred:
            return True  # nothing to disable
        cred.totp_seed_encrypted = None
        cred.auto_login_params_encrypted = None
        cred.auto_refresh_enabled = False
        db_session.commit()
        return True
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error disabling auto-refresh for {username}/{broker_name}: {e}")
        return False


def get_broker_auto_refresh_secrets(username: str, broker_name: str) -> dict | None:
    """Return the DECRYPTED seed + login params for a re-auth attempt.
    Returns None if auto-refresh isn't enabled or the material is missing.
    Internal use only (the auto-refresh service) -- never exposed via any
    API response."""
    try:
        cred = UserBrokerCredential.query.filter_by(
            username=username, broker_name=broker_name
        ).first()
        if not cred or not cred.auto_refresh_enabled or not cred.totp_seed_encrypted:
            return None
        import json

        from database.auth_db import decrypt_token

        params = {}
        if cred.auto_login_params_encrypted:
            try:
                params = json.loads(decrypt_token(cred.auto_login_params_encrypted))
            except Exception:
                params = {}
        return {
            "totp_seed": decrypt_token(cred.totp_seed_encrypted),
            "login_params": params,
        }
    except Exception as e:
        logger.exception(f"Error reading auto-refresh secrets for {username}/{broker_name}: {e}")
        return None


def get_broker_auto_refresh_status(username: str, broker_name: str) -> dict:
    """Non-secret status for the UI: whether it's enabled, and the last
    attempt's outcome/time. Never returns the seed or PIN."""
    try:
        cred = UserBrokerCredential.query.filter_by(
            username=username, broker_name=broker_name
        ).first()
        if not cred:
            return {"enabled": False, "supported": is_auto_refresh_supported(broker_name)}
        return {
            "enabled": bool(cred.auto_refresh_enabled),
            "supported": is_auto_refresh_supported(broker_name),
            "last_status": cred.auto_refresh_last_status,
            "last_at": cred.auto_refresh_last_at.isoformat() if cred.auto_refresh_last_at else None,
        }
    except Exception as e:
        logger.exception(f"Error reading auto-refresh status for {username}/{broker_name}: {e}")
        return {"enabled": False, "supported": is_auto_refresh_supported(broker_name)}


def record_auto_refresh_result(username: str, broker_name: str, success: bool) -> None:
    """Stamp the outcome of an auto-refresh attempt (for the UI + audit)."""
    from datetime import datetime

    try:
        cred = UserBrokerCredential.query.filter_by(
            username=username, broker_name=broker_name
        ).first()
        if not cred:
            return
        cred.auto_refresh_last_status = "success" if success else "failed"
        cred.auto_refresh_last_at = datetime.now(UTC)
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Error recording auto-refresh result for {username}/{broker_name}: {e}")


def list_enabled_auto_refresh_credentials() -> list[dict]:
    """Return [{username, broker_name}] for every row with auto-refresh on.
    Used by the scheduled job to know which sessions to refresh. No secret
    material returned -- the service fetches that per-row via
    get_broker_auto_refresh_secrets()."""
    try:
        rows = UserBrokerCredential.query.filter_by(auto_refresh_enabled=True).all()
        return [{"username": r.username, "broker_name": r.broker_name} for r in rows]
    except Exception as e:
        logger.exception(f"Error listing auto-refresh-enabled credentials: {e}")
        return []


def _ensure_broker_name_column():
    """Idempotent, in-place migration so a plain restart always brings the
    user_broker_credentials schema up to date - no separate migration step.

    Older deployments stored one credential row per username (unique on
    username alone, no broker_name column). Multi-broker support needs one
    row per (username, broker_name). This:

      1. Adds the broker_name column if missing.
      2. Backfills existing rows' broker_name from their redirect_url
         (".../zebu/callback" -> "zebu"), falling back to "unknown" rather
         than dropping any credential data.
      3. Rebuilds the table with the (username, broker_name) UNIQUE
         constraint (SQLite can't ALTER a UNIQUE constraint in place).

    Safe to run on every boot: if broker_name already exists it returns
    immediately. Only touches user_broker_credentials - never any other
    table. Failures are logged but never crash startup (the app can still
    boot; saves just keep failing until the schema is fixed, same as
    before this hook existed).
    """
    import re

    from sqlalchemy import inspect, text

    try:
        inspector = inspect(engine)
        if "user_broker_credentials" not in inspector.get_table_names():
            # Table not created yet (fresh DB). create_all below (via
            # init_db_with_logging) builds it with the correct schema.
            return

        columns = [c["name"] for c in inspector.get_columns("user_broker_credentials")]
        if "broker_name" in columns:
            return  # already migrated

        if engine.dialect.name != "sqlite":
            # The rename-recreate-copy-drop rebuild below is a SQLite-only
            # workaround for lack of native ALTER TABLE ... ALTER/DROP COLUMN.
            # A non-SQLite install upgrading from a pre-broker_name schema
            # should go through an Alembic migration instead, which can use
            # a plain ALTER TABLE ... ADD COLUMN + UNIQUE constraint directly.
            logger.warning(
                "user_broker_credentials predates broker_name on a non-SQLite "
                "database; skipping the SQLite-specific rebuild. Run the "
                "Alembic migration for this schema change instead."
            )
            return

        logger.info("Migrating user_broker_credentials -> (username, broker_name) schema...")

        def broker_from_redirect(url):
            if not url:
                return None
            m = re.search(r"/([^/]+)/callback$", url)
            return m.group(1).lower() if m else None

        with engine.connect() as conn:
            conn.execute(
                text("ALTER TABLE user_broker_credentials ADD COLUMN broker_name VARCHAR(20)")
            )
            conn.commit()

            rows = conn.execute(
                text("SELECT id, redirect_url FROM user_broker_credentials")
            ).fetchall()
            for row_id, redirect_url in rows:
                broker = broker_from_redirect(redirect_url) or "unknown"
                conn.execute(
                    text("UPDATE user_broker_credentials SET broker_name = :b WHERE id = :i"),
                    {"b": broker, "i": row_id},
                )
            conn.commit()

            # Rebuild with the composite UNIQUE constraint (rename-recreate-copy-drop).
            conn.execute(
                text("ALTER TABLE user_broker_credentials RENAME TO user_broker_credentials_old")
            )
            conn.commit()
            conn.execute(text("""
                CREATE TABLE user_broker_credentials (
                    id INTEGER NOT NULL,
                    username VARCHAR(80) NOT NULL,
                    broker_name VARCHAR(20) NOT NULL,
                    broker_api_key TEXT,
                    broker_api_secret TEXT,
                    broker_api_key_market TEXT,
                    broker_api_secret_market TEXT,
                    redirect_url TEXT,
                    PRIMARY KEY (id),
                    CONSTRAINT uq_user_broker_credential UNIQUE (username, broker_name)
                )
            """))
            conn.execute(text("""
                INSERT INTO user_broker_credentials
                    (id, username, broker_name, broker_api_key, broker_api_secret,
                     broker_api_key_market, broker_api_secret_market, redirect_url)
                SELECT id, username, broker_name, broker_api_key, broker_api_secret,
                       broker_api_key_market, broker_api_secret_market, redirect_url
                FROM user_broker_credentials_old
            """))
            conn.execute(text("DROP TABLE user_broker_credentials_old"))
            conn.commit()

        logger.info("user_broker_credentials migration complete.")
    except Exception as e:
        logger.exception(f"Failed migrating user_broker_credentials schema: {e}")


def _ensure_user_identity_columns():
    """Idempotent, in-place migration adding the new identity/lifecycle
    columns to `users` for installs upgrading from before this feature, then
    backfilling uuid/user_code/created_at/status for any existing rows that
    lack them. Safe to run on every boot -- no-ops once columns exist and
    every row is backfilled.
    """
    from sqlalchemy import inspect, text

    try:
        inspector = inspect(engine)
        if "users" not in inspector.get_table_names():
            return  # fresh DB - create_all() above already includes the new columns

        columns = {c["name"] for c in inspector.get_columns("users")}
        new_columns = {
            "uuid": "VARCHAR(36)",
            "user_code": "VARCHAR(10)",
            "status": "VARCHAR(20)",
            "email_verified": "BOOLEAN",
            "created_at": "DATETIME",
            "updated_at": "DATETIME",
            "last_login_at": "DATETIME",
            # SEBI algo-trading 2FA-for-API-access requirement -- see
            # totp_required_for_api_key's docstring on the User model above.
            "totp_required_for_api_key": "BOOLEAN DEFAULT 0",
        }
        missing = {name: ddl for name, ddl in new_columns.items() if name not in columns}

        if missing:
            logger.info(f"Migrating users table: adding columns {list(missing)}")
            with engine.connect() as conn:
                for name, ddl in missing.items():
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
                conn.commit()

        # Backfill rows lacking uuid/user_code/status/created_at (either
        # freshly-added columns above, or rows from before this migration
        # first ran).
        rows = User.query.filter(
            (User.uuid.is_(None)) | (User.user_code.is_(None)) | (User.status.is_(None))
        ).all()
        for user in rows:
            if not user.uuid:
                user.uuid = str(uuid_module.uuid4())
            if not user.user_code:
                user.user_code = f"MAX{user.id:06d}"
            if not user.status:
                user.status = "ACTIVE"
            if user.email_verified is None:
                user.email_verified = True  # pre-existing accounts are trusted
        if rows:
            db_session.commit()
            logger.info(f"Backfilled identity columns for {len(rows)} existing user(s)")
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Failed migrating users identity columns: {e}")


def _ensure_broker_auto_refresh_columns():
    """Idempotent additive migration adding the auto-session-refresh columns
    to user_broker_credentials (all nullable/defaulted, so a plain
    ADD COLUMN suffices -- no table rebuild). See
    docs/plans/2026-07-16-broker-auto-session-refresh-plan.md. Safe on every
    boot; no-ops once the columns exist."""
    from sqlalchemy import inspect, text

    try:
        inspector = inspect(engine)
        if "user_broker_credentials" not in inspector.get_table_names():
            return  # fresh DB; create_all builds the full schema
        columns = {c["name"] for c in inspector.get_columns("user_broker_credentials")}
        new_columns = {
            "totp_seed_encrypted": "TEXT",
            "auto_login_params_encrypted": "TEXT",
            "auto_refresh_enabled": "BOOLEAN DEFAULT 0",
            "auto_refresh_last_status": "VARCHAR(20)",
            "auto_refresh_last_at": "DATETIME",
        }
        missing = {n: d for n, d in new_columns.items() if n not in columns}
        if not missing:
            return
        logger.info(
            f"Migrating user_broker_credentials: adding {len(missing)} auto-refresh column(s)..."
        )
        with engine.connect() as conn:
            for name, ddl in missing.items():
                conn.execute(
                    text(f"ALTER TABLE user_broker_credentials ADD COLUMN {name} {ddl}")
                )
            conn.commit()
    except Exception as e:
        logger.exception(f"Failed migrating user_broker_credentials auto-refresh columns: {e}")


def init_db():
    """Initialize the user database tables.

    Creates the ``users`` table if it does not already exist,
    using the shared ``db_init_helper`` for consistent startup
    logging. Also runs the idempotent (username, broker_name) migration
    and the identity-columns backfill so a plain restart self-heals the
    schema without a manual step.
    """
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "User DB", logger)
    _ensure_broker_name_column()
    _ensure_user_identity_columns()
    _ensure_broker_auto_refresh_columns()


def add_user(username, email, password, is_admin=False, status="ACTIVE", email_verified=True):
    """Create a new user with a securely hashed password.

    Hashes the provided password, generates a two-factor authentication
    secret, and persists the new user record to the database.

    Args:
        username: Unique username for the new account.
        email: Unique email address for the new account.
        password: Plaintext password (will be hashed before storage).
        is_admin: Whether the user should have administrator privileges.
        status: Initial lifecycle status. Self-service registration passes
            "PENDING_VERIFICATION"; the /setup admin-bootstrap flow and
            admin-created users keep the default "ACTIVE".
        email_verified: Whether the email is considered verified already.
            Self-service registration passes False until the link is clicked.

    Returns:
        The newly created ``User`` instance on success, or ``None``
        if a user with the same username or email already exists.
    """
    try:
        # Generate TOTP secret and store it encrypted at rest using the
        # auth_db Fernet (same pattern used for broker tokens, API keys).
        # See _totp_plaintext() for the read path.
        from database.auth_db import encrypt_token
        totp_secret = pyotp.random_base32()
        user = User(
            username=username,
            email=email,
            totp_secret=encrypt_token(totp_secret),
            is_admin=is_admin,
            uuid=str(uuid_module.uuid4()),
            status=status,
            email_verified=email_verified,
        )
        user.set_password(password)
        db_session.add(user)
        db_session.flush()  # assigns user.id without committing
        user.user_code = f"MAX{user.id:06d}"
        db_session.commit()
        return user  # Return the user object instead of True
    except IntegrityError:
        db_session.rollback()
        return None  # Return None instead of False


def authenticate_user(username, password):
    """Authenticate user with Argon2 hashed password (supports username or email, case-insensitive)"""
    if not username or not password:
        return False

    user = find_user_by_login_identifier(username)
    if user and user.check_password(password):
        return True
    return False


def find_user_by_email(email):
    """Find user by email for password reset"""
    if not email:
        return None
    from sqlalchemy import func
    return User.query.filter(func.lower(User.email) == email.strip().lower()).first()


def find_user_by_username():
    """Find admin user"""
    return User.query.filter_by(is_admin=True).first()


def find_user_by_exact_username(username):
    """Look up a user by exact username match. Returns None if not found."""
    if not username:
        return None
    from sqlalchemy import func
    user = User.query.filter_by(username=username.strip()).first()
    if user:
        return user
    return User.query.filter(func.lower(User.username) == username.strip().lower()).first()


def find_user_by_login_identifier(identifier):
    """Look up a user by username OR email (case-insensitive)."""
    if not identifier:
        return None
    from sqlalchemy import func
    clean_id = identifier.strip().lower()

    # Exact username match first
    user = User.query.filter_by(username=identifier.strip()).first()
    if user:
        return user
    # Exact email match second
    user = User.query.filter_by(email=identifier.strip()).first()
    if user:
        return user

    # Case-insensitive username match
    user = User.query.filter(func.lower(User.username) == clean_id).first()
    if user:
        return user
    # Case-insensitive email match
    return User.query.filter(func.lower(User.email) == clean_id).first()


def create_email_verification_token(username: str, ttl_hours: int = 24) -> str:
    """Create (and persist) a fresh verification token for a pending
    signup. Any previous outstanding tokens for this username are removed
    first so only one link is ever valid at a time."""
    import secrets
    from datetime import datetime, timedelta

    EmailVerification.query.filter_by(username=username).delete()

    token = secrets.token_urlsafe(32)
    record = EmailVerification(
        username=username,
        token=token,
        expires_at=datetime.utcnow() + timedelta(hours=ttl_hours),
    )
    db_session.add(record)
    db_session.commit()
    return token


def consume_email_verification_token(token: str):
    """Validate and consume a verification token. On success, marks the
    owning user ACTIVE + email_verified and deletes the token row so it
    cannot be replayed. Returns the User on success, None on genuinely
    invalid/expired token.

    Recently-consumed tokens are tracked separately from "never existed" /
    "expired" so a second hit on the SAME link reports success again
    instead of a scary "invalid" error -- this happens routinely in
    practice: React effect double-fires in dev, the same link opened in two
    browser tabs, an email client's link-prescanning bot visiting the URL
    before the user ever clicks it, or the user just clicking twice. The
    token itself is still deleted on first use (so a leaked/forwarded link
    cannot be replayed indefinitely); _RECENT_VERIFICATIONS is a small,
    short-lived in-process cache of token -> username used only to answer
    "was this token JUST consumed successfully" for the harmless-repeat
    case, not a security boundary.
    """
    from datetime import datetime

    record = EmailVerification.query.filter_by(token=token).first()
    if not record:
        recent_username = _recently_verified_tokens.get(token)
        if recent_username:
            return find_user_by_exact_username(recent_username)
        return None
    if record.expires_at < datetime.utcnow():
        db_session.delete(record)
        db_session.commit()
        return None

    user = find_user_by_exact_username(record.username)
    if not user:
        db_session.delete(record)
        db_session.commit()
        return None

    user.email_verified = True
    if user.status == "PENDING_VERIFICATION":
        user.status = "ACTIVE"
    db_session.delete(record)
    db_session.commit()
    _recently_verified_tokens[token] = record.username
    return user


def get_active_platform_subscription(username: str):
    """Return the user's PlatformSubscription row if its status is
    "active"/"past_due" (past_due still gates as usable for this phase --
    see PlatformSubscription.status docstring), else None."""
    return PlatformSubscription.query.filter(
        PlatformSubscription.user_id == username,
        PlatformSubscription.status.in_(("active", "past_due")),
    ).first()


def rehash_all_passwords():
    """
    Utility function to rehash all existing passwords with Argon2.
    This should be called once when upgrading from the old hashing method.
    Requires knowing the original passwords or having users reset them.
    """
    users = User.query.all()
    for user in users:
        if user.password_hash.startswith("pbkdf2:sha256"):  # Old Werkzeug format
            # At this point, you would either:
            # 1. Have users reset their passwords
            # 2. Or if you have access to original passwords (during migration):
            #    user.set_password(original_password)
            pass
    db_session.commit()
