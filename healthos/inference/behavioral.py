"""Auto-detection rules that write inferred events to ``daily_events``.

Each rule reads canonical metrics + rolling baselines and, when its conditions
hold, upserts a row with ``confidence='inferred'``. Rules are intentionally
conservative; ambiguous signals stay low-confidence until the user confirms.

Inference is fully suppressed until we have >= MIN_INFERENCE_DAYS of data so we
don't fabricate events against a thin baseline (spec "building baseline" state).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as _date
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import settings
from ..models import CalendarEvent, DailyEvent, Workout
from ..queries import (
    MIN_INFERENCE_DAYS,
    canonical_sleep,
    canonical_value,
    data_day_count,
    rolling_baseline,
)

log = logging.getLogger(__name__)

LATE_WORKOUT_HOUR = 19  # workouts ending after 19:00 local count as "late"


@dataclass
class InferredEvent:
    event_type: str
    value: float | None
    confidence: str
    notes: str
    source: str


def _upsert_event(session: Session, day: _date, ev: InferredEvent) -> None:
    """Idempotent per (date, event_type). Manual/confirmed events are never
    overwritten by an inferred one."""
    stmt = (
        pg_insert(DailyEvent)
        .values(
            date=day,
            event_type=ev.event_type,
            value=ev.value,
            confidence=ev.confidence,
            notes=ev.notes,
            source=ev.source,
        )
        .on_conflict_do_update(
            constraint="uq_event_date_type",
            set_={
                "value": ev.value,
                "confidence": ev.confidence,
                "notes": ev.notes,
                "source": ev.source,
            },
            where=DailyEvent.confidence == "inferred",
        )
    )
    session.execute(stmt)


# -- individual rules -------------------------------------------------------
def detect_alcohol(session: Session, day: _date) -> InferredEvent | None:
    """Alcohol leaves a fingerprint: elevated RHR, suppressed HRV, longer sleep
    latency the following night. Fires only if all hold and no recent sickness.
    """
    if _recent_sick(session, day, lookback=3):
        return None
    hrv = canonical_value(session, day, "hrv_rmssd")
    rhr = canonical_value(session, day, "resting_hr")
    latency = _sleep_latency_minutes(session, day)

    hrv_base = rolling_baseline(session, "hrv_rmssd", day)
    rhr_base = rolling_baseline(session, "resting_hr", day)
    latency_base = _latency_baseline(session, day)

    if None in (hrv, rhr, latency, hrv_base.mean, rhr_base.mean, latency_base):
        return None

    conditions = (
        latency > 1.5 * latency_base,
        rhr > 1.1 * rhr_base.mean,
        hrv < 0.85 * hrv_base.mean,
    )
    n_true = sum(conditions)
    # Calendar acts as a corroborating prior: an evening "alcohol" event the
    # night before lets us fire on 2/3 physiological signals instead of 3/3.
    corroborated = _evening_alcohol_event(session, day) is not None
    if not (all(conditions) or (corroborated and n_true >= 2)):
        return None

    notes = (
        f"HRV {hrv:.0f} vs base {hrv_base.mean:.0f}; "
        f"RHR {rhr:.0f} vs {rhr_base.mean:.0f}; "
        f"latency {latency:.0f}m vs {latency_base:.0f}m"
    )
    # Note the keyword/flag only — never the raw event title (MCP reads notes).
    if corroborated:
        notes += "; corroborated by an evening calendar event (alcohol)"
    return InferredEvent(
        event_type="alcohol_detected",
        value=None,
        confidence="inferred",
        notes=notes,
        source="inferred_whoop+calendar" if corroborated else "inferred_whoop",
    )


def detect_late_workout(session: Session, day: _date) -> InferredEvent | None:
    """Any workout (any source — Whoop records them too) ending after 19:00."""
    workouts = session.scalars(select(Workout).where(Workout.date == day)).all()
    for w in workouts:
        end = w.end_time
        if end is None:
            continue
        local_end = end.astimezone(settings.tz)
        if local_end.hour >= LATE_WORKOUT_HOUR:
            return InferredEvent(
                event_type="late_workout",
                value=None,
                confidence="inferred",
                notes=f"{w.sport_type or 'workout'} ended {local_end:%H:%M} local",
                source=f"inferred_{w.source}",
            )
    return None


def detect_sick(session: Session, day: _date) -> InferredEvent | None:
    """Multi-day HRV crash + elevated RHR => likely illness."""
    rhr = canonical_value(session, day, "resting_hr")
    rhr_base = rolling_baseline(session, "resting_hr", day)
    if rhr is None or rhr_base.mean is None:
        return None
    if rhr <= 1.15 * rhr_base.mean:
        return None

    # HRV must be depressed today AND yesterday (2+ consecutive days).
    for offset in (0, 1):
        d = day - timedelta(days=offset)
        hrv = canonical_value(session, d, "hrv_rmssd")
        hrv_base = rolling_baseline(session, "hrv_rmssd", d)
        if hrv is None or hrv_base.mean is None or hrv >= 0.7 * hrv_base.mean:
            return None

    return InferredEvent(
        event_type="sick",
        value=None,
        confidence="inferred",
        notes=f"RHR {rhr:.0f} vs base {rhr_base.mean:.0f}; HRV depressed 2+ days",
        source="inferred_whoop",
    )


def detect_sauna(session: Session, day: _date) -> InferredEvent | None:
    """Sauna leaves a thermal signature on Eight Sleep: skin temp elevated in
    the first ~60 min of sleep, then a faster-than-average drop.

    Requires 30+ nights of Eight Sleep baseline before firing, and stays
    low-confidence until the user confirms a few times.
    """
    sleep = canonical_or_eight_sleep(session, day)
    if sleep is None or not sleep.raw_json:
        return None
    temps = _skin_temp_series(sleep.raw_json)
    if len(temps) < 12:  # need a reasonable curve
        return None

    eight_nights = _eight_sleep_night_count(session, day)
    if eight_nights < 30:
        return None

    first_hour = temps[: min(len(temps), 12)]  # assume ~5-min samples => first hour
    rest = temps[12:]
    if not rest:
        return None
    early_peak = max(first_hour)
    early_mean = sum(first_hour) / len(first_hour)
    drop_rate = (early_peak - min(rest)) / max(len(rest), 1)

    baseline_drop = _avg_drop_rate(session, day)
    if baseline_drop is None:
        return None

    elevated = early_mean > _avg_early_skin_temp(session, day, default=early_mean) + 0.3
    faster_drop = drop_rate > 1.2 * baseline_drop
    if elevated and faster_drop:
        return InferredEvent(
            event_type="sauna",
            value=None,
            confidence="inferred",  # low confidence; user confirmation upgrades it
            notes=f"early skin-temp elevated (+{early_mean:.1f}C), fast post-peak drop",
            source="inferred_eight_sleep",
        )
    return None


def detect_calendar_heavy(session: Session, day: _date) -> InferredEvent | None:
    """A day packed with calendar events, as a daytime-stress proxy."""
    events = _calendar_events(session, day)
    n = len(events)
    if n >= settings.calendar_heavy_threshold:
        return InferredEvent(
            event_type="calendar_heavy_day",
            value=float(n),
            confidence="inferred",
            notes=f"{n} calendar events scheduled",
            source="inferred_calendar",
        )
    return None


def detect_high_stress(session: Session, day: _date) -> InferredEvent | None:
    """Daytime HRV suppression vs baseline (proxy: low recovery score)."""
    recovery = canonical_value(session, day, "recovery_score")
    if recovery is None:
        return None
    if recovery < 34:  # Whoop's red-recovery zone
        return InferredEvent(
            event_type="high_stress_day",
            value=recovery,
            confidence="inferred",
            notes=f"recovery score {recovery:.0f} (red zone)",
            source="inferred_whoop",
        )
    return None


# -- orchestration ----------------------------------------------------------
RULES = [
    detect_alcohol,
    detect_late_workout,
    detect_sick,
    detect_sauna,
    detect_high_stress,
    detect_calendar_heavy,
]


def run_inference_for_date(session: Session, day: _date) -> list[str]:
    """Run all rules for one day. Returns the list of event types written."""
    if data_day_count(session) < MIN_INFERENCE_DAYS:
        log.info("Skipping inference for %s: < %d days of data", day, MIN_INFERENCE_DAYS)
        return []
    written: list[str] = []
    for rule in RULES:
        try:
            event = rule(session, day)
        except Exception:  # noqa: BLE001 - one rule must not break the rest
            log.exception("Inference rule %s failed for %s", rule.__name__, day)
            continue
        if event is not None:
            _upsert_event(session, day, event)
            written.append(event.event_type)
    return written


# -- helpers ----------------------------------------------------------------
def _recent_sick(session: Session, day: _date, lookback: int) -> bool:
    rows = session.scalars(
        select(DailyEvent.id).where(
            DailyEvent.event_type == "sick",
            DailyEvent.date >= day - timedelta(days=lookback),
            DailyEvent.date <= day,
        )
    ).all()
    return bool(rows)


def _calendar_events(session: Session, day: _date) -> list[CalendarEvent]:
    return list(
        session.scalars(select(CalendarEvent).where(CalendarEvent.date == day)).all()
    )


def _evening_alcohol_event(session: Session, day: _date) -> CalendarEvent | None:
    """An evening, alcohol-tagged event the night before `day` (whose sleep it
    would have affected)."""
    for ev in _calendar_events(session, day - timedelta(days=1)):
        if ev.is_evening and ev.keywords and "alcohol" in ev.keywords:
            return ev
    return None


def _sleep_latency_minutes(session: Session, day: _date) -> float | None:
    sleep = canonical_sleep(session, day)
    if sleep is None or not sleep.raw_json:
        return None
    score = sleep.raw_json.get("score") or {}
    stage = score.get("stage_summary") or {}
    latency_ms = stage.get("sleep_latency_milli") or score.get("sleep_latency_milli")
    return latency_ms / 60000 if latency_ms else None


def _latency_baseline(session: Session, day: _date, window: int = 30) -> float | None:
    samples: list[float] = []
    for offset in range(1, window + 1):
        lat = _sleep_latency_minutes(session, day - timedelta(days=offset))
        if lat is not None:
            samples.append(lat)
    return sum(samples) / len(samples) if samples else None


def canonical_or_eight_sleep(session: Session, day: _date):
    """Eight Sleep session for the night (for environment-based inference)."""
    from ..models import SleepSession

    return session.scalars(
        select(SleepSession).where(
            SleepSession.date == day, SleepSession.source == "eight_sleep"
        )
    ).first()


def _skin_temp_series(raw: dict) -> list[float]:
    """Skin-temp curve from an Eight Sleep session payload.

    The pod nests series under ``timeseries`` as [timestamp, value] pairs;
    prefer actual skin temp, fall back to bed temp (correlated), and never
    substitute non-thermal series.
    """
    ts = raw.get("timeseries") or {}
    for key in ("tempSkinC", "tempBedC"):
        series = ts.get(key)
        if isinstance(series, list) and series:
            return [float(p[1]) for p in series if isinstance(p, (list, tuple)) and len(p) == 2]
    # Older/flat payload shapes: plain list of floats at the top level.
    for key in ("tempSkinC", "skinTemp", "skin_temp"):
        series = raw.get(key)
        if isinstance(series, list) and series:
            return [float(x) for x in series if isinstance(x, (int, float))]
    return []


def _eight_sleep_night_count(session: Session, before: _date) -> int:
    from sqlalchemy import func

    from ..models import SleepSession

    return int(
        session.scalar(
            select(func.count(SleepSession.id)).where(
                SleepSession.source == "eight_sleep", SleepSession.date < before
            )
        )
        or 0
    )


def _avg_drop_rate(session: Session, day: _date, window: int = 30) -> float | None:
    rates: list[float] = []
    for offset in range(1, window + 1):
        s = canonical_or_eight_sleep(session, day - timedelta(days=offset))
        if s and s.raw_json:
            temps = _skin_temp_series(s.raw_json)
            if len(temps) >= 12:
                first_hour, rest = temps[:12], temps[12:]
                if rest:
                    rates.append((max(first_hour) - min(rest)) / max(len(rest), 1))
    return sum(rates) / len(rates) if rates else None


def _avg_early_skin_temp(session: Session, day: _date, default: float, window: int = 30) -> float:
    vals: list[float] = []
    for offset in range(1, window + 1):
        s = canonical_or_eight_sleep(session, day - timedelta(days=offset))
        if s and s.raw_json:
            temps = _skin_temp_series(s.raw_json)
            if temps:
                vals.append(sum(temps[:12]) / len(temps[:12]))
    return sum(vals) / len(vals) if vals else default
