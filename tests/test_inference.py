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


def test_skin_temp_series_reads_nested_pairs():
    """The pod nests series under timeseries as [ts, value] pairs; the helper
    must read skin temp (or bed temp), never toss-and-turn counts."""
    from healthos.inference.behavioral import _skin_temp_series

    raw = {
        "timeseries": {
            "tempSkinC": [["t1", 34.1], ["t2", 35.0], ["t3", 33.8]],
            "tnt": [["t1", 2], ["t2", 1]],
        }
    }
    assert _skin_temp_series(raw) == [34.1, 35.0, 33.8]
    # Bed temp fallback when skin temp absent.
    raw2 = {"timeseries": {"tempBedC": [["t1", 27.0]], "tnt": [["t1", 9]]}}
    assert _skin_temp_series(raw2) == [27.0]
    # tnt alone must NOT be mistaken for temperature.
    assert _skin_temp_series({"timeseries": {"tnt": [["t1", 9]]}}) == []


def test_late_workout_any_source(session):
    from datetime import datetime, timedelta as td

    from healthos.config import settings
    from healthos.inference.behavioral import detect_late_workout
    from healthos.models import Workout

    d = date(2026, 6, 8)
    end = datetime(2026, 6, 8, 20, 30, tzinfo=settings.tz)
    session.add(Workout(date=d, source="whoop", sport_type="run",
                        start_time=end - td(hours=1), end_time=end))
    session.commit()
    ev = detect_late_workout(session, d)
    assert ev is not None
    assert ev.source == "inferred_whoop"
