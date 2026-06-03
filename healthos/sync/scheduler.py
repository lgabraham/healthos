"""APScheduler nightly cron, embedded in the FastAPI process.

Runs ``daily_sync`` at SYNC_HOUR local time every day. No separate worker
process is needed for this single-user tool.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import settings
from .runner import daily_sync

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler:
    """Create and start the background scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(
        _safe_daily_sync,
        CronTrigger(hour=settings.sync_hour, minute=0, timezone=settings.timezone),
        id="nightly_sync",
        name="HealthOS nightly sync",
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info("Scheduler started; nightly sync at %02d:00 %s", settings.sync_hour, settings.timezone)
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _safe_daily_sync() -> None:
    try:
        daily_sync()
    except Exception:  # noqa: BLE001 - never let a job crash the scheduler thread
        log.exception("Nightly sync job crashed")
