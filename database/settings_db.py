# database/settings_db.py

import base64
import os
import threading
from datetime import UTC, datetime, timedelta, timezone

from cachetools import TTLCache
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Text,
    inspect,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.auth_db import PEPPER
from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

# Settings cache - 1 hour TTL (settings rarely change)
# This cache significantly reduces DB queries since get_analyze_mode() is called on every request
_settings_cache = TTLCache(maxsize=10, ttl=3600)  # 1 hour TTL

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_db_engine(DATABASE_URL)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    analyze_mode = Column(Boolean, default=False)  # Default to Live Mode

    # SMTP Configuration -- transport only (server/port/credentials/TLS).
    # Deliberately does NOT include which "From" address to use for any
    # given email; that is a separate concern (see Platform Email
    # Identities below) so a single mailbox (e.g. Microsoft 365
    # md@maxalgos.com) can send as noreply@/security@/billing@ aliases
    # without needing a separate SMTP login per alias.
    smtp_server = Column(String(255), nullable=True)
    smtp_port = Column(Integer, nullable=True)
    smtp_username = Column(String(255), nullable=True)
    smtp_password_encrypted = Column(Text, nullable=True)  # Encrypted SMTP password
    smtp_use_tls = Column(Boolean, default=True)
    smtp_from_email = Column(String(255), nullable=True)
    smtp_helo_hostname = Column(String(255), nullable=True)  # HELO/EHLO hostname

    # Platform Email Identities -- which "From" address each category of
    # outbound email uses, all sent through the single SMTP transport
    # above. Any identity left blank falls back to smtp_email_default (or
    # smtp_from_email if even that's unset, for pre-refactor installs).
    smtp_email_default = Column(String(255), nullable=True)
    smtp_email_verification = Column(String(255), nullable=True)
    smtp_email_security = Column(String(255), nullable=True)
    smtp_email_billing = Column(String(255), nullable=True)
    smtp_email_notifications = Column(String(255), nullable=True)
    smtp_email_reply_to = Column(String(255), nullable=True)

    # Security Settings
    security_auto_ban_enabled = Column(Boolean, default=False)  # Auto-ban disabled by default
    security_404_threshold = Column(Integer, default=100)  # 404 errors per day before ban
    security_404_ban_duration = Column(Integer, default=0)  # 0 = permanent ban
    security_api_threshold = Column(Integer, default=100)  # Invalid API attempts before ban
    security_api_ban_duration = Column(Integer, default=0)  # 0 = permanent ban
    security_repeat_offender_limit = Column(Integer, default=2)  # Bans before permanent ban

    # Payment Settings (Razorpay) — amounts stored in paise (integer) to
    # avoid float rounding issues with money, matching Razorpay's own API.
    payments_enabled = Column(Boolean, default=True)  # Admin kill-switch
    setup_fee_paise = Column(Integer, default=129900)  # One-time install activation fee (₹1299)
    default_subscription_price_paise = Column(Integer, default=49900)  # Default marketplace listing price (₹499)

    # Whole-platform recurring subscription (distinct from the marketplace
    # per-strategy price above). References a Razorpay Plan created via the
    # Razorpay dashboard/API -- the plan itself defines amount + interval,
    # this column just tells the platform which plan to subscribe users to.
    platform_subscription_plan_id = Column(String(64), nullable=True)

    # Razorpay API credentials, admin-configurable from the Payment Settings
    # panel rather than only via .env (see services/razorpay_service.py,
    # which reads these with an env-var fallback for installs that still
    # prefer the .env path). key_id is not secret (Razorpay's own JS
    # Checkout SDK exposes it client-side) so it's stored plain; key_secret
    # and webhook_secret are encrypted at rest with the same Fernet
    # convention as the SMTP password below.
    razorpay_key_id = Column(String(64), nullable=True)
    razorpay_key_secret_encrypted = Column(Text, nullable=True)
    razorpay_webhook_secret_encrypted = Column(Text, nullable=True)

    # Kill switch (SEBI-adjacent platform-level emergency stop -- see
    # docs/plans/2026-04-24-kill-switch-implementation-plan.md). Master flag
    # plus activation metadata; the audit trail of every activation/
    # deactivation event lives in the separate KillSwitchAudit table below so
    # this row stays a single small "current state" record.
    kill_switch_active = Column(Boolean, default=False)
    kill_switch_activated_at = Column(DateTime(timezone=True), nullable=True)
    kill_switch_activated_by = Column(String(50), nullable=True)  # 'ui' | 'api' | 'telegram'
    kill_switch_reason = Column(String(500), nullable=True)
    kill_switch_min_unlock_at = Column(DateTime(timezone=True), nullable=True)
    # User-configurable scope: which cleanup steps actually run on
    # activation. Both default True (stop everything) -- strategy/flow
    # stopping is NOT toggleable here; it always runs regardless of these.
    kill_switch_cancel_orders_enabled = Column(Boolean, default=True)
    kill_switch_close_positions_enabled = Column(Boolean, default=True)

    # Master Target / Master SL -- account-wide combined P&L auto-exit for
    # scalpers running multiple simultaneous positions. Distinct from any
    # per-order SL/target the broker itself enforces: this sums `pnl` across
    # every OPEN position (every connected broker, live only -- see
    # services/master_risk_monitor_service.py) and closes everything the
    # moment the combined total crosses either threshold. Values are plain
    # rupee amounts (not percentage), since scalpers think in absolute risk
    # ("stop me out at -5000"), not percentage of capital.
    master_risk_enabled = Column(Boolean, default=False)
    master_risk_sl_value = Column(Float, nullable=True)  # e.g. 5000 = close all at -5000 combined P&L
    master_risk_target_value = Column(Float, nullable=True)  # e.g. 10000 = close all at +10000 combined P&L
    master_risk_triggered_at = Column(DateTime(timezone=True), nullable=True)
    master_risk_triggered_reason = Column(String(10), nullable=True)  # 'sl' | 'target'


