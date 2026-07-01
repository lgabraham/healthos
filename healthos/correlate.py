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

from .models import DailyEvent, DailyMetric, IntakeLog
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


def _presence_to_metric_delta(
    session: Session,
    presence_dates: set[_date],
    label_a: str,
    metric: str,
    days: int,
    lag_days: int,
    empty_msg: str,
) -> Correlation:
    """Core of the presence-vs-delta correlation shared by events and journal
    tags: x is 1/0 for whether ``label_a`` was present on day D, y is ``metric``'s
    deviation from its rolling baseline on day D+lag_days.

    NOTE on lag: a metric[D] is the value from the night that ended the morning of
    D. So the correct lag depends on when the presence marker is dated relative to
    the night it affects — see the callers, which set it explicitly.
    """
    end = _date.today()
    start = end - timedelta(days=days)
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
                present = 1.0 if day in presence_dates else 0.0
                xs.append(present)
                ys.append(delta)
                points.append({"date": day.isoformat(), "x": present, "y": round(delta, 2)})
        day += timedelta(days=1)

    r = pearson(xs, ys)
    n_present = sum(1 for x in xs if x == 1.0)
    degenerate = len(xs) > 0 and (n_present == 0 or n_present == len(xs))
    interpretation = empty_msg if degenerate else interpret_r(r, len(xs))
    return Correlation(
        metric_a=label_a,
        metric_b=f"{metric}_delta",
        r=r,
        n=len(xs),
        points=points,
        interpretation=interpretation,
        lag_days=lag_days,
        degenerate=degenerate,
    )


def correlate_event_to_metric_delta(
    session: Session, event_type: str, metric: str, days: int, lag_days: int = 0
) -> Correlation:
    """Relate an inferred/curated event's presence to a metric's baseline delta.

    Default lag is 0: events like ``alcohol_detected`` and ``sauna`` are dated the
    *morning the effect shows* (that morning's suppressed HRV/recovery is the same
    night the behavior touched), so the metric on the event's own date is the one
    to compare. Callers whose event is dated *before* the affected night (e.g.
    ``late_workout``, dated the workout's evening → affects the *next* night) pass
    lag_days=1.
    """
    end = _date.today()
    start = end - timedelta(days=days)
    event_dates = set(
        session.scalars(
            select(DailyEvent.date).where(
                DailyEvent.event_type == event_type,
                DailyEvent.date >= start,
                DailyEvent.date <= end,
                DailyEvent.confidence.is_distinct_from("dismissed"),
            )
        ).all()
    )
    nice = event_type.replace("_", " ")
    empty = (
        f"No {nice} events in this window, so there's nothing to correlate yet. "
        f"Sync sources, then run `healthos infer` to (re)detect events."
    )
    return _presence_to_metric_delta(session, event_dates, event_type, metric, days, lag_days, empty)


def _tag_dates(session: Session, tag: str, start: _date, end: _date) -> set[_date]:
    """Dates in [start, end] with a journal entry carrying ``tag`` (JSONB @>)."""
    rows = session.scalars(
        select(IntakeLog.date).where(
            IntakeLog.tags.contains([tag]),
            IntakeLog.date >= start,
            IntakeLog.date <= end,
        )
    ).all()
    return set(rows)


def correlate_tag_to_metric_delta(
    session: Session, tag: str, metric: str, days: int, lag_days: int = 1
) -> Correlation:
    """Relate a journal exposure tag (alcohol, nsaid, dairy, …) to a next-day
    biomarker delta. Journal entries are dated the day you consumed, so the effect
    lands on the following night's metric — lag_days defaults to 1."""
    end = _date.today()
    start = end - timedelta(days=days)
    tag_dates = _tag_dates(session, tag, start, end)
    nice = tag.replace("_", " ")
    empty = (
        f"No '{nice}' entries logged in this window — journal what you eat/take "
        f"(and tag it) to build this correlation."
    )
    return _presence_to_metric_delta(
        session, tag_dates, f"{tag} (journal)", metric, days, lag_days, empty
    )


