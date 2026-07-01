"""Persistence + canonical-flagging tests."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from healthos.models import DailyEvent, DailyMetric, SleepSession
from healthos.sync.persistence import (
    EventRecord,
    MetricPoint,
    SleepRecord,
    upsert_events,
    upsert_metrics,
    upsert_sleep,
)


def test_canonical_flag_applied(session):
    points = [
        MetricPoint(date(2026, 6, 1), "hrv_rmssd", 60.0, "ms", "eight_sleep"),
        MetricPoint(date(2026, 6, 1), "hrv_rmssd", 58.0, "ms", "whoop"),
    ]
    upsert_metrics(session, points)
    session.commit()

    rows = session.scalars(
        select(DailyMetric).where(DailyMetric.metric == "hrv_rmssd").order_by(DailyMetric.source)
    ).all()
    by_source = {r.source: r.is_canonical for r in rows}
    assert by_source["eight_sleep"] is True  # the pod is canonical for HRV now
    assert by_source["whoop"] is False  # Whoop is the away-from-pod fallback


def test_upsert_events_confirms_inferred_but_not_manual(session):
    day = date(2026, 6, 1)
    # An inferred sauna guess and a manually-logged one on another day.
    session.add_all([
        DailyEvent(date=day, event_type="sauna", confidence="inferred", source="inferred_eight_sleep"),
        DailyEvent(date=date(2026, 6, 2), event_type="sauna", confidence="manual",
                   source="manual", notes="my note"),
    ])
    session.commit()

    upsert_events(session, [
        EventRecord(date=day, event_type="sauna", value=22, source="harvia"),
        EventRecord(date=date(2026, 6, 2), event_type="sauna", value=18, source="harvia"),
        EventRecord(date=date(2026, 6, 3), event_type="sauna", value=30, source="harvia"),
    ])
    session.commit()

    rows = {r.date: r for r in session.scalars(select(DailyEvent)).all()}
    # Inferred -> upgraded to a confirmed Harvia event.
    assert rows[day].confidence == "confirmed"
    assert rows[day].source == "harvia"
    assert float(rows[day].value) == 22
    # Manual stays the user's record of truth, but the duration refreshes.
    assert rows[date(2026, 6, 2)].source == "manual"
    assert rows[date(2026, 6, 2)].notes == "my note"
    assert float(rows[date(2026, 6, 2)].value) == 18
    # Brand-new day inserted.
    assert rows[date(2026, 6, 3)].confidence == "confirmed"


def test_upsert_sleep_dedupes_same_date_source_in_one_batch(session):
    """Two records for the same (date, source) in a single call must collapse to
    one row — the autoflush-off session can't see the first mid-batch, so without
    the in-batch dedupe it would insert a permanent duplicate."""
    d = date(2026, 6, 1)
    upsert_sleep(session, [
        SleepRecord(date=d, source="eight_sleep", total_minutes=40),   # nap-ish
        SleepRecord(date=d, source="eight_sleep", total_minutes=430),  # the night
    ])
    session.commit()
    rows = session.scalars(
        select(SleepSession).where(SleepSession.source == "eight_sleep")
    ).all()
    assert len(rows) == 1
    assert rows[0].total_minutes == 430  # last record wins


def test_upsert_is_idempotent(session):
    p = MetricPoint(date(2026, 6, 1), "steps", 8000.0, "steps", "apple_health")
    upsert_metrics(session, [p])
    upsert_metrics(
        session, [MetricPoint(date(2026, 6, 1), "steps", 9000.0, "steps", "apple_health")]
    )
    session.commit()

    rows = session.scalars(select(DailyMetric).where(DailyMetric.metric == "steps")).all()
    assert len(rows) == 1
    assert float(rows[0].value) == 9000.0  # latest value wins
    assert rows[0].is_canonical is True  # apple_health canonical for steps


def test_best_available_prefers_canonical_then_falls_back(session):
    from datetime import date
    from healthos.queries import best_available

    d = date(2026, 6, 1)
    # Only a non-canonical Whoop HRV exists (away-from-pod night) -> fallback.
    upsert_metrics(session, [MetricPoint(d, "hrv_rmssd", 48.0, "ms", "whoop")])
    session.commit()
    r = best_available(session, d, "hrv_rmssd")
    assert r.value == 48.0 and r.source == "whoop" and r.is_fallback is True

    # Add Eight Sleep (canonical) -> it wins, not a fallback.
    upsert_metrics(session, [MetricPoint(d, "hrv_rmssd", 55.0, "ms", "eight_sleep")])
    session.commit()
    r = best_available(session, d, "hrv_rmssd")
    assert r.value == 55.0 and r.source == "eight_sleep" and r.is_fallback is False
