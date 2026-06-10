"""Orchestrates pulling from one or all sources and persisting results.

This is the seam the scheduler, the backfill script, and manual CLI/API
triggers all call. Each source is isolated so one provider failing (expired
token, rate limit) never blocks the others, and every run lands a sync_log row.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date as _date

from ..config import settings
from ..database import get_session
from . import calendar, eight_sleep, garmin, whoop
from .persistence import (
    SyncResult,
    upsert_calendar_events,
    upsert_metrics,
    upsert_sleep,
    upsert_workouts,
    write_sync_log,
)

log = logging.getLogger(__name__)

# name -> (pull callable, source label)
SOURCES: dict[str, tuple[Callable[[_date, _date], dict], str]] = {
    "whoop": (whoop.pull, whoop.SOURCE),
    "garmin": (garmin.pull, garmin.SOURCE),
    "eight_sleep": (eight_sleep.pull, eight_sleep.SOURCE),
    "calendar": (calendar.pull, calendar.SOURCE),
}


def sync_source(name: str, start: _date, end: _date, sync_type: str = "daily") -> SyncResult:
    """Pull and persist a single source for the inclusive date range."""
    pull_fn, source = SOURCES[name]
    result = SyncResult(source=source, sync_type=sync_type)
    try:
        data = pull_fn(start, end)
        with get_session() as session:
            written = 0
            written += upsert_metrics(session, data.get("metrics", []))
            written += upsert_sleep(session, data.get("sleeps", []))
            written += upsert_workouts(session, data.get("workouts", []))
            written += upsert_calendar_events(session, data.get("calendar_events", []))
            result.records_written = written
            write_sync_log(session, result)
        log.info("Synced %s %s..%s: %d records", source, start, end, result.records_written)
    except Exception as exc:  # noqa: BLE001 - isolate provider failures
        log.exception("Sync failed for %s", source)
        result.errors.append(str(exc))
        with get_session() as session:
            write_sync_log(session, result)
    return result


def sync_all(start: _date, end: _date, sync_type: str = "daily") -> list[SyncResult]:
    """Pull every configured source, then run behavioral inference."""
    results = [sync_source(name, start, end, sync_type) for name in SOURCES]
    _run_inference(start, end)
    return results


def _run_inference(start: _date, end: _date) -> None:
    """Run inference for each day in range. Imported lazily to avoid a cycle."""
    from ..inference.behavioral import run_inference_for_date

    with get_session() as session:
        day = start
        while day <= end:
            try:
                run_inference_for_date(session, day)
            except Exception:  # noqa: BLE001
                log.exception("Inference failed for %s", day)
            day = _date.fromordinal(day.toordinal() + 1)


def daily_sync() -> list[SyncResult]:
    """Entry point for the nightly job: sync yesterday in local time."""
    from datetime import datetime, timedelta

    today_local = datetime.now(settings.tz).date()
    yesterday = today_local - timedelta(days=1)
    log.info("Running nightly sync for %s", yesterday)
    return sync_all(yesterday, yesterday, sync_type="daily")
