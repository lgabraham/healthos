"""Reusable read queries shared by inference, the REST API, and the MCP server.

Centralizing these keeps baseline math (rolling 30-day windows, sick-day
exclusion, canonical filtering) consistent everywhere instead of being
re-derived per call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from datetime import timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .canonical import FALLBACK_PRIORITY, source_rank
from .models import DailyEvent, DailyMetric, SleepSession, Workout


def _source_rank_expr():
    """SQL expression mirroring ``canonical.source_rank`` for ORDER BY."""
    return case(
        *[(DailyMetric.source == s, i) for i, s in enumerate(FALLBACK_PRIORITY)],
        else_=len(FALLBACK_PRIORITY),
    )

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

    rows = session.execute(
        select(DailyMetric.value, DailyMetric.source).where(
            DailyMetric.date == day, DailyMetric.metric == metric
        )
    ).all()
    if not rows:
        return Resolved(None, None, False)
    # Deterministic fallback: best-ranked source wins (not whichever synced last).
    value, src = min(rows, key=lambda r: source_rank(r[1]))
    return Resolved(float(value), src, True)


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


def estimated_recovery(session: Session, day: _date) -> float | None:
    """A Whoop-like recovery estimate (0-100) for days without a real score.

    Heuristic: recovery rises with HRV above your baseline and resting HR below
    it. Not Whoop's algorithm — a transparent stand-in so gap days aren't blank.
    Uses best-available HRV/RHR (so an Eight Sleep night counts) and needs a
    baseline to compare against.
    """
    hrv = best_available(session, day, "hrv_rmssd")
    rhr = best_available(session, day, "resting_hr")
    if hrv.value is None or rhr.value is None:
        return None
    hrv_base = rolling_baseline(session, "hrv_rmssd", day)
    rhr_base = rolling_baseline(session, "resting_hr", day)
    if not hrv_base.mean or not rhr_base.mean:
        return None
    hrv_ratio = hrv.value / hrv_base.mean  # >1 = better than baseline
    rhr_ratio = rhr_base.mean / rhr.value  # >1 = better (lower RHR)
    # Baseline maps to ~55; HRV weighted more heavily than RHR, like Whoop.
    score = 55 + 70 * (hrv_ratio - 1) + 35 * (rhr_ratio - 1)
    return round(max(1.0, min(99.0, score)), 1)


# (metric, label, day_offset, invert) — invert=True means "lower is better",
# so the sign flips to read as helping(+)/dragging(-) recovery.
ATTRIBUTION_DRIVERS = [
    ("hrv_rmssd", "HRV", 0, False),
    ("resting_hr", "Resting HR", 0, True),
    ("sleep_duration_minutes", "Sleep duration", 0, False),
    ("respiratory_rate", "Respiratory rate", 0, True),
    ("strain_score", "Yesterday's strain", 1, True),
    ("bed_temp", "Bed temp", 0, True),
]


def attribution(session: Session, day: _date) -> dict:
    """Decompose today's state into signed deviations from personal baselines.

    Not a causal model of Whoop's score — each driver is the metric's deviation
    from its own 30-day baseline, signed so positive = helping recovery. The
    headline names the largest mover in plain language.
    """
    drivers: list[dict] = []
    for metric, label, offset, invert in ATTRIBUTION_DRIVERS:
        target = day - timedelta(days=offset)
        resolved = best_available(session, target, metric)
        base = rolling_baseline(session, metric, target)
        if resolved.value is None or not base.mean:
            continue
        pct = (resolved.value / base.mean - 1.0) * 100.0
        if invert:
            pct = -pct
        drivers.append(
            {
                "key": metric,
                "label": label,
                "pct": round(pct, 1),
                "value": round(resolved.value, 1),
                "baseline": round(base.mean, 1),
                "baseline_n": base.n,
                "source": resolved.source,
                "is_fallback": resolved.is_fallback,
            }
        )
    drivers.sort(key=lambda d: abs(d["pct"]), reverse=True)

    headline = None
    if drivers and abs(drivers[0]["pct"]) >= 5:
        top = drivers[0]
        direction = "helping" if top["pct"] > 0 else "dragging"
        headline = (
            f"{top['label']} is today's biggest mover: {top['value']} vs your "
            f"baseline of {top['baseline']} ({direction} recovery"
            f"{', via ' + top['source'] if top['is_fallback'] else ''})."
        )
    elif drivers:
        headline = "Everything is close to baseline today — steady as she goes."

    events = session.scalars(
        select(DailyEvent).where(DailyEvent.date.in_([day, day - timedelta(days=1)]))
    ).all()
    event_notes = [
        f"{e.event_type.replace('_', ' ')} ({'yesterday' if e.date != day else 'today'})"
        for e in events
    ]
    return {"date": day.isoformat(), "drivers": drivers, "headline": headline,
            "events": event_notes}


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
    """Trailing ``days`` of a metric as (date, value) ascending.

    By default returns one value per date using the best-available source
    (canonical preferred, otherwise the most recent other source), so trends
    extend through the current day using all data — not just the canonical
    device. Pass ``canonical_only=True`` to restrict to the canonical source.
    """
    end = _today(session)
    start = end - timedelta(days=days)
    if canonical_only:
        stmt = (
            select(DailyMetric.date, DailyMetric.value)
            .where(
                DailyMetric.metric == metric,
                DailyMetric.date >= start,
                DailyMetric.date <= end,
                DailyMetric.is_canonical.is_(True),
            )
            .order_by(DailyMetric.date.asc())
        )
        return [(d, float(v)) for d, v in session.execute(stmt).all() if v is not None]

    # One row per date: canonical first, else newest other source.
    stmt = (
        select(DailyMetric.date, DailyMetric.value)
        .where(
            DailyMetric.metric == metric,
            DailyMetric.date >= start,
            DailyMetric.date <= end,
        )
        .order_by(
            DailyMetric.date.asc(),
            DailyMetric.is_canonical.desc(),
            _source_rank_expr().asc(),
            DailyMetric.created_at.desc(),
        )
        .distinct(DailyMetric.date)
    )
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