class UserRiskSettings(Base):
    """Per-user kill-switch and Master SL/Target state.

    The kill-switch and master-risk columns originally lived on the
    single-row `Settings` table, read via `Settings.query.first()`. That was
    written when Max Algos was single-user per deployment, but the platform
    is now multi-user with independent broker connections (see CLAUDE.md),
    which made those columns actively dangerous rather than merely
    inaccurate:

      - One user arming a Master SL of -5000 armed it for EVERY account,
        and the monitor closed positions using whichever username
        `Auth.query.filter_by(is_revoked=False).first()` happened to
        return -- i.e. one user's threshold could close a different user's
        real positions at their broker.
      - One user activating the kill switch blocked order placement for
        every other user on the instance, and ran cleanup (cancel all
        orders, close all positions) against that arbitrary first user's
        broker accounts.

    Keyed by `username` (the same identity `Auth.name` / `api_keys.user_id`
    use throughout the app) rather than a numeric FK, so it joins naturally
    with the existing per-user lookups and needs no cross-database
    relationship. The `Settings` columns are left in place, untouched and
    unread, so a rollback is a code revert with no data loss -- and so
    `_migrate_user_risk_settings()` can adopt them for the existing user.

    Genuinely platform-wide settings (SMTP, payments, security, analyze
    mode) deliberately stay on `Settings`.
    """

    __tablename__ = "user_risk_settings"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=False, unique=True, index=True)

    # Kill switch -- per-user emergency stop.
    kill_switch_active = Column(Boolean, default=False)
    kill_switch_activated_at = Column(DateTime(timezone=True), nullable=True)
    kill_switch_activated_by = Column(String(50), nullable=True)  # 'ui' | 'api' | 'telegram'
    kill_switch_reason = Column(String(500), nullable=True)
    kill_switch_min_unlock_at = Column(DateTime(timezone=True), nullable=True)
    kill_switch_cancel_orders_enabled = Column(Boolean, default=True)
    kill_switch_close_positions_enabled = Column(Boolean, default=True)

    # Master Target / Master SL -- per-user combined P&L auto-exit.
    master_risk_enabled = Column(Boolean, default=False)
    master_risk_sl_value = Column(Float, nullable=True)
    master_risk_target_value = Column(Float, nullable=True)
    master_risk_triggered_at = Column(DateTime(timezone=True), nullable=True)
    master_risk_triggered_reason = Column(String(10), nullable=True)  # 'sl' | 'target'


class KillSwitchAudit(Base):
    """Append-only audit log of every kill-switch activation/deactivation,
    kept separate from the single-row Settings table so it can grow
    unbounded without bloating the hot-path settings read.

    `username` scopes each row to the account it happened on, so one user's
    audit view never shows another's activations.
    """

    __tablename__ = "kill_switch_audit"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=True, index=True)
    event_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    event_type = Column(String(20), nullable=False)  # 'activated' | 'deactivated'
    actor_type = Column(String(20), nullable=False)  # 'ui' | 'api' | 'telegram'
    actor_id = Column(String(255), nullable=True)  # username / telegram chat id
    reason = Column(String(500), nullable=True)
    live_orders_cancelled = Column(Integer, default=0)
    live_orders_failed = Column(Integer, default=0)
    live_positions_closed = Column(Integer, default=0)
    sandbox_orders_cancelled = Column(Integer, default=0)
    sandbox_positions_closed = Column(Integer, default=0)
    strategies_stopped = Column(Integer, default=0)
    flows_aborted = Column(Integer, default=0)
    notes = Column(Text, nullable=True)  # JSON blob: per-strategy ids, broker errors, etc.


class MasterRiskAudit(Base):
    """Append-only log of every Master SL/Target trigger (see
    services/master_risk_monitor_service.py). Kept separate from the
    single-row Settings table for the same reason as KillSwitchAudit --
    grows unbounded without bloating the hot-path settings read."""

    __tablename__ = "master_risk_audit"
    id = Column(Integer, primary_key=True)
    username = Column(String(255), nullable=True, index=True)
    event_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    reason = Column(String(10), nullable=False)  # 'sl' | 'target'
    combined_pnl_at_trigger = Column(Float, nullable=False)
    threshold_value = Column(Float, nullable=False)
    positions_closed = Column(Integer, default=0)
    notes = Column(Text, nullable=True)  # JSON blob: per-broker close results


def _migrate_payment_columns():
    """Add payment columns to an existing `settings` table (pre-Razorpay
    installs). `Base.metadata.create_all()` only creates missing TABLES, not
    missing COLUMNS on a table that already exists, so upgrades need this
    explicit ALTER TABLE step -- same approach as database/user_db.py's
    broker_name migration."""
    inspector = inspect(engine)
    if "settings" not in inspector.get_table_names():
        return  # fresh install; create_all() above already includes these columns

    existing_columns = {c["name"] for c in inspector.get_columns("settings")}
    new_columns = {
        "payments_enabled": "BOOLEAN DEFAULT 1",
        "setup_fee_paise": "INTEGER DEFAULT 129900",
        "default_subscription_price_paise": "INTEGER DEFAULT 49900",
        "platform_subscription_plan_id": "VARCHAR(64)",
        "razorpay_key_id": "VARCHAR(64)",
        "razorpay_key_secret_encrypted": "TEXT",
        "razorpay_webhook_secret_encrypted": "TEXT",
    }
    missing = {name: ddl for name, ddl in new_columns.items() if name not in existing_columns}
    if not missing:
        return

    logger.info(f"Settings DB: Migrating in {len(missing)} new payment column(s)...")
    with engine.connect() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE settings ADD COLUMN {name} {ddl}"))
        conn.commit()


