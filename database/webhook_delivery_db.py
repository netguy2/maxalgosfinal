"""Webhook delivery log — an auditable record of every signal a webhook receives.

Answers "why did this trade (or not) happen?" without log-file forensics. Each
inbound webhook request creates exactly one WebhookDelivery row at ingestion,
which is then updated as the signal moves through processing:

    received → accepted/rejected → (async) processed/failed

The row is written *before* the signal is enqueued, so a request that crashes
mid-processing still leaves evidence it arrived. This is the key property a
plain application log does not give you: a queryable, per-request record whose
absence is itself meaningful.

Stage decisions accumulate in the `stages` JSON column as a list of
{stage, outcome, detail, ms} entries. That shape is deliberately module-shaped:
when the pipeline/module framework lands, each module appends one entry here and
the UI can render a before/after trace per stage without a schema change.

Retention is bounded — see purge_old_deliveries(); an unbounded audit table on
SQLite would grow without limit on a busy webhook.

FD note: engine uses NullPool via create_db_engine (CLAUDE.md). The scoped
session created here MUST be registered in app.py's teardown_appcontext.
"""

import hashlib
import json
import os
from datetime import datetime, timedelta

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_db_engine(DATABASE_URL)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

# Retention for delivery rows. Kept modest by default: this table takes one row
# per inbound webhook request, which on an active scanner-driven strategy can be
# thousands per day.
DELIVERY_RETENTION_DAYS = int(os.getenv("WEBHOOK_DELIVERY_RETENTION_DAYS", "30"))

# Truncation guard for stored payloads. A webhook body is attacker-influenced
# (the URL is the only credential today), so an unbounded Text column is a cheap
# way to bloat the DB. 16 KB is far above any legitimate TradingView/ChartInk
# alert body.
MAX_PAYLOAD_CHARS = 16384

# Terminal + transitional outcome values. Strings rather than an Enum column so
# new module outcomes (retry/pause/skip) can be recorded without a migration.
OUTCOME_RECEIVED = "received"
OUTCOME_ACCEPTED = "accepted"
OUTCOME_REJECTED = "rejected"
OUTCOME_PROCESSED = "processed"
OUTCOME_FAILED = "failed"
OUTCOME_DUPLICATE = "duplicate"


