"""Persistence + canonical-flagging tests."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select

from healthos.models import DailyMetric
from healthos.sync.persistence import MetricPoint, upsert_metrics


def test_canonical_flag_applied(session):
    points = [
        MetricPoint(date(2026, 6, 1), "hrv_rmssd", 60.0, "ms", "whoop"),
        MetricPoint(date(2026, 6, 1), "hrv_rmssd", 58.0, "ms", "garmin"),
    ]
    upsert_metrics(session, points)
    session.commit()

    rows = session.scalars(
        select(DailyMetric).where(DailyMetric.metric == "hrv_rmssd").order_by(DailyMetric.source)
    ).all()
    by_source = {r.source: r.is_canonical for r in rows}
    assert by_source["whoop"] is True  # whoop is canonical for HRV
    assert by_source["garmin"] is False


def test_upsert_is_idempotent(session):
    p = MetricPoint(date(2026, 6, 1), "steps", 8000.0, "steps", "garmin")
    upsert_metrics(session, [p])
    upsert_metrics(session, [MetricPoint(date(2026, 6, 1), "steps", 9000.0, "steps", "garmin")])
    session.commit()

    rows = session.scalars(select(DailyMetric).where(DailyMetric.metric == "steps")).all()
    assert len(rows) == 1
    assert float(rows[0].value) == 9000.0  # latest value wins
    assert rows[0].is_canonical is True  # garmin canonical for steps


def test_best_available_prefers_canonical_then_falls_back(session):
    from datetime import date
    from healthos.queries import best_available

    d = date(2026, 6, 1)
    # Only a non-canonical Eight Sleep HRV exists -> fallback.
    upsert_metrics(session, [MetricPoint(d, "hrv_rmssd", 48.0, "ms", "eight_sleep")])
    session.commit()
    r = best_available(session, d, "hrv_rmssd")
    assert r.value == 48.0 and r.source == "eight_sleep" and r.is_fallback is True

    # Add Whoop (canonical) -> it wins, not a fallback.
    upsert_metrics(session, [MetricPoint(d, "hrv_rmssd", 55.0, "ms", "whoop")])
    session.commit()
    r = best_available(session, d, "hrv_rmssd")
    assert r.value == 55.0 and r.source == "whoop" and r.is_fallback is False