# Behavioral-event cards. Lag is the TRUE lag given each event's dating (see
# correlate_event_to_metric_delta): alcohol/sauna are same-morning (0); a late
# workout affects the *next* night (1).
_BEHAVIOR_SPECS: list[tuple[str, str, str, int]] = [
    ("Alcohol → morning-after recovery", "alcohol_detected", "recovery_score", 0),
    ("Sauna → that night's HRV", "sauna", "hrv_rmssd", 0),
    ("Late workout → the next night's sleep", "late_workout", "sleep_duration_minutes", 1),
]

# Journal exposure cards: which biomarker each tag most plausibly moves, and the
# lag (1 = next morning). Any logged tag without an entry here falls back to HRV.
_INTAKE_SPECS: dict[str, tuple[str, int, str]] = {
    "alcohol": ("recovery_score", 1, "Alcohol (journal) → next-morning recovery"),
    "nsaid": ("hrv_rmssd", 1, "NSAID → next-morning HRV"),
    "caffeine": ("sleep_duration_minutes", 1, "Caffeine → that night's sleep"),
    "dairy": ("hrv_rmssd", 1, "Dairy → next-morning HRV"),
    "gluten": ("hrv_rmssd", 1, "Gluten → next-morning HRV"),
    "high_histamine": ("resting_hr", 1, "High-histamine food → next-morning resting HR"),
    "sugar": ("deep_sleep_minutes", 1, "Sugar → that night's deep sleep"),
    "spicy": ("sleep_duration_minutes", 1, "Spicy food → that night's sleep"),
    "magnesium": ("deep_sleep_minutes", 1, "Magnesium → that night's deep sleep"),
    "melatonin": ("sleep_duration_minutes", 1, "Melatonin → that night's sleep"),
}
_MAX_INTAKE_CARDS = 8


def _error_card(title: str, group: str, exc: Exception) -> dict:
    return {
        "title": title, "group": group, "metric_a": "", "metric_b": "",
        "lag_days": 0, "r": None, "n": 0, "points": [],
        "interpretation": f"Couldn't compute this card: {exc}",
    }


def _present_tag_counts(session: Session, start: _date, end: _date) -> dict[str, int]:
    from collections import Counter

    counts: Counter[str] = Counter()
    for tags in session.scalars(
        select(IntakeLog.tags).where(IntakeLog.date >= start, IntakeLog.date <= end)
    ).all():
        for t in tags or []:
            counts[t] += 1
    return dict(counts)


def prebuilt_intake_cards(session: Session, days: int = 90) -> list[dict]:
    """One card per exposure tag you've actually journaled in the window (most
    frequent first), so the view adapts to what you log instead of showing empty
    cards for tags you never use."""
    end = _date.today()
    start = end - timedelta(days=days)
    counts = _present_tag_counts(session, start, end)
    tags = sorted(counts, key=lambda t: counts[t], reverse=True)[:_MAX_INTAKE_CARDS]
    out: list[dict] = []
    for tag in tags:
        metric, lag, title = _INTAKE_SPECS.get(
            tag, ("hrv_rmssd", 1, f"{tag.replace('_', ' ').title()} → next-morning HRV")
        )
        try:
            out.append(
                {"title": title, "group": "intake",
                 **correlate_tag_to_metric_delta(session, tag, metric, days, lag).to_dict()}
            )
        except Exception as exc:  # noqa: BLE001 - one card must not break the view
            log.warning("Intake card failed (%s): %s", tag, exc)
            out.append(_error_card(title, "intake", exc))
    return out


def prebuilt_cards(session: Session, days: int = 90) -> list[dict]:
    """The Correlations view's standing set of cards: behavioral events first,
    then a card per journaled exposure tag. Each card is computed defensively so
    a single failure degrades to an error card instead of 500-ing the view.
    """
    out: list[dict] = []
    for title, event_type, metric, lag in _BEHAVIOR_SPECS:
        try:
            out.append(
                {"title": title, "group": "behavior",
                 **correlate_event_to_metric_delta(session, event_type, metric, days, lag).to_dict()}
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Correlation card failed (%s): %s", title, exc)
            out.append(_error_card(title, "behavior", exc))
    try:
        out.append(
            {"title": "Training load (TSS) → next-morning HRV", "group": "behavior",
             **correlate_metrics(session, "tss", "hrv_rmssd", days, 1).to_dict()}
        )
    except Exception as exc:  # noqa: BLE001
        out.append(_error_card("Training load (TSS) → next-morning HRV", "behavior", exc))

    out += prebuilt_intake_cards(session, days)
    return out
