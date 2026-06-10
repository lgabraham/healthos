"""Dashboard REST endpoints.

Everything the React frontend needs: a daily summary, metric trends, sleep and
workout history, behavioral events, correlations, and sync status. Timestamps
are converted to local time here so the frontend can render them directly.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..config import settings
from ..correlate import correlate_metrics, prebuilt_cards
from ..database import db_session
from ..models import CalendarEvent, DailyEvent, SleepSession, SyncLog, Workout
from ..queries import (
    MIN_INFERENCE_DAYS,
    best_available,
    best_available_sleep,
    data_day_count,
    latest_workout,
    metric_series,
    rolling_baseline,
)
from ..stats import rolling_average

router = APIRouter(prefix="/api", tags=["metrics"])

# Metrics surfaced on the daily view, with display units.
DAILY_METRICS = {
    "recovery_score": "score",
    "hrv_rmssd": "ms",
    "resting_hr": "bpm",
    "strain_score": "score",
    "sleep_duration_minutes": "minutes",
    "steps": "steps",
}


def _local(dt):
    return dt.astimezone(settings.tz).isoformat() if dt else None


@router.get("/status")
def status(db: Session = Depends(db_session)) -> dict:
    """Overall app/data readiness, incl. the 'building baseline' flag."""
    days = data_day_count(db)
    last_sync = db.scalars(select(SyncLog).order_by(desc(SyncLog.synced_at)).limit(1)).first()
    return {
        "data_days": days,
        "building_baseline": days < MIN_INFERENCE_DAYS,
        "min_days_for_inference": MIN_INFERENCE_DAYS,
        "timezone": settings.timezone,
        "last_sync": {
            "source": last_sync.source,
            "status": last_sync.status,
            "at": _local(last_sync.synced_at),
        }
        if last_sync
        else None,
    }


@router.get("/daily")
def daily(
    date: str | None = Query(default=None, description="YYYY-MM-DD; defaults to latest"),
    db: Session = Depends(db_session),
) -> dict:
    """All canonical metrics, sleep, events, and last workout for a date."""
    day = _date.fromisoformat(date) if date else _latest_date(db)

    metrics = {}
    for metric, unit in DAILY_METRICS.items():
        resolved = best_available(db, day, metric)
        value = resolved.value
        base = rolling_baseline(db, metric, day)
        # A fallback value comes from a different instrument than the canonical
        # baseline, so suppress the (misleading) delta in that case.
        delta = (
            round((value - base.mean) / base.mean * 100, 1)
            if value is not None and base.mean and not resolved.is_fallback
            else None
        )
        metrics[metric] = {
            "value": value,
            "unit": unit,
            "source": resolved.source,
            "is_fallback": resolved.is_fallback,
            "baseline": round(base.mean, 1) if base.mean is not None else None,
            "baseline_n": base.n,
            "baseline_trustworthy": base.trustworthy,
            "delta_pct": delta,
        }

    sleep = best_available_sleep(db, day)
    last_wk = latest_workout(db, day)
    events = db.scalars(select(DailyEvent).where(DailyEvent.date == day)).all()

    # The "why" layer: events today + the night before (which shaped last sleep).
    cal = db.scalars(
        select(CalendarEvent)
        .where(CalendarEvent.date.in_([day, day - timedelta(days=1)]))
        .order_by(CalendarEvent.start_time.asc().nullsfirst())
    ).all()

    return {
        "date": day.isoformat(),
        "metrics": metrics,
        "sleep": _sleep_dict(sleep),
        "events": [_event_dict(e) for e in events],
        "calendar": [_calendar_dict(c) for c in cal],
        "last_workout": _workout_dict(last_wk),
        "building_baseline": data_day_count(db) < MIN_INFERENCE_DAYS,
    }


@router.get("/calendar")
def calendar_events(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(db_session),
) -> list[dict]:
    rows = db.scalars(
        select(CalendarEvent)
        .where(CalendarEvent.date >= _date.today() - timedelta(days=days))
        .order_by(CalendarEvent.start_time.desc().nullslast())
    ).all()
    return [_calendar_dict(c) for c in rows]


@router.get("/trend/{metric}")
def trend(
    metric: str,
    days: int = Query(default=30, ge=1, le=365),
    rolling: int = Query(default=7, ge=1, le=60),
    db: Session = Depends(db_session),
) -> dict:
    """Time series for a metric with a rolling average + event markers."""
    series = metric_series(db, metric, days)
    enriched = rolling_average(series, rolling)
    event_rows = db.scalars(
        select(DailyEvent).where(DailyEvent.date >= _date.today() - timedelta(days=days))
    ).all()
    return {
        "metric": metric,
        "days": days,
        "rolling_window": rolling,
        "series": enriched,
        "events": [_event_dict(e) for e in event_rows],
    }


@router.get("/sleep")
def sleep_history(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(db_session),
) -> list[dict]:
    rows = db.scalars(
        select(SleepSession)
        .where(
            SleepSession.is_canonical.is_(True),
            SleepSession.date >= _date.today() - timedelta(days=days),
        )
        .order_by(SleepSession.date.asc())
    ).all()
    return [_sleep_dict(s) for s in rows]


@router.get("/workouts")
def workout_history(
    days: int = Query(default=30, ge=1, le=365),
    db: Session = Depends(db_session),
) -> list[dict]:
    rows = db.scalars(
        select(Workout)
        .where(Workout.date >= _date.today() - timedelta(days=days))
        .order_by(Workout.start_time.desc().nullslast(), Workout.date.desc())
    ).all()
    return [_workout_dict(w) for w in rows]


@router.get("/events")
def events(
    days: int = Query(default=30, ge=1, le=365),
    event_type: str | None = Query(default=None),
    db: Session = Depends(db_session),
) -> list[dict]:
    stmt = (
        select(DailyEvent)
        .where(DailyEvent.date >= _date.today() - timedelta(days=days))
        .order_by(DailyEvent.date.desc())
    )
    if event_type:
        stmt = stmt.where(DailyEvent.event_type == event_type)
    return [_event_dict(e) for e in db.scalars(stmt).all()]


@router.get("/correlate")
def correlate_endpoint(
    metric_a: str,
    metric_b: str,
    days: int = Query(default=90, ge=7, le=365),
    lag: int = Query(default=0, ge=0, le=7),
    db: Session = Depends(db_session),
) -> dict:
    return correlate_metrics(db, metric_a, metric_b, days, lag_days=lag).to_dict()


@router.get("/correlations")
def correlations(
    days: int = Query(default=90, ge=14, le=365),
    db: Session = Depends(db_session),
) -> list[dict]:
    return prebuilt_cards(db, days)


@router.get("/sync-log")
def sync_log(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(db_session),
) -> list[dict]:
    rows = db.scalars(select(SyncLog).order_by(desc(SyncLog.synced_at)).limit(limit)).all()
    return [
        {
            "source": r.source,
            "sync_type": r.sync_type,
            "status": r.status,
            "records_written": r.records_written,
            "error_message": r.error_message,
            "synced_at": _local(r.synced_at),
        }
        for r in rows
    ]


# -- serializers ------------------------------------------------------------
def _latest_date(db: Session) -> _date:
    from sqlalchemy import func

    from ..models import DailyMetric

    # Latest *complete night*: a day with an HRV reading from ANY source (so a
    # recent Eight Sleep night counts, not just Whoop), which avoids landing on
    # a partial "today" that only has an accumulating strain value.
    anchor = db.scalar(
        select(func.max(DailyMetric.date)).where(DailyMetric.metric == "hrv_rmssd")
    )
    return anchor or db.scalar(select(func.max(DailyMetric.date))) or _date.today()


def _sleep_dict(s: SleepSession | None) -> dict | None:
    if s is None:
        return None
    return {
        "date": s.date.isoformat(),
        "source": s.source,
        "start_time": _local(s.start_time),
        "end_time": _local(s.end_time),
        "total_minutes": s.total_minutes,
        "rem_minutes": s.rem_minutes,
        "deep_minutes": s.deep_minutes,
        "light_minutes": s.light_minutes,
        "awake_minutes": s.awake_minutes,
        "sleep_score": float(s.sleep_score) if s.sleep_score is not None else None,
    }


def _workout_dict(w: Workout | None) -> dict | None:
    if w is None:
        return None
    return {
        "date": w.date.isoformat(),
        "source": w.source,
        "sport_type": w.sport_type,
        "start_time": _local(w.start_time),
        "end_time": _local(w.end_time),
        "duration_minutes": w.duration_minutes,
        "hr_avg": w.hr_avg,
        "hr_max": w.hr_max,
        "calories": w.calories,
        "distance_km": float(w.distance_km) if w.distance_km is not None else None,
        "tss": float(w.tss) if w.tss is not None else None,
    }


def _calendar_dict(c: CalendarEvent) -> dict:
    return {
        "date": c.date.isoformat(),
        "title": c.title,  # local dashboard only; redacted by the MCP server
        "location": c.location,
        "start_time": _local(c.start_time),
        "end_time": _local(c.end_time),
        "all_day": c.all_day,
        "is_evening": c.is_evening,
        "keywords": c.keywords or [],
    }


def _event_dict(e: DailyEvent) -> dict:
    return {
        "date": e.date.isoformat(),
        "event_type": e.event_type,
        "value": float(e.value) if e.value is not None else None,
        "confidence": e.confidence,
        "notes": e.notes,
        "source": e.source,
    }