def _migrate_kill_switch_columns():
    """Add kill-switch columns to an existing `settings` table, same
    ALTER TABLE approach as _migrate_payment_columns above."""
    inspector = inspect(engine)
    if "settings" not in inspector.get_table_names():
        return  # fresh install; create_all() above already includes these columns

    existing_columns = {c["name"] for c in inspector.get_columns("settings")}
    new_columns = {
        "kill_switch_active": "BOOLEAN DEFAULT 0",
        "kill_switch_activated_at": "DATETIME",
        "kill_switch_activated_by": "VARCHAR(50)",
        "kill_switch_reason": "VARCHAR(500)",
        "kill_switch_min_unlock_at": "DATETIME",
        "kill_switch_cancel_orders_enabled": "BOOLEAN DEFAULT 1",
        "kill_switch_close_positions_enabled": "BOOLEAN DEFAULT 1",
    }
    missing = {name: ddl for name, ddl in new_columns.items() if name not in existing_columns}
    if not missing:
        return

    logger.info(f"Settings DB: Migrating in {len(missing)} new kill-switch column(s)...")
    with engine.connect() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE settings ADD COLUMN {name} {ddl}"))
        conn.commit()


def _migrate_email_identity_columns():
    """Add platform-email-identity columns to an existing `settings` table,
    same ALTER TABLE approach as _migrate_payment_columns above."""
    inspector = inspect(engine)
    if "settings" not in inspector.get_table_names():
        return  # fresh install; create_all() above already includes these columns

    existing_columns = {c["name"] for c in inspector.get_columns("settings")}
    new_columns = {
        "smtp_email_default": "VARCHAR(255)",
        "smtp_email_verification": "VARCHAR(255)",
        "smtp_email_security": "VARCHAR(255)",
        "smtp_email_billing": "VARCHAR(255)",
        "smtp_email_notifications": "VARCHAR(255)",
        "smtp_email_reply_to": "VARCHAR(255)",
    }
    missing = {name: ddl for name, ddl in new_columns.items() if name not in existing_columns}
    if not missing:
        return

    logger.info(f"Settings DB: Migrating in {len(missing)} new email-identity column(s)...")
    with engine.connect() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE settings ADD COLUMN {name} {ddl}"))
        conn.commit()


def _migrate_master_risk_columns():
    """Add Master SL/Target columns to an existing `settings` table, same
    ALTER TABLE approach as _migrate_payment_columns above."""
    inspector = inspect(engine)
    if "settings" not in inspector.get_table_names():
        return  # fresh install; create_all() above already includes these columns

    existing_columns = {c["name"] for c in inspector.get_columns("settings")}
    new_columns = {
        "master_risk_enabled": "BOOLEAN DEFAULT 0",
        "master_risk_sl_value": "FLOAT",
        "master_risk_target_value": "FLOAT",
        "master_risk_triggered_at": "DATETIME",
        "master_risk_triggered_reason": "VARCHAR(10)",
    }
    missing = {name: ddl for name, ddl in new_columns.items() if name not in existing_columns}
    if not missing:
        return

    logger.info(f"Settings DB: Migrating in {len(missing)} new master-risk column(s)...")
    with engine.connect() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE settings ADD COLUMN {name} {ddl}"))
        conn.commit()


def _migrate_audit_username_columns():
    """Add the `username` scoping column to the two audit tables, same
    ALTER TABLE approach as _migrate_payment_columns above. Existing rows
    keep NULL (pre-multi-user history, owner unknown)."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.connect() as conn:
        for table in ("kill_switch_audit", "master_risk_audit"):
            if table not in tables:
                continue  # fresh install; create_all() already includes it
            existing = {c["name"] for c in inspector.get_columns(table)}
            if "username" in existing:
                continue
            logger.info(f"Settings DB: Adding username column to {table}...")
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN username VARCHAR(255)"))
        conn.commit()


def _migrate_user_risk_settings():
    """Adopt the legacy single-row kill-switch / master-risk config into a
    per-user `user_risk_settings` row.

    Runs once: if any `user_risk_settings` row already exists, the install
    has been migrated and this is a no-op. Otherwise the values on the
    global `Settings` row are handed to the install's existing account, so
    upgrading does not silently disarm a configured Master SL/Target or
    forget an active kill switch. Brand-new installs (no user yet, or no
    meaningful legacy config) get nothing here -- `get_or_create` below
    creates rows with safe defaults on first access.

    Deliberately leaves the legacy `Settings` columns in place rather than
    dropping them: SQLite's ALTER TABLE DROP COLUMN is unavailable on older
    versions, and keeping them makes a rollback to the previous release a
    pure code revert with the old data still intact.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "user_risk_settings" not in tables or "settings" not in tables:
        return

    try:
        if db_session.query(UserRiskSettings).first():
            return  # already migrated

        legacy = Settings.query.first()
        if not legacy:
            return

        legacy_columns = {c["name"] for c in inspector.get_columns("settings")}

        def _legacy(name, default=None):
            # The legacy columns may not exist at all on a very old install
            # that never ran the kill-switch/master-risk migrations.
            if name not in legacy_columns:
                return default
            return getattr(legacy, name, default)

        # Only adopt if there is actually something worth carrying over --
        # otherwise leave the table empty and let normal per-user creation
        # handle it with defaults.
        has_config = bool(
            _legacy("kill_switch_active")
            or _legacy("master_risk_enabled")
            or _legacy("master_risk_sl_value") is not None
            or _legacy("master_risk_target_value") is not None
            or _legacy("kill_switch_cancel_orders_enabled", True) is False
            or _legacy("kill_switch_close_positions_enabled", True) is False
        )
        if not has_config:
            return

        # The account that owns this install's existing config. Imported
        # lazily to avoid a circular import at module load.
        from database.auth_db import Auth

        owner = Auth.query.filter_by(is_revoked=False).first()
        if not owner:
            return  # nobody to adopt it; defaults will apply per-user later

        db_session.add(
            UserRiskSettings(
                username=owner.name,
                kill_switch_active=bool(_legacy("kill_switch_active", False)),
                kill_switch_activated_at=_legacy("kill_switch_activated_at"),
                kill_switch_activated_by=_legacy("kill_switch_activated_by"),
                kill_switch_reason=_legacy("kill_switch_reason"),
                kill_switch_min_unlock_at=_legacy("kill_switch_min_unlock_at"),
                kill_switch_cancel_orders_enabled=bool(
                    _legacy("kill_switch_cancel_orders_enabled", True)
                ),
                kill_switch_close_positions_enabled=bool(
                    _legacy("kill_switch_close_positions_enabled", True)
                ),
                master_risk_enabled=bool(_legacy("master_risk_enabled", False)),
                master_risk_sl_value=_legacy("master_risk_sl_value"),
                master_risk_target_value=_legacy("master_risk_target_value"),
                master_risk_triggered_at=_legacy("master_risk_triggered_at"),
                master_risk_triggered_reason=_legacy("master_risk_triggered_reason"),
            )
        )
        db_session.commit()
        logger.info(
            f"Settings DB: Adopted legacy kill-switch/master-risk config for user '{owner.name}'"
        )
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Settings DB: user_risk_settings migration failed: {e}")


