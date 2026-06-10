"""Reusable read queries shared by inference, the REST API, and the MCP server.

Centralizing these keeps baseline math (rolling 30-day windows, sick-day
exclusion, canonical filtering) consistent everywhere instead of being
re-derived per call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import DailyEvent, DailyMetric, SleepSession, Workout

BASELINE_WINDOW_DAYS = 30
MIN_BASELINE_DAYS = 30  # below this we flag baselines as not-yet-trustworthy
MIN_INFERENCE_DAYS = 14  # below this we suppress inference entirely (spec: "building baseline")


@dataclass
class Baseline:
    metric: str
    mean: float | None
    n: int

    @property
    def trustworthy(self) -> bool:
        return self.n >= MIN_BASELINE_DAYS


def canonical_value(session: Session, day: _date, metric: str) -> float | None:
    """The canonical reading of ``metric`` on ``day``, if present."""
    stmt = (
        select(DailyMetric.value)
        .where(
            DailyMetric.date == day,
            DailyMetric.metric == metric,
            DailyMetric.is_canonical.is_(True),
        )
        .limit(1)
    )
    val = session.scalar(stmt)
    return float(val) if val is not None else None


@dataclass
class Resolved:
    value: float | None
    source: str | None
    is_fallback: bool


def best_available(session: Session, day: _date, metric: str) -> Resolved:
    """Canonical reading if present, else fall back to any other source for the
    day — carrying provenance so the UI can label a fallback (e.g. HRV via
    Eight Sleep when Whoop has a gap)."""
    canon = session.execute(
        select(DailyMetric.value, DailyMetric.source)
        .where(
            DailyMetric.date == day,
            DailyMetric.metric == metric,
            DailyMetric.is_canonical.is_(True),
        )
        .limit(1)
    ).first()
    if canon is not None:
        return Resolved(float(canon[0]), canon[1], False)

    other = session.execute(
        select(DailyMetric.value, DailyMetric.source)
        .where(DailyMetric.date == day, DailyMetric.metric == metric)
        .order_by(DailyMetric.created_at.desc())
        .limit(1)
    ).first()
    if other is not None:
        return Resolved(float(other[0]), other[1], True)
    return Resolved(None, None, False)


def sick_dates(session: Session, end: _date, window_days: int = BASELINE_WINDOW_DAYS) -> set[_date]:
    """Dates flagged ``sick`` within the window, to exclude from baselines."""
    start = end - timedelta(days=window_days)
    rows = session.scalars(
        select(DailyEvent.date).where(
            DailyEvent.event_type == "sick",
            DailyEvent.date >= start,
            DailyEvent.date <= end,
        )
    ).all()
    return set(rows)


def rolling_baseline(
    session: Session,
    metric: str,
    end: _date,
    window_days: int = BASELINE_WINDOW_DAYS,
    exclude_sick: bool = True,
) -> Baseline:
    """Mean of canonical ``metric`` over the trailing window ending the day
    before ``end`` (exclusive of the target day so "today" doesn't bias its own
    baseline). Sick days are excluded by default per spec.
    """
    start = end - timedelta(days=window_days)
    stmt = select(DailyMetric.date, DailyMetric.value).where(
        DailyMetric.metric == metric,
        DailyMetric.is_canonical.is_(True),
        DailyMetric.date >= start,
        DailyMetric.date < end,
    )
    rows = session.execute(stmt).all()
    excluded = sick_dates(session, end, window_days) if exclude_sick else set()
    values = [float(v) for d, v in rows if d not in excluded and v is not None]
    if not values:
        return Baseline(metric=metric, mean=None, n=0)
    return Baseline(metric=metric, mean=sum(values) / len(values), n=len(values))


def data_day_count(session: Session) -> int:
    """Distinct number of days we have any canonical metric for."""
    n = session.scalar(
        select(func.count(func.distinct(DailyMetric.date))).where(
            DailyMetric.is_canonical.is_(True)
        )
    )
    return int(n or 0)


def metric_series(
    session: Session, metric: str, days: int, canonical_only: bool = True
) -> list[tuple[_date, float]]:
    """Trailing ``days`` of a metric as (date, value) ascending."""
    end = _today(session)
    start = end - timedelta(days=days)
    stmt = (
        select(DailyMetric.date, DailyMetric.value)
        .where(
            DailyMetric.metric == metric,
            DailyMetric.date >= start,
            DailyMetric.date <= end,
        )
        .order_by(DailyMetric.date.asc())
    )
    if canonical_only:
        stmt = stmt.where(DailyMetric.is_canonical.is_(True))
    return [(d, float(v)) for d, v in session.execute(stmt).all() if v is not None]


def canonical_sleep(session: Session, day: _date) -> SleepSession | None:
    return session.scalars(
        select(SleepSession).where(
            SleepSession.date == day, SleepSession.is_canonical.is_(True)
        )
    ).first()


def best_available_sleep(session: Session, day: _date) -> SleepSession | None:
    """Canonical (Whoop) sleep if present, else the most recent session from any
    source for the day — so the pod's sleep shows when Whoop has a gap."""
    canon = canonical_sleep(session, day)
    if canon is not None:
        return canon
    return session.scalars(
        select(SleepSession)
        .where(SleepSession.date == day)
        .order_by(SleepSession.created_at.desc())
    ).first()


def latest_workout(session: Session, on_or_before: _date) -> Workout | None:
    return session.scalars(
        select(Workout)
        .where(Workout.date <= on_or_before)
        .order_by(Workout.start_time.desc().nullslast(), Workout.date.desc())
    ).first()


def _today(session: Session) -> _date:
    """Most recent date we have data for (so trends aren't empty before sync)."""
    latest = session.scalar(select(func.max(DailyMetric.date)))
    return latest or _date.today()
