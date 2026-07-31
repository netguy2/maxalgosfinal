# database/payment_db.py
"""Payment audit trail for Razorpay-backed flows (setup activation fee,
marketplace subscriptions). One row per Razorpay Order, updated as the
order/payment progresses through created -> captured/failed. This table is
the source of truth the admin Payment Settings page and the webhook
reconciliation path both read/write against.
"""

import os

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    String,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.sql import func

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_db_engine(DATABASE_URL)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class Payment(Base):
    """One Razorpay order, from creation through capture/failure.

    user_id is nullable because setup-fee payments happen BEFORE the admin
    account exists -- the account is only created after the payment is
    verified (see blueprints/payments.py). It is backfilled once the account
    is created.
    """

    __tablename__ = "payments"

    id = Column(Integer, primary_key=True)
    user_id = Column(String(255), nullable=True, index=True)
    purpose = Column(String(30), nullable=False)  # 'setup' | 'subscription'
    razorpay_order_id = Column(String(64), nullable=False, unique=True, index=True)
    razorpay_payment_id = Column(String(64), nullable=True, index=True)
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String(10), nullable=False, default="INR")
    status = Column(String(20), nullable=False, default="created")  # created|captured|failed
    # subscription_id / strategy_id are informational references into
    # database/strategy_db.py's Subscription/Strategy tables -- NOT enforced
    # SQLAlchemy ForeignKeys, because that module uses a separate declarative
    # Base (own metadata registry) even though it's the same physical
    # maxalgos.db file; create_all() cannot resolve a FK across two Base
    # registries. Same convention already used elsewhere in this repo (e.g.
    # Deployment.version_id in strategy_db.py).
    subscription_id = Column(Integer, nullable=True)
    strategy_id = Column(Integer, nullable=True)  # marketplace payments only; informational
    created_at = Column(DateTime(timezone=True), nullable=False, default=func.now())
    verified_at = Column(DateTime(timezone=True), nullable=True)


def init_db():
    """Initialize the payments database"""
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "Payments DB", logger)


def create_payment_record(
    purpose: str,
    razorpay_order_id: str,
    amount_paise: int,
    user_id: str | None = None,
    strategy_id: int | None = None,
    currency: str = "INR",
) -> Payment:
    """Insert a `created` payment row for a freshly-made Razorpay order."""
    payment = Payment(
        user_id=user_id,
        purpose=purpose,
        razorpay_order_id=razorpay_order_id,
        amount_paise=amount_paise,
        currency=currency,
        status="created",
        strategy_id=strategy_id,
    )
    db_session.add(payment)
    db_session.commit()
    return payment


def get_payment_by_order_id(razorpay_order_id: str) -> Payment | None:
    return Payment.query.filter_by(razorpay_order_id=razorpay_order_id).first()


def mark_payment_captured(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    user_id: str | None = None,
    subscription_id: int | None = None,
) -> Payment | None:
    """Mark a payment row captured. Idempotent -- safe to call from both the
    verify-callback route and the webhook reconciliation path without double
    -processing (callers must still gate the side effect, e.g. "only create
    the account once", on the row's PRIOR status)."""
    payment = get_payment_by_order_id(razorpay_order_id)
    if not payment:
        logger.warning(f"Payment record not found for order {razorpay_order_id}")
        return None

    payment.razorpay_payment_id = razorpay_payment_id
    payment.status = "captured"
    payment.verified_at = func.now()
    if user_id is not None:
        payment.user_id = user_id
    if subscription_id is not None:
        payment.subscription_id = subscription_id
    db_session.commit()
    return payment


def mark_payment_failed(razorpay_order_id: str) -> Payment | None:
    payment = get_payment_by_order_id(razorpay_order_id)
    if not payment:
        return None
    payment.status = "failed"
    db_session.commit()
    return payment


def list_recent_payments(limit: int = 100) -> list[Payment]:
    """Admin reconciliation view -- most recent payments first."""
    return Payment.query.order_by(Payment.created_at.desc()).limit(limit).all()
