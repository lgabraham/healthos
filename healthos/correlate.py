"""Correlation helpers shared by the API's Correlations view and the MCP server.

Two flavours:
  * metric-vs-metric, with an optional day lag (for "next-day" effects).
  * event-vs-metric-delta, e.g. "alcohol nights -> next-day recovery".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as _date
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import DailyEvent, DailyMetric
from .queries import rolling_baseline
from .stats import interpret_r, pearson

log = logging.getLogger(__name__)


@dataclass
class Correlation:
    metric_a: str
    metric_b: str
    r: float | None
    n: int
    points: list[dict]
    interpretation: str
    lag_days: int = 0
    degenerate: bool = False  # zero variance in x — a scatter would be a lie

    def to_dict(self) -> dict:
        return {
            "metric_a": self.metric_a,
            "metric_b": self.metric_b,
            "lag_days": self.lag_days,
            "r": round(self.r, 3) if self.r is not None else None,
            "n": self.n,
            "points": self.points,
            "interpretation": self.interpretation,
            "degenerate": self.degenerate,
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
    n_events = sum(1 for x in xs if x == 1.0)
    degenerate = len(xs) > 0 and (n_events == 0 or n_events == len(xs))
    if degenerate:
        nice = event_type.replace("_", " ")
        interpretation = (
            f"No {nice} events inferred in this window, so there is nothing to "
            f"correlate yet. Sync sources, then run `healthos infer` to (re)detect events."
        )
    else:
        interpretation = interpret_r(r, len(xs))
    return Correlation(
        metric_a=event_type,
        metric_b=f"{metric}_delta",
        r=r,
        n=len(xs),
        points=points,
        interpretation=interpretation,
        lag_days=lag_days,
        degenerate=degenerate,
    )


def prebuilt_cards(session: Session, days: int = 90) -> list[dict]:
    """The Correlations view's standing set of cards.

    Each card is computed defensively so a single failure (or an unexpected data
    shape) degrades to an error card instead of 500-ing the whole view.
    """
    specs = [
        (
            "Sauna nights -> next-day HRV delta",
            lambda: correlate_event_to_metric_delta(session, "sauna", "hrv_rmssd", days, 1),
        ),
        (
            "Alcohol events -> next-day recovery score",
            lambda: correlate_event_to_metric_delta(
                session, "alcohol_detected", "recovery_score", days, 1
            ),
        ),
        (
            "Late workout -> sleep duration",
            lambda: correlate_event_to_metric_delta(
                session, "late_workout", "sleep_duration_minutes", days, 0
            ),
        ),
        (
            "Training load (TSS) -> next-day HRV",
            lambda: correlate_metrics(session, "tss", "hrv_rmssd", days, 1),
        ),
    ]
    out: list[dict] = []
    for title, fn in specs:
        try:
            out.append({"title": title, **fn().to_dict()})
        except Exception as exc:  # noqa: BLE001 - never let one card break the view
            log.warning("Correlation card failed (%s): %s", title, exc)
            out.append(
                {
                    "title": title,
                    "metric_a": "",
                    "metric_b": "",
                    "lag_days": 0,
                    "r": None,
                    "n": 0,
                    "points": [],
                    "interpretation": f"Couldn't compute this card: {exc}",
                }
            )
    return out
