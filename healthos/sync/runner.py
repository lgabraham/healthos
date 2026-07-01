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
from . import calendar, eight_sleep, garmin, harvia, whoop
from .persistence import (
    SyncResult,
    upsert_calendar_events,
    upsert_events,
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
    "harvia": (harvia.pull, harvia.SOURCE),
}


def sync_source(
    name: str, start: _date, end: _date, sync_type: str = "daily", replace: bool = False
) -> SyncResult:
    """Pull and persist a single source for the inclusive date range.

    When ``replace`` is set, the source's existing rows in the window are
    deleted before the freshly-pulled data is written — so an upstream deletion
    (e.g. an Eight Sleep session you removed because a kid was in the bed) is
    mirrored locally instead of leaving a stale night behind. The delete happens
    only after a successful pull, in the same transaction as the insert, so a
    network failure never wipes data without replacing it.
    """
    pull_fn, source = SOURCES[name]
    result = SyncResult(source=source, sync_type=sync_type)
    try:
        data = pull_fn(start, end)  # may raise -> nothing is deleted
        with get_session() as session:
            if replace:
                # Only clear the span the pull ACTUALLY returned, not the whole
                # requested window. Eight Sleep's /intervals endpoint ignores the
                # date range and returns just the most-recent sessions, so a blind
                # window-wide delete would wipe older canonical nights it simply
                # didn't include and never rewrite them. Clamping to the pulled
                # span still mirrors an upstream deletion *within* that span (a gap
                # day the provider dropped gets deleted and not re-added) while
                # leaving days outside the provider's reach untouched. An empty
                # pull deletes nothing — protecting against a transient blank.
                span = _pulled_date_span(data)
                if span:
                    lo, hi = max(start, span[0]), min(end, span[1])
                    if lo <= hi:
                        _delete_source_window(session, source, lo, hi)
            written = 0
            written += upsert_metrics(session, data.get("metrics", []))
            written += upsert_sleep(session, data.get("sleeps", []))
            written += upsert_workouts(session, data.get("workouts", []))
            written += upsert_calendar_events(session, data.get("calendar_events", []))
            written += upsert_events(session, data.get("events", []))
            result.records_written = written
            write_sync_log(session, result)
        log.info("Synced %s %s..%s: %d records%s", source, start, end,
                 result.records_written, " (replace)" if replace else "")
    except Exception as exc:  # noqa: BLE001 - isolate provider failures
        log.exception("Sync failed for %s", source)
        result.errors.append(str(exc))
        with get_session() as session:
            write_sync_log(session, result)
    return result


def _pulled_date_span(data: dict) -> tuple[_date, _date] | None:
    """(min, max) date across the pulled metrics/sleeps/workouts, or None if the
    pull returned nothing datable — used to bound a replace-mode delete to the
    range the provider actually reported on."""
    dates = [
        rec.date
        for key in ("metrics", "sleeps", "workouts")
        for rec in (data.get(key) or [])
        if getattr(rec, "date", None) is not None
    ]
    return (min(dates), max(dates)) if dates else None


def _delete_source_window(session, source: str, start: _date, end: _date) -> None:
    """Drop a source's metrics/sleeps/workouts in [start, end] (inclusive) so a
    re-pull becomes an exact mirror of the provider, deletions included."""
    from sqlalchemy import delete

    from ..models import DailyEvent, DailyMetric, SleepSession, Workout

    # DailyEvent included so a Harvia re-pull mirrors deletions. Inference rows
    # use source "inferred_*" and manual rows use "manual", so they're untouched
    # by a device source's window delete.
    for model in (DailyMetric, SleepSession, Workout, DailyEvent):
        session.execute(
            delete(model).where(
                model.source == source, model.date >= start, model.date <= end
            )
        )


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


def manual_sync(days: int = 7, source: str | None = None) -> list[SyncResult]:
    """User-triggered refresh: re-pull the trailing ``days`` (through today) in
    REPLACE mode so corrections/deletions upstream take effect. One source if
    given, else all; re-runs inference afterward."""
    from datetime import datetime, timedelta

    end = datetime.now(settings.tz).date()
    start = end - timedelta(days=days - 1)
    names = [source] if source else list(SOURCES)
    log.info("Manual refresh %s..%s (sources=%s, replace)", start, end, names)
    results = [sync_source(n, start, end, sync_type="manual", replace=True) for n in names]
    _run_inference(start, end)
    return results
