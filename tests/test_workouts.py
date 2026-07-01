"""Manual workout logging + 'last workout' selection."""

from __future__ import annotations

from datetime import date, datetime, timezone

from healthos.models import Workout
from healthos.queries import latest_workout


def _device(session, d, sport, hour_utc):
    session.add(Workout(date=d, source="garmin", sport_type=sport,
                        start_time=datetime(d.year, d.month, d.day, hour_utc, tzinfo=timezone.utc)))


def test_manual_workout_is_stamped_with_local_time(session, client):
    """A manually logged workout gets a sortable start_time (and end_time when a
    duration is given) — a timestamp-less row would be buried in 'last workout'."""
    r = client.post(
        "/api/workouts",
        json={"sport_type": "walk", "date": "2026-06-28", "duration_minutes": 40},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["start_time"] is not None
    assert body["start_time"].startswith("2026-06-28T12:00")  # noon local on that day
    assert body["end_time"].startswith("2026-06-28T12:40")    # start + duration


def test_last_workout_prefers_same_day_manual_over_device(session):
    """The reported bug: a same-day manual walk must win 'last workout' over a
    device workout that merely carries a clock time — even the legacy case where
    the manual row has no start_time at all."""
    day = date(2026, 7, 1)
    _device(session, day, "indoor_cardio", 7)
    session.add(Workout(date=day, source="manual", sport_type="walk"))  # legacy: no start_time
    session.commit()

    w = latest_workout(session, day)
    assert w.sport_type == "walk"


def test_last_workout_still_prefers_later_device_day(session):
    """The fix must not over-correct: a device workout on a later day still wins
    over an earlier manual walk."""
    session.add(Workout(date=date(2026, 6, 30), source="manual", sport_type="walk"))
    _device(session, date(2026, 7, 1), "indoor_cardio", 7)
    session.commit()

    w = latest_workout(session, date(2026, 7, 1))
    assert w.sport_type == "indoor_cardio"


def test_last_workout_orders_two_device_workouts_by_time(session):
    """No regression for the common all-device case: latest start_time wins."""
    day = date(2026, 7, 1)
    _device(session, day, "morning_run", 7)
    _device(session, day, "evening_ride", 18)
    session.commit()

    assert latest_workout(session, day).sport_type == "evening_ride"
