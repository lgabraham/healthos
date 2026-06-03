"""Behavioral inference tests against seeded canonical data."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from healthos.inference.behavioral import run_inference_for_date
from healthos.models import DailyEvent, Workout
from healthos.sync.persistence import MetricPoint, upsert_metrics


def _seed_baseline(session, start: date, n: int, hrv: float, rhr: float, recovery: float = 70):
    points = []
    for i in range(n):
        d = start + timedelta(days=i)
        points += [
            MetricPoint(d, "hrv_rmssd", hrv, "ms", "whoop"),
            MetricPoint(d, "resting_hr", rhr, "bpm", "whoop"),
            MetricPoint(d, "recovery_score", recovery, "score", "whoop"),
        ]
    upsert_metrics(session, points)
    session.commit()


def test_inference_suppressed_below_min_days(session):
    start = date(2026, 1, 1)
    _seed_baseline(session, start, n=5, hrv=60, rhr=50)
    written = run_inference_for_date(session, start + timedelta(days=4))
    assert written == []  # < 14 days of data => suppressed


def test_sick_detection(session):
    start = date(2026, 1, 1)
    # 30 healthy days
    _seed_baseline(session, start, n=30, hrv=60, rhr=50)
    # Two consecutive depressed days at the end
    d1 = start + timedelta(days=30)
    d2 = start + timedelta(days=31)
    upsert_metrics(
        session,
        [
            MetricPoint(d1, "hrv_rmssd", 38.0, "ms", "whoop"),  # < 0.7 * 60 = 42
            MetricPoint(d1, "resting_hr", 60.0, "bpm", "whoop"),  # > 1.15 * 50 = 57.5
            MetricPoint(d2, "hrv_rmssd", 38.0, "ms", "whoop"),
            MetricPoint(d2, "resting_hr", 60.0, "bpm", "whoop"),
        ],
    )
    session.commit()

    written = run_inference_for_date(session, d2)
    assert "sick" in written
    event = session.scalars(
        select(DailyEvent).where(DailyEvent.event_type == "sick", DailyEvent.date == d2)
    ).first()
    assert event is not None
    assert event.confidence == "inferred"


def test_late_workout_detection(session):
    start = date(2026, 1, 1)
    _seed_baseline(session, start, n=20, hrv=60, rhr=50)
    target = start + timedelta(days=20)
    # Workout ending 20:30 local (= 04:30 UTC next day for America/Los_Angeles).
    session.add(
        Workout(
            date=target,
            source="garmin",
            sport_type="running",
            end_time=datetime(2026, 1, 22, 4, 30, tzinfo=timezone.utc),
        )
    )
    session.commit()
    written = run_inference_for_date(session, target)
    assert "late_workout" in written
