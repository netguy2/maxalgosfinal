"""Daily scheduler for broker auto session refresh.

Runs services.broker_auto_refresh_service.refresh_all_enabled() once each
morning after the ~3 AM IST broker-token death and before market open, so
opted-in password+TOTP broker sessions (angel/fivepaisa/motilal) are
already refreshed when the user arrives. See
docs/plans/2026-07-16-broker-auto-session-refresh-plan.md.

Self-contained BackgroundScheduler (mirrors the broker-keepalive daemon's
"start once at app init" pattern) rather than sharing the flow/historify
scheduler, to keep this security-sensitive job isolated and independently
toggleable via BROKER_AUTO_REFRESH_ENABLED.
"""

import os
import threading

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from utils.logging import get_logger

logger = get_logger(__name__)

IST = pytz.timezone("Asia/Kolkata")

# Off unless explicitly enabled at the deployment level -- this feature
# stores broker 2FA seeds, so the whole subsystem stays behind a flag the
# operator turns on knowingly (individual users still opt in per broker on
# top of this).
_ENABLED = os.getenv("BROKER_AUTO_REFRESH_ENABLED", "False").lower() == "true"

# Default 08:30 IST: after the ~3 AM token death, comfortably before the
# 09:15 market open. Overridable via env (HH:MM, IST).
_RUN_TIME = os.getenv("BROKER_AUTO_REFRESH_TIME", "08:30")

_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


def _run_refresh_job():
    """Job body: refresh every enabled session. Never raises (a raised job
    would just be logged by APScheduler, but we log our own summary)."""
    try:
        from services.broker_auto_refresh_service import refresh_all_enabled

        summary = refresh_all_enabled()
        logger.info(f"Broker auto-refresh job: {summary['succeeded']}/{summary['attempted']} ok")
    except Exception as e:
        logger.exception(f"Broker auto-refresh job raised: {e}")


def start_broker_auto_refresh_scheduler():
    """Start the daily auto-refresh scheduler (idempotent). No-op if the
    feature is disabled."""
    global _scheduler

    if not _ENABLED:
        logger.info("Broker auto session refresh disabled via BROKER_AUTO_REFRESH_ENABLED")
        return

    try:
        hour, minute = (int(x) for x in _RUN_TIME.split(":"))
    except (ValueError, AttributeError):
        logger.error(
            f"Invalid BROKER_AUTO_REFRESH_TIME '{_RUN_TIME}' (want HH:MM) -- using 08:30 IST"
        )
        hour, minute = 8, 30

    with _lock:
        if _scheduler is not None and _scheduler.running:
            return
        _scheduler = BackgroundScheduler(
            timezone=IST,
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
        )
        _scheduler.add_job(
            _run_refresh_job,
            trigger=CronTrigger(hour=hour, minute=minute, day_of_week="mon-fri", timezone=IST),
            id="broker_auto_refresh_daily",
            replace_existing=True,
        )
        _scheduler.start()
        logger.info(
            f"Broker auto session refresh scheduled daily at {hour:02d}:{minute:02d} IST (Mon-Fri)"
        )
