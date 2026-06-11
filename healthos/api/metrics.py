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
    ZERO_IS_MISSING,
    best_available,
    best_available_sleep,
    data_day_count,
    estimated_recovery,
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
    """Overall app/data readiness, incl. per-source freshness for the
    data-health banner (a stale Whoop quietly degrades half the app — say so)."""
    from sqlalchemy import func

    from ..models import DailyMetric

    days = data_day_count(db)
    last_sync = db.scalars(select(SyncLog).order_by(desc(SyncLog.synced_at)).limit(1)).first()
    latest = _latest_date_any(db)
    freshness = db.execute(
        select(DailyMetric.source, func.max(DailyMetric.date)).group_by(DailyMetric.source)
    ).all()
    sources = {
        src: {
            "last_data_date": d.isoformat(),
            "days_behind": (latest - d).days,
        }
        for src, d in freshness
    }
    return {
        "data_days": days,
        "building_baseline": days < MIN_INFERENCE_DAYS,
        "min_days_for_inference": MIN_INFERENCE_DAYS,
        "timezone": settings.timezone,
        "latest_data_date": latest.isoformat(),
        "sources": sources,
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
        source = resolved.source
        is_fallback = resolved.is_fallback
        is_estimated = False
        # When there's no real recovery score, estimate one from HRV + RHR.
        if metric == "recovery_score" and value is None:
            est = estimated_recovery(db, day)
            if est is not None:
                value, source, is_estimated = est, "estimated", True
        base = rolling_baseline(db, metric, day)
        # A fallback/estimated value isn't comparable to the canonical baseline,
        # so suppress the (misleading) delta in those cases.
        delta = (
            round((value - base.mean) / base.mean * 100, 1)
            if value is not None and base.mean and not is_fallback and not is_estimated
            else None
        )
        metrics[metric] = {
            "value": value,
            "unit": unit,
            "source": source,
            "is_fallback": is_fallback,
            "is_estimated": is_estimated,
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
    """Time series for a metric with a rolling average + event markers.

    Uses the best-available source per day (not just canonical), so the line
    extends through the current day wherever any device has data. The series is
    padded to one entry per calendar day (nulls for gaps) BEFORE the rolling
    average, so the average is calendar-aware (a reading from before a long gap
    can't leak into "this week"). The window start is clamped to the first date
    any metric has data — same anchor for every metric, so all charts share an
    identical x-axis without weeks of dead space when history is short.
    """
    series = metric_series(db, metric, days, canonical_only=False)
    by_date = {d: v for d, v in series}
    end = _latest_date_any(db)
    start = end - timedelta(days=days)
    first_data = _earliest_date_any(db)
    if first_data and first_data > start:
        start = first_data
    padded = [
        (start + timedelta(days=i), by_date.get(start + timedelta(days=i)))
        for i in range((end - start).days + 1)
    ]
    enriched = rolling_average(padded, rolling)
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


@router.get("/attribution")
def attribution_endpoint(
    date: str | None = Query(default=None, description="YYYY-MM-DD; defaults to latest"),
    db: Session = Depends(db_session),
) -> dict:
    """Why is today what it is: signed driver deviations + a plain headline."""
    from ..queries import attribution

    day = _date.fromisoformat(date) if date else _latest_date(db)
    return attribution(db, day)


CONCORDANCE_METRICS = {"hrv_rmssd", "resting_hr", "sleep_duration_minutes"}


@router.get("/metric-sources")
def metric_sources(
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(db_session),
) -> dict:
    """Device-by-metric matrix: for EVERY metric we store, which sources feed
    it, how many days each covers, which is canonical, and how fresh it is.

    Answers 'what does each device actually give me' — broader than the
    fixed-row coverage heatmap (includes body_battery, vo2_max, tss, etc.).
    """
    from ..canonical import CANONICAL_METRIC_SOURCE
    from ..models import DailyMetric

    end = _latest_date_any(db)
    start = end - timedelta(days=days)
    rows = db.execute(
        select(DailyMetric.metric, DailyMetric.source, DailyMetric.date, DailyMetric.value)
        .where(DailyMetric.date >= start, DailyMetric.date <= end)
    ).all()

    # metric -> source -> {dates set, last date}
    agg: dict[str, dict[str, dict]] = {}
    for metric, source, d, value in rows:
        if value is None or (metric in ZERO_IS_MISSING and value <= 0):
            continue
        s = agg.setdefault(metric, {}).setdefault(source, {"dates": set(), "last": d})
        s["dates"].add(d)
        if d > s["last"]:
            s["last"] = d

    out = []
    for metric, sources in sorted(agg.items()):
        canonical_src = CANONICAL_METRIC_SOURCE.get(metric)
        src_list = [
            {
                "source": src,
                "days": len(info["dates"]),
                "canonical": src == canonical_src,
                "last_date": info["last"].isoformat(),
                "days_behind": (end - info["last"]).days,
            }
            for src, info in sources.items()
        ]
        # Canonical first, then by coverage.
        src_list.sort(key=lambda s: (not s["canonical"], -s["days"]))
        out.append(
            {
                "metric": metric,
                "canonical_source": canonical_src,
                "total_days": len({d for info in sources.values() for d in info["dates"]}),
                "sources": src_list,
            }
        )
    return {"days": days, "window_days": (end - start).days + 1, "metrics": out}


@router.get("/concordance")
def concordance(
    metric: str = Query(default="hrv_rmssd"),
    days: int = Query(default=60, ge=7, le=365),
    db: Session = Depends(db_session),
) -> dict:
    """Whoop vs Eight Sleep, same metric, same nights.

    Quantifies the instrument offset so fallback values can be read honestly
    (the pod tends to read HRV higher than the strap), and makes one-off
    divergent nights (sensor moved / partner in bed) visible as outliers.
    """
    from statistics import median

    from ..models import DailyMetric
    from ..stats import pearson

    if metric not in CONCORDANCE_METRICS:
        return {"error": f"metric must be one of {sorted(CONCORDANCE_METRICS)}"}
    end = _latest_date_any(db)
    start = end - timedelta(days=days)
    rows = db.execute(
        select(DailyMetric.date, DailyMetric.source, DailyMetric.value).where(
            DailyMetric.metric == metric,
            DailyMetric.source.in_(["whoop", "eight_sleep"]),
            DailyMetric.date >= start,
            DailyMetric.date <= end,
            DailyMetric.value > 0,
        )
    ).all()
    by_date: dict[str, dict] = {}
    for d, src, v in rows:
        by_date.setdefault(d.isoformat(), {"date": d.isoformat()})[src] = float(v)
    series = sorted(by_date.values(), key=lambda r: r["date"])

    pairs = [(r["whoop"], r["eight_sleep"]) for r in series if "whoop" in r and "eight_sleep" in r]
    diffs = [es - w for w, es in pairs]
    offset = round(median(diffs), 1) if diffs else None
    r = pearson([p[0] for p in pairs], [p[1] for p in pairs])
    return {
        "metric": metric,
        "days": days,
        "series": series,
        "n_whoop": sum(1 for r_ in series if "whoop" in r_),
        "n_eight_sleep": sum(1 for r_ in series if "eight_sleep" in r_),
        "n_overlap": len(pairs),
        "median_offset": offset,  # eight_sleep minus whoop on shared nights
        "r": round(r, 2) if r is not None else None,
    }


COVERAGE_METRICS = [
    "recovery_score",
    "hrv_rmssd",
    "resting_hr",
    "strain_score",
    "sleep_duration_minutes",
    "respiratory_rate",
    "spo2",
    "steps",
]


@router.get("/coverage")
def coverage(
    days: int = Query(default=60, ge=7, le=365),
    db: Session = Depends(db_session),
) -> dict:
    """Which source filled each (day, metric) cell — the data-coverage grid."""
    from ..models import DailyMetric

    end = _latest_date(db)
    start = end - timedelta(days=days)
    rows = db.execute(
        select(DailyMetric.date, DailyMetric.metric, DailyMetric.source, DailyMetric.is_canonical)
        .where(
            DailyMetric.metric.in_(COVERAGE_METRICS),
            DailyMetric.date >= start,
            DailyMetric.date <= end,
            # All coverage metrics are zero-impossible; a stored 0 is a
            # placeholder, and showing it as covered would hide the real gap.
            DailyMetric.value > 0,
        )
    ).all()

    # Best source per (date, metric): canonical wins, else whatever's there.
    best: dict[tuple[str, str], tuple[str, bool]] = {}
    for d, metric, src, canon in rows:
        key = (d.isoformat(), metric)
        cur = best.get(key)
        if cur is None or (canon and not cur[1]):
            best[key] = (src, bool(canon))

    dates = [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    grid = {
        date: {m: (best.get((date, m), (None, False))[0]) for m in COVERAGE_METRICS}
        for date in dates
    }
    # Show recovery as 'estimated' where there's no score but HRV+RHR exist.
    for date in dates:
        if grid[date]["recovery_score"] is None:
            day = _date.fromisoformat(date)
            if estimated_recovery(db, day) is not None:
                grid[date]["recovery_score"] = "estimated"
    return {"metrics": COVERAGE_METRICS, "dates": dates, "grid": grid}


# -- serializers ------------------------------------------------------------
def _latest_date_any(db: Session) -> _date:
    """Max date with any metric — the same anchor metric_series uses, so all
    padded trend axes line up across metrics."""
    from sqlalchemy import func

    from ..models import DailyMetric

    return db.scalar(select(func.max(DailyMetric.date))) or _date.today()


def _earliest_date_any(db: Session) -> _date | None:
    """Min date with any metric — clamps trend windows so charts don't render
    weeks of empty axis when the requested range predates all data."""
    from sqlalchemy import func

    from ..models import DailyMetric

    return db.scalar(select(func.min(DailyMetric.date)))


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