def init_db():
    """Initialize the settings database"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Settings DB", logger)
    _migrate_payment_columns()
    _migrate_kill_switch_columns()
    _migrate_email_identity_columns()
    _migrate_master_risk_columns()
    _migrate_audit_username_columns()
    _migrate_user_risk_settings()

    # Create default settings only if no settings exist (with race condition protection)
    try:
        if not Settings.query.first():
            logger.debug("Settings DB: Creating default configuration (Live Mode)")
            default_settings = Settings(analyze_mode=False)
            db_session.add(default_settings)
            db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.debug(f"Settings DB: Default config may already exist (race condition): {e}")


def get_analyze_mode():
    """Get current analyze mode setting (cached for 1 hour)"""
    cache_key = "analyze_mode"

    # Check cache first
    if cache_key in _settings_cache:
        return _settings_cache[cache_key]

    # Cache miss - query database
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=False)  # Default to Live Mode
        db_session.add(settings)
        db_session.commit()

    # Store in cache
    _settings_cache[cache_key] = settings.analyze_mode
    return settings.analyze_mode


def set_analyze_mode(mode: bool):
    """Set analyze mode setting"""
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=mode)
        db_session.add(settings)
    else:
        settings.analyze_mode = mode
    db_session.commit()

    # Invalidate cache after update
    if "analyze_mode" in _settings_cache:
        del _settings_cache["analyze_mode"]


# Kill switch -- PER-USER emergency stop. See
# docs/plans/2026-04-24-kill-switch-implementation-plan.md for the original
# design (written when the platform was single-user; state now lives on the
# per-user UserRiskSettings table instead of the global Settings row).
#
# Every function below takes an explicit `username`. That is deliberate and
# load-bearing: the previous signatures took none and read
# `Settings.query.first()`, so ANY user's activation blocked order placement
# for EVERY account on the instance. Making the identity an explicit required
# argument means a future caller cannot accidentally reintroduce the global
# read -- it won't compile past review without answering "whose kill switch?".
KILL_SWITCH_MIN_UNLOCK_SECONDS = 60


def _kill_switch_cache_key(username: str) -> str:
    return f"kill_switch_active:{username}"


def get_user_risk_settings_row(username: str, create: bool = False):
    """Fetch (optionally create) the UserRiskSettings row for `username`.

    Returns None when the row doesn't exist and `create` is False, so
    read paths can fall back to defaults without writing on every read.
    """
    if not username:
        return None
    row = db_session.query(UserRiskSettings).filter_by(username=username).first()
    if row is None and create:
        row = UserRiskSettings(username=username)
        db_session.add(row)
        db_session.commit()
    return row


def is_kill_switch_active(username: str | None) -> bool:
    """Hot-path read for `username`'s own kill switch, cached for 1 hour.

    A None/empty username returns False (fail-open) rather than falling
    back to some other user's flag: an unattributable internal call must
    never be blocked by a DIFFERENT user's emergency stop. Callers that
    can identify the user always pass it (see utils/kill_switch.py).
    """
    if not username:
        return False

    cache_key = _kill_switch_cache_key(username)
    if cache_key in _settings_cache:
        return _settings_cache[cache_key]

    row = get_user_risk_settings_row(username)
    active = bool(row.kill_switch_active) if row else False
    _settings_cache[cache_key] = active
    return active


def get_kill_switch_state(username: str | None) -> dict:
    """Full kill-switch record for `username`, for status endpoints/UI --
    not cached since it's read far less often than the hot-path boolean
    above and callers need up-to-date timestamps."""
    row = get_user_risk_settings_row(username) if username else None
    if not row:
        return {
            "kill_switch_active": False,
            "activated_at": None,
            "activated_by": None,
            "reason": None,
            "min_unlock_at": None,
        }
    return {
        "kill_switch_active": bool(row.kill_switch_active),
        "activated_at": row.kill_switch_activated_at.isoformat()
        if row.kill_switch_activated_at
        else None,
        "activated_by": row.kill_switch_activated_by,
        "reason": row.kill_switch_reason,
        "min_unlock_at": row.kill_switch_min_unlock_at.isoformat()
        if row.kill_switch_min_unlock_at
        else None,
    }


# Per-username in-process lock guarding set_kill_switch below. NOT a real
# row lock: this project runs single-worker Gunicorn/eventlet (see
# CLAUDE.md), and SQLite's dialect silently ignores SELECT...FOR UPDATE
# entirely (confirmed: engine.dialect.supports_for_update_of is False for
# SQLite) -- combined with NullPool (every query gets its own fresh
# connection, nothing to actually block on), .with_for_update() below was a
# complete no-op. A real concurrent-thread test against the equivalent
# pattern in database/strategy_db.py::try_claim_deployment_for_entry caught
# this directly: 9 of 10 simultaneous callers "won" instead of exactly 1.
# A real mutex is required for SQLite; see that function's docstring for
# the full explanation. Kept even though kill-switch activation is a rare,
# human-paced action rather than a high-frequency path -- same class of
# bug, cheap to close now that it's been found.
_kill_switch_locks: dict[str, threading.Lock] = {}
_kill_switch_locks_guard = threading.Lock()


def _get_kill_switch_lock(username: str) -> threading.Lock:
    with _kill_switch_locks_guard:
        lock = _kill_switch_locks.get(username)
        if lock is None:
            lock = threading.Lock()
            _kill_switch_locks[username] = lock
        return lock


def set_kill_switch(
    username: str, active: bool, actor_type: str, actor_id: str | None, reason: str | None
) -> dict:
    """Flip `username`'s own flag and timestamps. Guarded by a per-username
    threading.Lock (see above) so a second concurrent activate call blocks
    until the first commits, then sees the already-active state instead of
    racing it -- see plan section 16.4. Returns the state dict as of after
    the write."""
    lock = _get_kill_switch_lock(username)
    with lock:
        row = db_session.query(UserRiskSettings).filter_by(username=username).first()
        if not row:
            row = UserRiskSettings(username=username)
            db_session.add(row)

        now = datetime.now(UTC)
        row.kill_switch_active = active
        if active:
            row.kill_switch_activated_at = now
            row.kill_switch_activated_by = actor_type
            row.kill_switch_reason = reason
            row.kill_switch_min_unlock_at = now + timedelta(seconds=KILL_SWITCH_MIN_UNLOCK_SECONDS)
        # On deactivate, deliberately leave activated_at/by/reason/min_unlock_at
        # as historical record of the most recent activation rather than
        # clearing them -- the audit table is the real log, but this makes the
        # "who/when/why" visible at a glance even between audit-log page visits.
        db_session.commit()

        _settings_cache.pop(_kill_switch_cache_key(username), None)

        return get_kill_switch_state(username)


def get_kill_switch_scope(username: str | None) -> dict:
    """Which cleanup steps run on `username`'s activation. Strategy/flow
    stopping is not represented here -- it always runs unconditionally."""
    row = get_user_risk_settings_row(username) if username else None
    if not row:
        return {"cancel_orders_enabled": True, "close_positions_enabled": True}
    return {
        "cancel_orders_enabled": bool(row.kill_switch_cancel_orders_enabled),
        "close_positions_enabled": bool(row.kill_switch_close_positions_enabled),
    }


def set_kill_switch_scope(
    username: str, cancel_orders_enabled: bool, close_positions_enabled: bool
) -> dict:
    """Update which cleanup steps run on `username`'s activation."""
    row = get_user_risk_settings_row(username, create=True)
    row.kill_switch_cancel_orders_enabled = cancel_orders_enabled
    row.kill_switch_close_positions_enabled = close_positions_enabled
    db_session.commit()
    return get_kill_switch_scope(username)


