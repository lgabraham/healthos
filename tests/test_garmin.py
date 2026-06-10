"""Garmin normalizer tests — pure functions over sample payloads (no network)."""
from __future__ import annotations

from datetime import date

from healthos.canonical import is_canonical_metric
from healthos.sync.garmin import (
    normalize_daily,
    normalize_hrv,
    normalize_vo2max_range,
)

DAY = date(2026, 6, 1)


def _by_metric(points):
    return {p.metric: p for p in points}


def test_daily_extracts_steps_rhr_battery_stress():
    summary = {
        "totalSteps": 8421,
        "restingHeartRate": 51,
        "bodyBatteryMostRecentValue": 64,
        "averageStressLevel": 33,
    }
    m = _by_metric(normalize_daily(DAY, summary))
    assert m["steps"].value == 8421
    assert m["resting_hr"].value == 51
    assert m["resting_hr"].source == "garmin"
    assert m["body_battery"].value == 64
    assert m["stress_avg"].value == 33


def test_daily_skips_sentinel_and_missing_values():
    # Garmin sends -1/-2 for "no reading"; a 0 RHR is not a real heart rate.
    summary = {"totalSteps": 100, "restingHeartRate": 0, "averageStressLevel": -1}
    m = _by_metric(normalize_daily(DAY, summary))
    assert "steps" in m
    assert "resting_hr" not in m
    assert "stress_avg" not in m


def test_daily_empty():
    assert normalize_daily(DAY, None) == []
    assert normalize_daily(DAY, {}) == []


def test_hrv_uses_last_night_avg():
    data = {"hrvSummary": {"lastNightAvg": 38, "weeklyAvg": 41, "status": "BALANCED"}}
    points = normalize_hrv(DAY, data)
    assert len(points) == 1
    assert points[0].metric == "hrv_rmssd"
    assert points[0].value == 38
    assert points[0].unit == "ms"


def test_hrv_missing():
    assert normalize_hrv(DAY, None) == []
    assert normalize_hrv(DAY, {"hrvSummary": {}}) == []
    assert normalize_hrv(DAY, {"hrvSummary": {"lastNightAvg": None}}) == []


def test_garmin_hrv_and_rhr_are_non_canonical_fallbacks():
    # Whoop owns HRV/RHR, so Garmin readings must land as fallback (fill gaps).
    assert is_canonical_metric("hrv_rmssd", "garmin") is False
    assert is_canonical_metric("resting_hr", "garmin") is False
    # But Garmin-only context metrics are canonical to Garmin.
    assert is_canonical_metric("body_battery", "garmin") is True
    assert is_canonical_metric("stress_avg", "garmin") is True


def test_vo2max_range_maps_by_calendar_date():
    entries = [
        {"generic": {"calendarDate": "2026-05-30", "vo2MaxPreciseValue": 48.6}},
        {"generic": {"calendarDate": "2026-05-31", "vo2MaxValue": 49}},
        {"generic": {"calendarDate": "2026-06-01"}},  # no value -> skipped
    ]
    points = normalize_vo2max_range(entries)
    by_date = {p.date: p.value for p in points}
    assert by_date[date(2026, 5, 30)] == 48.6
    assert by_date[date(2026, 5, 31)] == 49
    assert date(2026, 6, 1) not in by_date


def test_vo2max_range_empty():
    assert normalize_vo2max_range([]) == []


def test_fallback_is_deterministic_across_sources(session):
    """When both Eight Sleep and Garmin have a non-canonical HRV for a day,
    best_available must return the same (priority-ranked) source every time,
    not whichever was inserted most recently."""
    from datetime import date as _date

    from healthos.models import DailyMetric
    from healthos.queries import best_available

    day = _date(2026, 6, 1)
    # Insert Garmin first, Eight Sleep second (so created_at would prefer ES).
    session.add(DailyMetric(date=day, metric="hrv_rmssd", value=40, unit="ms",
                            source="garmin", is_canonical=False))
    session.add(DailyMetric(date=day, metric="hrv_rmssd", value=44, unit="ms",
                            source="eight_sleep", is_canonical=False))
    session.commit()
    r = best_available(session, day, "hrv_rmssd")
    # Eight Sleep outranks Garmin for overnight HRV per FALLBACK_PRIORITY.
    assert r.source == "eight_sleep"
    assert r.value == 44
    assert r.is_fallback is True
