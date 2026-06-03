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