def record_kill_switch_audit(
    username: str | None,
    event_type: str,
    actor_type: str,
    actor_id: str | None,
    reason: str | None,
    live_orders_cancelled: int = 0,
    live_orders_failed: int = 0,
    live_positions_closed: int = 0,
    sandbox_orders_cancelled: int = 0,
    sandbox_positions_closed: int = 0,
    strategies_stopped: int = 0,
    flows_aborted: int = 0,
    notes: str | None = None,
) -> None:
    """Append one row to the kill-switch audit log, scoped to `username`.
    Never raises -- audit logging must not be able to fail the activation/
    deactivation itself."""
    try:
        entry = KillSwitchAudit(
            username=username,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
            live_orders_cancelled=live_orders_cancelled,
            live_orders_failed=live_orders_failed,
            live_positions_closed=live_positions_closed,
            sandbox_orders_cancelled=sandbox_orders_cancelled,
            sandbox_positions_closed=sandbox_positions_closed,
            strategies_stopped=strategies_stopped,
            flows_aborted=flows_aborted,
            notes=notes,
        )
        db_session.add(entry)
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Kill switch: failed to write audit entry: {e}")


def get_kill_switch_audit(username: str | None, limit: int = 50) -> list[dict]:
    """`username`'s most recent audit entries, newest first.

    Filtered by user so one account's audit page never exposes another's
    activation history (times, reasons, and per-broker cleanup counts).
    """
    query = KillSwitchAudit.query
    if username:
        query = query.filter(KillSwitchAudit.username == username)
    entries = query.order_by(KillSwitchAudit.event_at.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "event_at": e.event_at.isoformat() if e.event_at else None,
            "event_type": e.event_type,
            "actor_type": e.actor_type,
            "actor_id": e.actor_id,
            "reason": e.reason,
            "live_orders_cancelled": e.live_orders_cancelled,
            "live_orders_failed": e.live_orders_failed,
            "live_positions_closed": e.live_positions_closed,
            "sandbox_orders_cancelled": e.sandbox_orders_cancelled,
            "sandbox_positions_closed": e.sandbox_positions_closed,
            "strategies_stopped": e.strategies_stopped,
            "flows_aborted": e.flows_aborted,
            "notes": e.notes,
        }
        for e in entries
    ]


# Master Target / Master SL -- PER-USER combined P&L auto-exit. Follows the
# exact get/set pattern as the kill switch above, minus the 1-hour cache
# (this is read once every monitor tick, not on every order-placing call, so
# the cache's main purpose -- avoiding a DB hit on the hot order path --
# doesn't apply here).
#
# `username` is required for the same reason it is on the kill switch: these
# used to read the single global Settings row, so one trader's "-5000" SL was
# every trader's SL, and the monitor closed positions belonging to whichever
# account Auth.query.first() returned.
def get_master_risk_settings(username: str | None) -> dict:
    """Full master-risk record for `username`, for the monitor loop and
    settings UI."""
    row = get_user_risk_settings_row(username) if username else None
    if not row:
        return {
            "enabled": False,
            "sl_value": None,
            "target_value": None,
            "triggered_at": None,
            "triggered_reason": None,
        }
    return {
        "enabled": bool(row.master_risk_enabled),
        "sl_value": row.master_risk_sl_value,
        "target_value": row.master_risk_target_value,
        "triggered_at": row.master_risk_triggered_at.isoformat()
        if row.master_risk_triggered_at
        else None,
        "triggered_reason": row.master_risk_triggered_reason,
    }


