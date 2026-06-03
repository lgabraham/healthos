"""Correlation helpers shared by the API's Correlations view and the MCP server.

Two flavours:
  * metric-vs-metric, with an optional day lag (for "next-day" effects).
  * event-vs-metric-delta, e.g. "alcohol nights -> next-day recovery".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DailyEvent, DailyMetric
from .queries import rolling_baseline
from .stats import interpret_r, pearson


@dataclass
class Correlation:
    metric_a: str
    metric_b: str
    r: float | None
    n: int
    points: list[dict]
    interpretation: str
    lag_days: int = 0

    def to_dict(self) -> dict:
        return {
            "metric_a": self.metric_a,
            "metric_b": self.metric_b,
            "lag_days": self.lag_days,
            "r": round(self.r, 3) if self.r is not None else None,
            "n": self.n,
            "points": self.points,
            "interpretation": self.interpretation,
        }


def _canonical_map(session: Session, metric: str, start: _date, end: _date) -> dict[_date, float]:
    rows = session.execute(
        select(DailyMetric.date, DailyMetric.value).where(
            DailyMetric.metric == metric,
            DailyMetric.is_canonical.is_(True),
            DailyMetric.date >= start,
            DailyMetric.date <= end,
        )
    ).all()
    return {d: float(v) for d, v in rows if v is not None}


def correlate_metrics(
    session: Session, metric_a: str, metric_b: str, days: int, lag_days: int = 0
) -> Correlation:
    """Correlate two metrics, optionally shifting metric_b forward by lag_days
    (lag=1 pairs metric_a[d] with metric_b[d+1])."""
    end = _date.today()
    start = end - timedelta(days=days + lag_days)
    a = _canonical_map(session, metric_a, start, end)
    b = _canonical_map(session, metric_b, start, end)

    xs: list[float] = []
    ys: list[float] = []
    points: list[dict] = []
    for d, av in sorted(a.items()):
        bv = b.get(d + timedelta(days=lag_days))
        if bv is None:
            continue
        xs.append(av)
        ys.append(bv)
        points.append({"date": d.isoformat(), "x": av, "y": bv})

    r = pearson(xs, ys)
    return Correlation(
        metric_a=metric_a,
        metric_b=metric_b,
        r=r,
        n=len(xs),
        points=points,
        interpretation=interpret_r(r, len(xs)),
        lag_days=lag_days,
    )


def correlate_event_to_metric_delta(
    session: Session, event_type: str, metric: str, days: int, lag_days: int = 1
) -> Correlation:
    """Relate an event's presence to the next-day deviation of a metric from its
    rolling baseline (e.g. alcohol -> next-day recovery delta). x is 1/0 for
    event presence, y is the metric's delta from baseline lag_days later."""
    end = _date.today()
    start = end - timedelta(days=days)
    event_dates = set(
        session.scalars(
            select(DailyEvent.date).where(
                DailyEvent.event_type == event_type,
                DailyEvent.date >= start,
                DailyEvent.date <= end,
            )
        ).all()
    )

    xs: list[float] = []
    ys: list[float] = []
    points: list[dict] = []
    day = start
    while day <= end:
        target = day + timedelta(days=lag_days)
        val = session.scalar(
            select(DailyMetric.value).where(
                DailyMetric.metric == metric,
                DailyMetric.is_canonical.is_(True),
                DailyMetric.date == target,
            )
        )
        if val is not None:
            base = rolling_baseline(session, metric, target)
            if base.mean is not None:
                delta = float(val) - base.mean
                present = 1.0 if day in event_dates else 0.0
                xs.append(present)
                ys.append(delta)
                points.append(
                    {"date": day.isoformat(), "x": present, "y": round(delta, 2)}
                )
        day += timedelta(days=1)

    r = pearson(xs, ys)
    return Correlation(
        metric_a=event_type,
        metric_b=f"{metric}_delta",
        r=r,
        n=len(xs),
        points=points,
        interpretation=interpret_r(r, len(xs)),
        lag_days=lag_days,
    )


def prebuilt_cards(session: Session, days: int = 90) -> list[dict]:
    """The Correlations view's standing set of cards."""
    cards = [
        (
            "Sauna nights -> next-day HRV delta",
            correlate_event_to_metric_delta(session, "sauna", "hrv_rmssd", days, lag_days=1),
        ),
        (
            "Alcohol events -> next-day recovery score",
            correlate_event_to_metric_delta(
                session, "alcohol_detected", "recovery_score", days, lag_days=1
            ),
        ),
        (
            "Late workout -> sleep onset latency",
            correlate_event_to_metric_delta(
                session, "late_workout", "sleep_duration_minutes", days, lag_days=0
            ),
        ),
        (
            "Training load (TSS) -> next-day HRV",
            correlate_metrics(session, "tss", "hrv_rmssd", days, lag_days=1),
        ),
    ]
    return [{"title": title, **corr.to_dict()} for title, corr in cards]
