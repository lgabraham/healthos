"""Idempotent upsert helpers shared by every sync module.

Sync modules normalize provider payloads into plain dataclasses / dicts and
hand them here; this module owns all the SQL-y concerns (conflict handling,
canonical flagging, sync logging) so the provider code stays focused on each
API's quirks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..canonical import is_canonical_metric, is_canonical_sleep
from ..models import DailyMetric, SleepSession, SyncLog, Workout


@dataclass
class MetricPoint:
    """One normalized metric reading destined for ``daily_metrics``."""

    date: _date
    metric: str
    value: float
    unit: str | None
    source: str
    raw_json: dict | None = None


@dataclass
class SleepRecord:
    date: _date
    source: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    total_minutes: int | None = None
    rem_minutes: int | None = None
    deep_minutes: int | None = None
    light_minutes: int | None = None
    awake_minutes: int | None = None
    sleep_score: float | None = None
    stages_json: dict | None = None
    raw_json: dict | None = None


@dataclass
class WorkoutRecord:
    date: _date
    source: str
    external_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    sport_type: str | None = None
    duration_minutes: int | None = None
    hr_avg: int | None = None
    hr_max: int | None = None
    calories: int | None = None
    distance_km: float | None = None
    tss: float | None = None
    raw_json: dict | None = None


@dataclass
class CalendarEventRecord:
    date: _date
    uid: str
    title: str | None = None
    location: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    all_day: bool = False
    is_evening: bool = False
    keywords: list[str] | None = None
    source: str = "ics"


@dataclass
class SyncResult:
    source: str
    sync_type: str
    records_written: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.errors and self.records_written:
            return "partial"
        if self.errors:
            return "error"
        return "success"


def upsert_metrics(session: Session, points: list[MetricPoint]) -> int:
    """Insert/update metric points, keyed on (date, metric, source)."""
    written = 0
    for p in points:
        if p.value is None:
            continue
        stmt = (
            pg_insert(DailyMetric)
            .values(
                date=p.date,
                metric=p.metric,
                value=p.value,
                unit=p.unit,
                source=p.source,
                is_canonical=is_canonical_metric(p.metric, p.source),
                raw_json=p.raw_json,
            )
            .on_conflict_do_update(
                constraint="uq_metric_date_source",
                set_={
                    "value": p.value,
                    "unit": p.unit,
                    "is_canonical": is_canonical_metric(p.metric, p.source),
                    "raw_json": p.raw_json,
                },
            )
        )
        session.execute(stmt)
        written += 1
    return written


def upsert_sleep(session: Session, records: list[SleepRecord]) -> int:
    """Insert/update sleep sessions, deduped on (date, source).

    There is no DB-level unique constraint on sleep_sessions (a night can in
    theory have naps), so we dedupe in application code on (date, source) to
    keep nightly re-syncs idempotent.
    """
    written = 0
    for r in records:
        existing = session.scalars(
            select(SleepSession).where(
                SleepSession.date == r.date, SleepSession.source == r.source
            )
        ).first()
        canonical = is_canonical_sleep(r.source)
        if existing is None:
            session.add(
                SleepSession(
                    date=r.date,
                    source=r.source,
                    start_time=r.start_time,
                    end_time=r.end_time,
                    total_minutes=r.total_minutes,
                    rem_minutes=r.rem_minutes,
                    deep_minutes=r.deep_minutes,
                    light_minutes=r.light_minutes,
                    awake_minutes=r.awake_minutes,
                    sleep_score=r.sleep_score,
                    stages_json=r.stages_json,
                    raw_json=r.raw_json,
                    is_canonical=canonical,
                )
            )
        else:
            existing.start_time = r.start_time
            existing.end_time = r.end_time
            existing.total_minutes = r.total_minutes
            existing.rem_minutes = r.rem_minutes
            existing.deep_minutes = r.deep_minutes
            existing.light_minutes = r.light_minutes
            existing.awake_minutes = r.awake_minutes
            existing.sleep_score = r.sleep_score
            existing.stages_json = r.stages_json
            existing.raw_json = r.raw_json
            existing.is_canonical = canonical
        written += 1
    return written


def upsert_workouts(session: Session, records: list[WorkoutRecord]) -> int:
    """Insert/update workouts, deduped on (source, external_id) when present."""
    written = 0
    for r in records:
        existing = None
        if r.external_id is not None:
            existing = session.scalars(
                select(Workout).where(
                    Workout.source == r.source, Workout.external_id == r.external_id
                )
            ).first()
        if existing is None:
            session.add(
                Workout(
                    date=r.date,
                    source=r.source,
                    external_id=r.external_id,
                    start_time=r.start_time,
                    end_time=r.end_time,
                    sport_type=r.sport_type,
                    duration_minutes=r.duration_minutes,
                    hr_avg=r.hr_avg,
                    hr_max=r.hr_max,
                    calories=r.calories,
                    distance_km=r.distance_km,
                    tss=r.tss,
                    raw_json=r.raw_json,
                )
            )
        else:
            existing.date = r.date
            existing.start_time = r.start_time
            existing.end_time = r.end_time
            existing.sport_type = r.sport_type
            existing.duration_minutes = r.duration_minutes
            existing.hr_avg = r.hr_avg
            existing.hr_max = r.hr_max
            existing.calories = r.calories
            existing.distance_km = r.distance_km
            existing.tss = r.tss
            existing.raw_json = r.raw_json
        written += 1
    return written


def upsert_calendar_events(session: Session, records: list[CalendarEventRecord]) -> int:
    """Insert/update calendar events, deduped on (uid, start_time)."""
    from ..models import CalendarEvent

    written = 0
    for r in records:
        stmt = (
            pg_insert(CalendarEvent)
            .values(
                date=r.date,
                uid=r.uid,
                title=r.title,
                location=r.location,
                start_time=r.start_time,
                end_time=r.end_time,
                all_day=r.all_day,
                is_evening=r.is_evening,
                keywords=r.keywords,
                source=r.source,
            )
            .on_conflict_do_update(
                constraint="uq_calendar_uid_start",
                set_={
                    "date": r.date,
                    "title": r.title,
                    "location": r.location,
                    "end_time": r.end_time,
                    "all_day": r.all_day,
                    "is_evening": r.is_evening,
                    "keywords": r.keywords,
                },
            )
        )
        session.execute(stmt)
        written += 1
    return written


def write_sync_log(session: Session, result: SyncResult) -> None:
    session.add(
        SyncLog(
            source=result.source,
            sync_type=result.sync_type,
            status=result.status,
            records_written=result.records_written,
            error_message="; ".join(result.errors) if result.errors else None,
        )
    )