def set_master_risk_settings(
    username: str, enabled: bool, sl_value: float | None, target_value: float | None
) -> dict:
    """Update `username`'s master-risk configuration. Does NOT touch
    triggered_at/triggered_reason -- those are only set by
    record_master_risk_trigger below, when a trigger actually fires."""
    row = get_user_risk_settings_row(username, create=True)
    row.master_risk_enabled = enabled
    row.master_risk_sl_value = sl_value
    row.master_risk_target_value = target_value
    db_session.commit()
    return get_master_risk_settings(username)


def list_enabled_master_risk_users() -> list[str]:
    """Every username with master-risk monitoring currently armed.

    The monitor tick iterates this instead of assuming a single account --
    each user's own thresholds are evaluated against their own positions.
    """
    rows = (
        db_session.query(UserRiskSettings.username)
        .filter(UserRiskSettings.master_risk_enabled.is_(True))
        .all()
    )
    return [r[0] for r in rows if r[0]]


def record_master_risk_trigger(username: str, reason: str, combined_pnl: float) -> None:
    """Stamp the trigger timestamp/reason on `username`'s row AND
    auto-disable their monitoring (mirrors a physical breaker -- once
    tripped, it stays off until the trader deliberately re-arms it via
    set_master_risk_settings, rather than immediately re-triggering on the
    next tick before positions have actually cleared)."""
    row = get_user_risk_settings_row(username)
    if not row:
        return
    row.master_risk_enabled = False
    row.master_risk_triggered_at = datetime.now(UTC)
    row.master_risk_triggered_reason = reason
    db_session.commit()
    _ = combined_pnl  # logged by the caller into MasterRiskAudit, not stored here


def record_master_risk_audit(
    username: str | None,
    reason: str,
    combined_pnl_at_trigger: float,
    threshold_value: float,
    positions_closed: int = 0,
    notes: str | None = None,
) -> None:
    """Append one row to the master-risk audit log, scoped to `username`.
    Never raises -- audit logging must not be able to fail the trigger
    sequence itself."""
    try:
        entry = MasterRiskAudit(
            username=username,
            reason=reason,
            combined_pnl_at_trigger=combined_pnl_at_trigger,
            threshold_value=threshold_value,
            positions_closed=positions_closed,
            notes=notes,
        )
        db_session.add(entry)
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        logger.exception(f"Master risk: failed to write audit entry: {e}")


def get_master_risk_audit(username: str | None, limit: int = 50) -> list[dict]:
    """`username`'s most recent audit entries, newest first. Filtered by
    user so one account never sees another's trigger history or P&L."""
    query = MasterRiskAudit.query
    if username:
        query = query.filter(MasterRiskAudit.username == username)
    entries = query.order_by(MasterRiskAudit.event_at.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "event_at": e.event_at.isoformat() if e.event_at else None,
            "reason": e.reason,
            "combined_pnl_at_trigger": e.combined_pnl_at_trigger,
            "threshold_value": e.threshold_value,
            "positions_closed": e.positions_closed,
            "notes": e.notes,
        }
        for e in entries
    ]


# SMTP password encryption.
#
# New ciphertext uses a strong PBKDF2-HMAC-SHA256 key derived from the
# validated API_KEY_PEPPER (imported from auth_db, which fails fast if the
# pepper is missing or too short) plus a dedicated salt. Older installs
# stored the SMTP password under a weak legacy key (the raw pepper,
# padded/truncated to 32
# bytes with no KDF); _decrypt_password() transparently falls back to that
# legacy key so existing values keep working, and re-saving SMTP settings
# re-encrypts under the strong key, migrating it forward.
SMTP_KEY_SALT = os.getenv("SMTP_KEY_SALT", "smtp-maxalgos-salt").encode()


def _get_smtp_fernet() -> Fernet:
    """Strong Fernet for the SMTP password: PBKDF2(PEPPER, SMTP_KEY_SALT)."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SMTP_KEY_SALT,
        iterations=100000,
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(PEPPER.encode())))


def _legacy_smtp_fernet() -> Fernet:
    """Legacy read-only key (raw pepper, no KDF). Used only to decrypt values
    stored before the switch to _get_smtp_fernet(); never for new writes.
    """
    return Fernet(base64.urlsafe_b64encode(PEPPER.ljust(32)[:32].encode()))


# Module-level cipher; PEPPER is fixed for the process lifetime.
_smtp_fernet = _get_smtp_fernet()


def _encrypt_password(password: str) -> str:
    """Encrypt SMTP password with the strong per-install key."""
    if not password:
        return None
    return _smtp_fernet.encrypt(password.encode()).decode()


def _decrypt_password(encrypted_password: str) -> str:
    """Decrypt SMTP password, falling back to the legacy key for values
    written before the KDF upgrade."""
    if not encrypted_password:
        return None
    token = encrypted_password.encode()
    try:
        return _smtp_fernet.decrypt(token).decode()
    except InvalidToken:
        return _legacy_smtp_fernet().decrypt(token).decode()


def get_smtp_settings():
    """Get SMTP configuration (transport only -- server/port/credentials/TLS).
    For the "From" address to use for a specific email, see
    get_email_from_address() below; smtp_from_email is kept here too as the
    legacy/ultimate fallback for installs that only ever set that field."""
    settings = Settings.query.first()
    if not settings:
        return None

    return {
        "smtp_server": settings.smtp_server,
        "smtp_port": settings.smtp_port,
        "smtp_username": settings.smtp_username,
        "smtp_password": _decrypt_password(settings.smtp_password_encrypted)
        if settings.smtp_password_encrypted
        else None,
        "smtp_use_tls": settings.smtp_use_tls,
        "smtp_from_email": settings.smtp_from_email,
        "smtp_helo_hostname": settings.smtp_helo_hostname,
    }


def set_smtp_settings(
    smtp_server=None,
    smtp_port=None,
    smtp_username=None,
    smtp_password=None,
    smtp_use_tls=True,
    smtp_from_email=None,
    smtp_helo_hostname=None,
):
    """Set SMTP configuration (transport only). Platform email identities
    (which "From" address each email category uses) are set separately via
    set_email_identities() -- kept as a distinct function/route so the
    transport form and the identities form can be saved independently in
    the admin UI without one overwriting the other's fields."""
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=False)
        db_session.add(settings)

    # None means "field omitted, keep existing" (e.g. a caller that only
    # wants to update one field). "" means "explicitly cleared" and must
    # actually clear the column -- normalized to None for storage so
    # get_smtp_settings()/callers see an unset field consistently, matching
    # set_email_identities()'s convention below.
    if smtp_server is not None:
        settings.smtp_server = smtp_server or None
    if smtp_port is not None:
        settings.smtp_port = smtp_port
    if smtp_username is not None:
        settings.smtp_username = smtp_username or None
    if smtp_password is not None:
        settings.smtp_password_encrypted = _encrypt_password(smtp_password)
    if smtp_use_tls is not None:
        settings.smtp_use_tls = smtp_use_tls
    if smtp_from_email is not None:
        settings.smtp_from_email = smtp_from_email or None
    if smtp_helo_hostname is not None:
        settings.smtp_helo_hostname = smtp_helo_hostname or None

    db_session.commit()
    logger.info("SMTP settings updated successfully")