class WebhookDelivery(Base):
    """One inbound webhook request and everything that happened to it."""

    __tablename__ = "webhook_deliveries"

    id = Column(Integer, primary_key=True)

    # Which webhook was hit. webhook_id is the UUID in the URL; source_type
    # distinguishes the subsystem ("strategy", "chartink", "flow") so all
    # webhook entry points can share one audit table.
    webhook_id = Column(String(64), nullable=False, index=True)
    source_type = Column(String(20), nullable=False, default="strategy")

    # Denormalized for display — a delivery must stay readable after its
    # strategy is renamed or deleted.
    strategy_id = Column(Integer, nullable=True, index=True)
    strategy_name = Column(String(200), nullable=True)
    user_id = Column(String(50), nullable=True, index=True)

    # What arrived.
    signal = Column(String(50), nullable=True)
    payload = Column(Text, nullable=True)
    payload_hash = Column(String(64), nullable=True, index=True)
    remote_ip = Column(String(64), nullable=True)

    # What happened. `outcome` is the current state; `reason_code` and
    # `reason_detail` explain a rejection/failure in a structured way so the UI
    # can group by code rather than string-matching prose.
    outcome = Column(String(20), nullable=False, default=OUTCOME_RECEIVED, index=True)
    reason_code = Column(String(64), nullable=True)
    reason_detail = Column(Text, nullable=True)

    # Per-stage trace: [{"stage": "...", "outcome": "...", "detail": "...", "ms": 1.2}]
    stages = Column(JSON, nullable=True)

    # Resulting order ids, as a JSON list of strings.
    order_ids = Column(JSON, nullable=True)

    # datetime.now (local), NOT func.now(): func.now() resolves server-side to
    # UTC, while every read path here (dedup window, retention purge, duration)
    # compares against local datetime.now(). Mixing the two makes every freshly
    # written row look hours old on any non-UTC host -- IST is +5:30, so the
    # dedup window silently never matched and duplicate orders went through.
    received_at = Column(DateTime, default=datetime.now, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    # Composite index for the dedup lookup, which is the hottest query on this
    # table: "has this exact payload hit this webhook in the last N seconds?"
    __table_args__ = (
        Index("ix_webhook_deliveries_dedup", "webhook_id", "payload_hash", "received_at"),
    )

    def to_dict(self):
        """Serialize for API/UI consumption."""
        return {
            "id": self.id,
            "webhook_id": self.webhook_id,
            "source_type": self.source_type,
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "signal": self.signal,
            "payload": self.payload,
            "remote_ip": self.remote_ip,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "reason_detail": self.reason_detail,
            "stages": self.stages or [],
            "order_ids": self.order_ids or [],
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_ms": self.duration_ms,
        }


def init_db():
    """Create the delivery table if absent. Safe to call repeatedly."""
    Base.metadata.create_all(bind=engine)
    logger.info("Webhook delivery log initialized")


def compute_payload_hash(webhook_id, payload):
    """Stable hash of (webhook_id, payload) used for duplicate detection.

    The payload dict is serialized with sorted keys so that two logically
    identical JSON bodies with different key ordering hash the same — signal
    sources do not guarantee key order across retries.

    Note this deliberately hashes the *whole* body. A source that includes a
    changing timestamp or nonce per retry will therefore not be deduped, which
    is the correct conservative default: we only suppress orders we can prove
    are byte-identical repeats.
    """
    try:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        canonical = str(payload)
    return hashlib.sha256(f"{webhook_id}:{canonical}".encode()).hexdigest()


def _truncate(payload):
    """Serialize a payload for storage, bounded to MAX_PAYLOAD_CHARS."""
    try:
        s = json.dumps(payload, default=str)
    except (TypeError, ValueError):
        s = str(payload)
    if len(s) > MAX_PAYLOAD_CHARS:
        return s[:MAX_PAYLOAD_CHARS] + f"...[truncated {len(s) - MAX_PAYLOAD_CHARS} chars]"
    return s


def record_received(
    webhook_id,
    payload,
    source_type="strategy",
    strategy_id=None,
    strategy_name=None,
    user_id=None,
    signal=None,
    remote_ip=None,
    payload_hash=None,
):
    """Insert a delivery row at ingestion. Returns the row id, or None on failure.

    Never raises: an audit-log write must not be able to break order flow. A
    failure here is logged and the caller proceeds without a delivery id.
    """
    try:
        delivery = WebhookDelivery(
            webhook_id=str(webhook_id),
            source_type=source_type,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            user_id=user_id,
            signal=signal,
            payload=_truncate(payload),
            payload_hash=payload_hash or compute_payload_hash(webhook_id, payload),
            remote_ip=remote_ip,
            outcome=OUTCOME_RECEIVED,
            stages=[],
            order_ids=[],
        )
        db_session.add(delivery)
        db_session.commit()
        return delivery.id
    except Exception:
        logger.exception("Failed to record webhook delivery")
        db_session.rollback()
        return None


def update_outcome(
    delivery_id,
    outcome,
    reason_code=None,
    reason_detail=None,
    order_ids=None,
    completed=True,
):
    """Set a delivery's outcome, and optionally close it out with a duration.

    Never raises, for the same reason as record_received.
    """
    if not delivery_id:
        return
    try:
        delivery = db_session.query(WebhookDelivery).filter_by(id=delivery_id).first()
        if not delivery:
            return
        delivery.outcome = outcome
        if reason_code is not None:
            delivery.reason_code = reason_code
        if reason_detail is not None:
            delivery.reason_detail = str(reason_detail)[:2000]
        if order_ids:
            existing = list(delivery.order_ids or [])
            existing.extend(str(o) for o in order_ids)
            delivery.order_ids = existing
        if completed:
            now = datetime.now()
            delivery.completed_at = now
            if delivery.received_at:
                delivery.duration_ms = int((now - delivery.received_at).total_seconds() * 1000)
        db_session.commit()
    except Exception:
        logger.exception(f"Failed to update webhook delivery {delivery_id}")
        db_session.rollback()


def append_stage(delivery_id, stage, outcome, detail=None, ms=None):
    """Append one stage decision to a delivery's trace.

    This is the hook the future module pipeline writes to — one call per module,
    giving a step-by-step record of what each stage decided and how long it took.

    JSON columns are replaced wholesale rather than mutated in place; SQLAlchemy
    does not track in-place mutation of a plain JSON column.
    """
    if not delivery_id:
        return
    try:
        delivery = db_session.query(WebhookDelivery).filter_by(id=delivery_id).first()
        if not delivery:
            return
        entry = {"stage": stage, "outcome": outcome}
        if detail is not None:
            entry["detail"] = str(detail)[:1000]
        if ms is not None:
            entry["ms"] = round(float(ms), 2)
        delivery.stages = list(delivery.stages or []) + [entry]
        db_session.commit()
    except Exception:
        logger.exception(f"Failed to append stage to webhook delivery {delivery_id}")
        db_session.rollback()


def find_recent_duplicate(webhook_id, payload_hash, window_seconds):
    """Return the id of a matching delivery inside the window, else None.

    Only deliveries that were actually acted upon count as duplicates —
    a prior request that was itself rejected (or already flagged duplicate)
    must not suppress a later genuine signal, otherwise one malformed retry
    could shadow a real trade.
    """
    if not payload_hash or window_seconds <= 0:
        return None
    try:
        cutoff = datetime.now() - timedelta(seconds=window_seconds)
        row = (
            db_session.query(WebhookDelivery.id)
            .filter(
                WebhookDelivery.webhook_id == str(webhook_id),
                WebhookDelivery.payload_hash == payload_hash,
                WebhookDelivery.received_at >= cutoff,
                WebhookDelivery.outcome.in_(
                    [OUTCOME_RECEIVED, OUTCOME_ACCEPTED, OUTCOME_PROCESSED]
                ),
            )
            .order_by(WebhookDelivery.received_at.desc())
            .first()
        )
        return row[0] if row else None
    except Exception:
        logger.exception("Duplicate lookup failed")
        db_session.rollback()
        return None


def get_deliveries(
    webhook_id=None,
    strategy_id=None,
    user_id=None,
    outcome=None,
    limit=100,
    offset=0,
):
    """Query deliveries newest-first for the UI."""
    try:
        q = db_session.query(WebhookDelivery)
        if webhook_id:
            q = q.filter(WebhookDelivery.webhook_id == str(webhook_id))
        if strategy_id:
            q = q.filter(WebhookDelivery.strategy_id == strategy_id)
        if user_id:
            q = q.filter(WebhookDelivery.user_id == user_id)
        if outcome:
            q = q.filter(WebhookDelivery.outcome == outcome)
        rows = (
            q.order_by(WebhookDelivery.received_at.desc())
            .limit(min(int(limit), 500))
            .offset(int(offset))
            .all()
        )
        return [r.to_dict() for r in rows]
    except Exception:
        logger.exception("Failed to query webhook deliveries")
        db_session.rollback()
        return []


def get_delivery(delivery_id, user_id=None):
    """Fetch one delivery. When user_id is given, enforces ownership."""
    try:
        q = db_session.query(WebhookDelivery).filter_by(id=delivery_id)
        if user_id:
            q = q.filter(WebhookDelivery.user_id == user_id)
        row = q.first()
        return row.to_dict() if row else None
    except Exception:
        logger.exception(f"Failed to fetch webhook delivery {delivery_id}")
        db_session.rollback()
        return None


def purge_old_deliveries(retention_days=None):
    """Delete deliveries older than the retention window. Returns rows removed."""
    days = retention_days if retention_days is not None else DELIVERY_RETENTION_DAYS
    if days <= 0:
        return 0
    try:
        cutoff = datetime.now() - timedelta(days=days)
        deleted = (
            db_session.query(WebhookDelivery)
            .filter(WebhookDelivery.received_at < cutoff)
            .delete(synchronize_session=False)
        )
        db_session.commit()
        if deleted:
            logger.info(f"Purged {deleted} webhook delivery rows older than {days} days")
        return deleted
    except Exception:
        logger.exception("Failed to purge webhook deliveries")
        db_session.rollback()
        return 0
