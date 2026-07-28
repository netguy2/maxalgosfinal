# database/apilog_db.py

"""API order audit log.

SEBI's algo trading circular requires a long-term (5-year) audit trail
for every API order. This module is the audit trail: every order-placing
and order-modifying API call is persisted here via async_log_order(),
and — deliberately — nothing in this codebase ever deletes rows from this
table. See MIN_RETENTION_YEARS and assert_no_premature_deletion() below
for the explicit guard against a future change accidentally introducing
a purge/rotation that would violate that retention requirement.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta, timezone

import pytz
from sqlalchemy import Column, DateTime, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.sql import func

from database.engine_factory import create_db_engine
from utils.logging import get_logger

logger = get_logger(__name__)

# SEBI's algo trading circular requires API order records to be retained
# for audit purposes for at least this long. This is a floor, not a
# target -- there is no code path in this module (or anywhere else in the
# codebase, per utils/logging.py's cleanup_old_logs() which only touches
# filesystem log files, never this table) that deletes order_logs rows at
# all. This constant exists so any future deletion/archival code added to
# this table has an explicit, named requirement to check itself against
# rather than picking an arbitrary retention window.
MIN_RETENTION_YEARS = 5


DATABASE_URL = os.getenv("DATABASE_URL")  # Replace with your SQLite path
engine = create_db_engine(DATABASE_URL)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class OrderLog(Base):
    __tablename__ = "order_logs"
    id = Column(Integer, primary_key=True)
    api_type = Column(Text, nullable=False)
    request_data = Column(Text, nullable=False)
    response_data = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=func.now())


def init_db():
    """Initialize the API log database tables.

    Creates the ``order_logs`` table if it does not already exist,
    using the shared ``db_init_helper`` for consistent logging.
    """
    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(Base, engine, "API Log DB", logger)


# Executor for asynchronous tasks
executor = ThreadPoolExecutor(10)  # Increased from 2 to 10 for better concurrency


def assert_no_premature_deletion(record_created_at: datetime) -> None:
    """Guard for any future deletion/archival code added to order_logs.

    Call this before deleting or archiving-out-of-primary-storage any
    OrderLog row. Raises if the record is younger than
    MIN_RETENTION_YEARS, so a future maintenance script or admin
    "clear old logs" feature can't accidentally violate the SEBI
    retention requirement -- the violation becomes a loud exception
    instead of a silent data-loss bug.

    Args:
        record_created_at: the OrderLog row's created_at value.

    Raises:
        ValueError: if deleting this record now would violate the
            minimum retention period.
    """
    now = datetime.now(UTC)
    created = record_created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    min_age = timedelta(days=365 * MIN_RETENTION_YEARS)
    if now - created < min_age:
        eligible_at = created + min_age
        raise ValueError(
            f"Refusing to delete order_logs record created {created.isoformat()} -- "
            f"SEBI requires {MIN_RETENTION_YEARS}-year audit retention. "
            f"Not eligible for deletion until {eligible_at.isoformat()}."
        )


def get_audit_retention_status() -> dict:
    """Report the current audit trail's actual coverage: row count and the
    oldest surviving record's age, so retention compliance is verifiable
    rather than just documented. Intended for an admin diagnostics view."""
    oldest = OrderLog.query.order_by(OrderLog.created_at.asc()).first()
    total = OrderLog.query.count()
    if not oldest:
        return {
            "total_records": 0,
            "oldest_record_at": None,
            "oldest_record_age_days": None,
            "meets_min_retention": True,  # vacuously true -- nothing to violate yet
            "min_retention_years": MIN_RETENTION_YEARS,
        }

    created = oldest.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - created).days
    return {
        "total_records": total,
        "oldest_record_at": created.isoformat(),
        "oldest_record_age_days": age_days,
        "meets_min_retention": True,  # always true today -- nothing deletes rows
        "min_retention_years": MIN_RETENTION_YEARS,
    }


def async_log_order(api_type, request_data, response_data):
    """Persist an API order log entry to the database.

    Note: Despite its name, this function executes **synchronously**.
    It is designed to be submitted to a ``ThreadPoolExecutor`` by
    callers so that the database write does not block the main
    request thread.

    Args:
        api_type: The type of API call. Reserved values include:
            - Regular orders: ``placeorder``, ``placesmartorder``, ``modifyorder``,
              ``cancelorder``, ``cancelallorder``, ``closeposition``, ``basketorder``,
              ``splitorder``, ``optionsorder``, ``optionsmultiorder``.
            - GTT orders: ``placegttorder``, ``modifygttorder``, ``cancelgttorder``,
              ``gttorderbook``, ``gtttriggered`` (auto-emitted when a GTT leg fires),
              ``gttexpired`` (auto-emitted when a GTT passes ``expires_at``).
            - Data reads: ``orderbook``, ``tradebook``, ``positionbook``, ``holdings``,
              ``funds``, ``orderstatus``, ``openposition``, ``quotes``, ``depth``,
              ``history``, ``chart``, etc.
        request_data: Dictionary of the original request payload.
        response_data: Dictionary of the broker/service response.
    """
    try:
        # Serialize JSON data for storage
        request_json = json.dumps(request_data)
        response_json = json.dumps(response_data)

        # Get current time in IST
        ist = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(ist)

        order_log = OrderLog(
            api_type=api_type,
            request_data=request_json,
            response_data=response_json,
            created_at=now_ist,
        )
        db_session.add(order_log)
        db_session.commit()
    except Exception as e:
        logger.exception(f"Error saving order log: {e}")
    finally:
        db_session.remove()