# Platform Email Identities -- maps an email "purpose" to the From address
# it should be sent as. All purposes share the single SMTP transport from
# get_smtp_settings() above; only the From header/envelope-sender differs.
EMAIL_IDENTITY_FIELDS = (
    "smtp_email_default",
    "smtp_email_verification",
    "smtp_email_security",
    "smtp_email_billing",
    "smtp_email_notifications",
    "smtp_email_reply_to",
)

VALID_EMAIL_PURPOSES = ("verification", "security", "billing", "notifications")


def get_email_identities() -> dict:
    """Return the configured From address for every identity slot (may be
    None/blank for any that haven't been set yet)."""
    settings = Settings.query.first()
    if not settings:
        return dict.fromkeys(EMAIL_IDENTITY_FIELDS)
    return {field: getattr(settings, field) for field in EMAIL_IDENTITY_FIELDS}


def set_email_identities(
    smtp_email_default=None,
    smtp_email_verification=None,
    smtp_email_security=None,
    smtp_email_billing=None,
    smtp_email_notifications=None,
    smtp_email_reply_to=None,
) -> None:
    """Set the platform email identities. Each param left as None keeps the
    existing stored value unchanged (same convention as set_smtp_settings);
    pass an empty string "" to explicitly clear a field back to unset."""
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=False)
        db_session.add(settings)

    if smtp_email_default is not None:
        settings.smtp_email_default = smtp_email_default or None
    if smtp_email_verification is not None:
        settings.smtp_email_verification = smtp_email_verification or None
    if smtp_email_security is not None:
        settings.smtp_email_security = smtp_email_security or None
    if smtp_email_billing is not None:
        settings.smtp_email_billing = smtp_email_billing or None
    if smtp_email_notifications is not None:
        settings.smtp_email_notifications = smtp_email_notifications or None
    if smtp_email_reply_to is not None:
        settings.smtp_email_reply_to = smtp_email_reply_to or None

    db_session.commit()
    logger.info("Platform email identities updated successfully")


def get_email_from_address(purpose: str = "default") -> str | None:
    """Resolve which "From" address to use for a given email purpose.

    Fallback chain: the specific identity (e.g. smtp_email_security) ->
    smtp_email_default -> smtp_from_email (the original single-field
    config, kept as the ultimate fallback so installs that only ever
    configured the old single "From Email" field keep working exactly as
    before -- this refactor is additive, not a breaking migration).
    """
    if purpose not in VALID_EMAIL_PURPOSES and purpose != "default":
        purpose = "default"

    settings = Settings.query.first()
    if not settings:
        return None

    specific = None if purpose == "default" else getattr(settings, f"smtp_email_{purpose}", None)
    return specific or settings.smtp_email_default or settings.smtp_from_email


# Razorpay credential encryption -- same PBKDF2-HMAC-SHA256(PEPPER, salt)
# Fernet construction as SMTP above, with its own salt so the two derived
# keys are independent (compromising one does not help decrypt the other).
RAZORPAY_KEY_SALT = os.getenv("RAZORPAY_KEY_SALT", "razorpay-maxalgos-salt").encode()


def _get_razorpay_fernet() -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=RAZORPAY_KEY_SALT,
        iterations=100000,
    )
    return Fernet(base64.urlsafe_b64encode(kdf.derive(PEPPER.encode())))


_razorpay_fernet = _get_razorpay_fernet()


def _encrypt_razorpay_secret(value: str) -> str:
    if not value:
        return None
    return _razorpay_fernet.encrypt(value.encode()).decode()


def _decrypt_razorpay_secret(encrypted_value: str) -> str:
    if not encrypted_value:
        return None
    return _razorpay_fernet.decrypt(encrypted_value.encode()).decode()


