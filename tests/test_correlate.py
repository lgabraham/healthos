"""Correlation lag semantics + journal-tag exposure correlations."""

from __future__ import annotations

from datetime import date, timedelta

from healthos.correlate import (
    correlate_event_to_metric_delta,
    correlate_tag_to_metric_delta,
    prebuilt_cards,
)
from healthos.models import DailyEvent, IntakeLog
from healthos.sync.persistence import MetricPoint, upsert_metrics

TODAY = date.today()


def _baseline(session, metric, n=40, value=50.0, source="eight_sleep"):
    """A flat baseline ending yesterday so deltas are well-defined."""
    pts = [
        MetricPoint(TODAY - timedelta(days=i), metric, value, "u", source)
        for i in range(1, n + 1)
    ]
    upsert_metrics(session, pts)
    session.commit()


def test_tag_correlation_pairs_the_next_morning(session):
    """A journal entry is dated the day consumed; its effect must pair with the
    NEXT morning's metric (lag 1)."""
    _baseline(session, "hrv_rmssd")
    consumed = TODAY - timedelta(days=3)
    # Log 'alcohol' on the consumed day; drop next-morning HRV well below baseline.
    session.add(IntakeLog(date=consumed, raw_text="wine", tags=["alcohol"]))
    upsert_metrics(session, [MetricPoint(consumed + timedelta(days=1), "hrv_rmssd", 30.0, "ms", "eight_sleep")])
    session.commit()

    c = correlate_tag_to_metric_delta(session, "alcohol", "hrv_rmssd", days=30, lag_days=1)
    assert not c.degenerate
    # The consumed day is a present point (x=1) and its paired y is a big negative delta.
    pt = next(p for p in c.points if p["date"] == consumed.isoformat())
    assert pt["x"] == 1.0
    assert pt["y"] < -10  # ~30 vs 50 baseline


def test_tag_correlation_empty_when_tag_never_logged(session):
    _baseline(session, "hrv_rmssd")
    c = correlate_tag_to_metric_delta(session, "nsaid", "hrv_rmssd", days=30, lag_days=1)
    assert c.degenerate
    assert "nsaid" in c.interpretation


def test_event_correlation_defaults_to_same_morning(session):
    """alcohol_detected is dated the morning the hit shows, so the default lag is
    0 — the event date's own metric is the one to compare, not the day after."""
    _baseline(session, "recovery_score", source="whoop")
    hit = TODAY - timedelta(days=2)
    session.add(DailyEvent(date=hit, event_type="alcohol_detected",
                           confidence="inferred", source="inferred_behavioral"))
    upsert_metrics(session, [MetricPoint(hit, "recovery_score", 20.0, "score", "whoop")])
    session.commit()

    c = correlate_event_to_metric_delta(session, "alcohol_detected", "recovery_score", days=30)
    assert c.lag_days == 0
    pt = next(p for p in c.points if p["date"] == hit.isoformat())
    assert pt["x"] == 1.0
    assert pt["y"] < -10  # recovery 20 vs 50 baseline, same morning


def test_dismissed_events_excluded_from_correlation(session):
    _baseline(session, "recovery_score", source="whoop")
    hit = TODAY - timedelta(days=2)
    session.add(DailyEvent(date=hit, event_type="alcohol_detected",
                           confidence="dismissed", source="inferred_behavioral"))
    upsert_metrics(session, [MetricPoint(hit, "recovery_score", 20.0, "score", "whoop")])
    session.commit()
    c = correlate_event_to_metric_delta(session, "alcohol_detected", "recovery_score", days=30)
    # The dismissed event isn't counted as present -> no 1-valued x.
    assert all(p["x"] == 0.0 for p in c.points)


def test_prebuilt_cards_group_behavior_and_intake(session):
    _baseline(session, "hrv_rmssd")
    _baseline(session, "recovery_score", source="whoop")
    # Journal two different tags in-window; only these should get intake cards.
    session.add(IntakeLog(date=TODAY - timedelta(days=2), raw_text="ibuprofen", tags=["nsaid"]))
    session.add(IntakeLog(date=TODAY - timedelta(days=4), raw_text="latte", tags=["caffeine", "dairy"]))
    session.commit()

    cards = prebuilt_cards(session, days=30)
    groups = {c["group"] for c in cards}
    assert groups == {"behavior", "intake"}

    intake_titles = " ".join(c["title"].lower() for c in cards if c["group"] == "intake")
    assert "nsaid" in intake_titles
    assert "caffeine" in intake_titles
    assert "dairy" in intake_titles
    # A tag never logged gets no card.
    assert "gluten" not in intake_titles

    # The late-workout behavior card carries the corrected next-night lag.
    lw = next(c for c in cards if "late workout" in c["title"].lower())
    assert lw["lag_days"] == 1
