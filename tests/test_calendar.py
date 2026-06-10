"""Calendar ingest, tagging, inference corroboration, and MCP redaction."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from healthos.inference.behavioral import detect_alcohol, detect_calendar_heavy
from healthos.models import CalendarEvent, SleepSession
from healthos.sync.calendar import parse_feed, tag_keywords
from healthos.sync.persistence import (
    CalendarEventRecord,
    MetricPoint,
    upsert_calendar_events,
    upsert_metrics,
)

# Dinner at 8pm PDT (03:00Z next day) on 2026-05-28 + a recurring standup.
SAMPLE_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//EN
BEGIN:VEVENT
UID:dinner-1
SUMMARY:Drinks with Sarah
LOCATION:The Tavern
DTSTART:20260529T030000Z
DTEND:20260529T050000Z
END:VEVENT
BEGIN:VEVENT
UID:standup-1
SUMMARY:Daily Standup
DTSTART:20260525T160000Z
DTEND:20260525T161500Z
RRULE:FREQ=DAILY;COUNT=5
END:VEVENT
END:VCALENDAR"""


def test_tag_keywords():
    assert "alcohol" in tag_keywords("Dinner with friends", None)
    assert "travel" in tag_keywords("Flight home", "SFO Airport")
    assert "work" in tag_keywords("Sprint Planning", None)
    assert tag_keywords("Pick up groceries", None) == []  # unclassified -> none


def test_parse_feed_expands_and_tags():
    recs = parse_feed(SAMPLE_ICS, date(2026, 5, 25), date(2026, 5, 30))
    dinners = [r for r in recs if r.uid == "dinner-1"]
    standups = [r for r in recs if r.uid == "standup-1"]
    assert len(standups) == 5  # recurrence expanded
    assert len(dinners) == 1
    d = dinners[0]
    assert d.date == date(2026, 5, 28)
    assert d.is_evening is True
    assert d.keywords == ["alcohol"]
    assert d.title == "Drinks with Sarah"


def test_calendar_heavy_day(session):
    day = date(2026, 6, 1)
    upsert_calendar_events(
        session,
        [CalendarEventRecord(date=day, uid=f"e{i}", title=f"Meeting {i}") for i in range(6)],
    )
    session.commit()
    ev = detect_calendar_heavy(session, day)
    assert ev is not None
    assert ev.event_type == "calendar_heavy_day"
    assert ev.value == 6


def _seed_alcohol_scenario(session, start: date, n: int = 31):
    """Baseline so only 2/3 alcohol conditions trigger on the target day."""
    points = []
    for i in range(n):
        d = start + timedelta(days=i)
        points += [
            MetricPoint(d, "hrv_rmssd", 60.0, "ms", "whoop"),
            MetricPoint(d, "resting_hr", 50.0, "bpm", "whoop"),
        ]
        session.add(
            SleepSession(
                date=d,
                source="whoop",
                is_canonical=True,
                raw_json={"score": {"stage_summary": {"sleep_latency_milli": 15 * 60000}}},
            )
        )
    upsert_metrics(session, points)
    session.commit()


def test_alcohol_fires_on_2of3_when_calendar_corroborates(session):
    start = date(2026, 1, 1)
    _seed_alcohol_scenario(session, start)
    target = start + timedelta(days=30)
    # 2/3: HRV depressed + RHR elevated, but sleep latency normal.
    upsert_metrics(
        session,
        [
            MetricPoint(target, "hrv_rmssd", 45.0, "ms", "whoop"),  # < 0.85*60
            MetricPoint(target, "resting_hr", 60.0, "bpm", "whoop"),  # > 1.1*50
        ],
    )
    session.commit()

    # Without calendar context, 2/3 is not enough.
    assert detect_alcohol(session, target) is None

    # An evening alcohol event the night before tips it over.
    upsert_calendar_events(
        session,
        [
            CalendarEventRecord(
                date=target - timedelta(days=1),
                uid="dinner",
                title="Dinner",
                is_evening=True,
                keywords=["alcohol"],
                start_time=datetime(2026, 1, 31, 3, 0, tzinfo=timezone.utc),
            )
        ],
    )
    session.commit()

    ev = detect_alcohol(session, target)
    assert ev is not None
    assert ev.event_type == "alcohol_detected"
    assert "corroborated" in ev.notes
    assert "Dinner" not in ev.notes  # raw title never leaks into notes


def test_mcp_query_raw_redacts_titles(session):
    upsert_calendar_events(
        session,
        [CalendarEventRecord(date=date(2026, 6, 1), uid="x", title="Therapy", location="Clinic")],
    )
    session.commit()

    from healthos.mcp_server.server import query_raw

    out = query_raw("SELECT date, title, location, keywords FROM calendar_events")
    assert out["row_count"] == 1
    row = out["rows"][0]
    assert row["title"] == "[redacted]"
    assert row["location"] == "[redacted]"
    # Confirm the real title is nowhere in the payload.
    import json

    assert "Therapy" not in json.dumps(out)


def test_calendar_event_persists(session):
    upsert_calendar_events(
        session,
        [CalendarEventRecord(date=date(2026, 6, 1), uid="u1", title="X", keywords=["alcohol"])],
    )
    # Idempotent on (uid, start_time).
    upsert_calendar_events(
        session,
        [CalendarEventRecord(date=date(2026, 6, 1), uid="u1", title="X2", keywords=[])],
    )
    session.commit()
    rows = session.scalars(select(CalendarEvent).where(CalendarEvent.uid == "u1")).all()
    assert len(rows) == 1
    assert rows[0].title == "X2"