def get_razorpay_credentials():
    """Get Razorpay credentials (decrypted). Backend-only -- the key_secret
    and webhook_secret returned here must never reach the frontend; the
    admin API layer (blueprints/payments.py) masks them into booleans
    before responding to any request. Falls back to RAZORPAY_KEY_ID /
    RAZORPAY_KEY_SECRET / RAZORPAY_WEBHOOK_SECRET env vars when the DB has
    no value set, so installs that prefer .env-only config keep working
    unchanged.
    """
    settings = Settings.query.first()

    key_id = (settings.razorpay_key_id if settings else None) or os.getenv(
        "RAZORPAY_KEY_ID", ""
    ) or None
    key_secret = (
        _decrypt_razorpay_secret(settings.razorpay_key_secret_encrypted)
        if settings and settings.razorpay_key_secret_encrypted
        else None
    ) or os.getenv("RAZORPAY_KEY_SECRET", "") or None
    webhook_secret = (
        _decrypt_razorpay_secret(settings.razorpay_webhook_secret_encrypted)
        if settings and settings.razorpay_webhook_secret_encrypted
        else None
    ) or os.getenv("RAZORPAY_WEBHOOK_SECRET", "") or None

    return {
        "key_id": key_id,
        "key_secret": key_secret,
        "webhook_secret": webhook_secret,
    }


def set_razorpay_credentials(key_id=None, key_secret=None, webhook_secret=None):
    """Set Razorpay credentials (admin-only, enforced by the calling route).
    Blank/None values are left untouched, same "leave blank to keep
    existing" convention as SMTP -- re-saving the key_id doesn't force the
    admin to re-paste the secret every time.
    """
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=False)
        db_session.add(settings)

    if key_id is not None:
        settings.razorpay_key_id = key_id
    if key_secret:
        settings.razorpay_key_secret_encrypted = _encrypt_razorpay_secret(key_secret)
    if webhook_secret:
        settings.razorpay_webhook_secret_encrypted = _encrypt_razorpay_secret(webhook_secret)

    db_session.commit()
    logger.info("Razorpay credentials updated successfully")


def get_security_settings():
    """Get security configuration (cached for 1 hour)"""
    cache_key = "security_settings"

    # Check cache first
    if cache_key in _settings_cache:
        return _settings_cache[cache_key]

    # Cache miss - query database
    settings = Settings.query.first()
    if not settings:
        # Create with defaults
        settings = Settings(
            analyze_mode=False,
            security_auto_ban_enabled=False,
            security_404_threshold=100,
            security_404_ban_duration=0,
            security_api_threshold=100,
            security_api_ban_duration=0,
            security_repeat_offender_limit=2,
        )
        db_session.add(settings)
        db_session.commit()

    result = {
        "auto_ban_enabled": bool(settings.security_auto_ban_enabled) if settings.security_auto_ban_enabled is not None else False,
        "404_threshold": settings.security_404_threshold or 100,
        "404_ban_duration": settings.security_404_ban_duration if settings.security_404_ban_duration is not None else 0,
        "api_threshold": settings.security_api_threshold or 100,
        "api_ban_duration": settings.security_api_ban_duration if settings.security_api_ban_duration is not None else 0,
        "repeat_offender_limit": settings.security_repeat_offender_limit or 2,
    }

    # Store in cache
    _settings_cache[cache_key] = result
    return result


def set_security_settings(
    auto_ban_enabled=None,
    threshold_404=None,
    ban_duration_404=None,
    threshold_api=None,
    ban_duration_api=None,
    repeat_offender_limit=None,
):
    """Set security configuration"""
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=False)
        db_session.add(settings)

    if auto_ban_enabled is not None:
        settings.security_auto_ban_enabled = auto_ban_enabled
    if threshold_404 is not None:
        settings.security_404_threshold = threshold_404
    if ban_duration_404 is not None:
        settings.security_404_ban_duration = ban_duration_404
    if threshold_api is not None:
        settings.security_api_threshold = threshold_api
    if ban_duration_api is not None:
        settings.security_api_ban_duration = ban_duration_api
    if repeat_offender_limit is not None:
        settings.security_repeat_offender_limit = repeat_offender_limit

    db_session.commit()
    logger.info("Security settings updated successfully")

    # Invalidate cache after update
    if "security_settings" in _settings_cache:
        del _settings_cache["security_settings"]


def get_payment_settings():
    """Get payment configuration (cached for 1 hour)"""
    cache_key = "payment_settings"

    # Check cache first
    if cache_key in _settings_cache:
        return _settings_cache[cache_key]

    # Cache miss - query database
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=False)
        db_session.add(settings)
        db_session.commit()

    result = {
        "payments_enabled": bool(settings.payments_enabled)
        if settings.payments_enabled is not None
        else True,
        "setup_fee_paise": settings.setup_fee_paise
        if settings.setup_fee_paise is not None
        else 129900,
        "default_subscription_price_paise": settings.default_subscription_price_paise
        if settings.default_subscription_price_paise is not None
        else 49900,
        "platform_subscription_plan_id": settings.platform_subscription_plan_id,
    }

    # Store in cache
    _settings_cache[cache_key] = result
    return result


def set_payment_settings(
    payments_enabled=None,
    setup_fee_paise=None,
    default_subscription_price_paise=None,
    platform_subscription_plan_id=None,
):
    """Set payment configuration (admin-only, enforced by the calling route)"""
    settings = Settings.query.first()
    if not settings:
        settings = Settings(analyze_mode=False)
        db_session.add(settings)

    if payments_enabled is not None:
        settings.payments_enabled = payments_enabled
    if setup_fee_paise is not None:
        if setup_fee_paise < 0:
            raise ValueError("setup_fee_paise must be non-negative")
        settings.setup_fee_paise = setup_fee_paise
    if default_subscription_price_paise is not None:
        if default_subscription_price_paise < 0:
            raise ValueError("default_subscription_price_paise must be non-negative")
        settings.default_subscription_price_paise = default_subscription_price_paise
    if platform_subscription_plan_id is not None:
        settings.platform_subscription_plan_id = platform_subscription_plan_id.strip() or None

    db_session.commit()
    logger.info("Payment settings updated successfully")

    # Invalidate cache after update
    if "payment_settings" in _settings_cache:
        del _settings_cache["payment_settings"]


def clear_settings_cache():
    """
    Clear all settings caches.
    Called on logout/session expiry to ensure fresh data on next login.
    """
    _settings_cache.clear()
    logger.info("Settings cache cleared")
