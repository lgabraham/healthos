"""Regression tests for the 2026-06-10 QA review fixes (P0 data integrity)."""
from __future__ import annotations

from datetime import date, timedelta

from healthos.models import DailyMetric
from healthos.queries import attribution, best_available, rolling_baseline
from healthos.sync.whoop import normalize_cycles, normalize_recovery

DAY = date(2026, 6, 9)


def test_zero_strain_reads_as_missing(session):
    """A stored 0.0 strain (unsynced strap placeholder) must resolve to None,
    not flow into cards/attribution as a real reading."""
    session.add(DailyMetric(date=DAY, metric="strain_score", value=0, unit="score",
                            source="whoop", is_canonical=True))
    session.commit()
    assert best_available(session, DAY, "strain_score").value is None


def test_zero_excluded_from_baseline(session):
    for i in range(10):
        session.add(DailyMetric(date=DAY - timedelta(days=i + 1), metric="strain_score",
                                value=10.0 if i < 5 else 0, unit="score",
                                source="whoop", is_canonical=True))
    session.commit()
    base = rolling_baseline(session, "strain_score", DAY)
    assert base.n == 5  # the five zeros don't count
    assert base.mean == 10.0


def test_attribution_skips_fake_zero_and_reports_reason(session):
    # Only a zero strain exists -> no drivers, and the reason names the cause.
    session.add(DailyMetric(date=DAY - timedelta(days=1), metric="strain_score", value=0,
                            unit="score", source="whoop", is_canonical=True))
    session.commit()
    a = attribution(session, DAY)
    assert a["drivers"] == []
    assert "No metrics recorded" in a["reason"]


def test_attribution_separates_deviation_and_impact(session):
    # Resting HR 10% BELOW baseline: deviation negative, impact positive.
    for i in range(20):
        session.add(DailyMetric(date=DAY - timedelta(days=i + 1), metric="resting_hr",
                                value=50, unit="bpm", source="whoop", is_canonical=True))
    session.add(DailyMetric(date=DAY, metric="resting_hr", value=45, unit="bpm",
                            source="whoop", is_canonical=True))
    session.commit()
    a = attribution(session, DAY)
    rhr = next(d for d in a["drivers"] if d["key"] == "resting_hr")
    assert rhr["deviation_pct"] == -10.0  # below your normal
    assert rhr["pct"] == 10.0  # which helps recovery
    assert rhr["neutral"] is False


def test_strain_driver_is_neutral_and_not_headlined(session):
    for i in range(20):
        session.add(DailyMetric(date=DAY - timedelta(days=i + 2), metric="strain_score",
                                value=10, unit="score", source="whoop", is_canonical=True))
    # Yesterday's strain way below baseline; no other drivers.
    session.add(DailyMetric(date=DAY - timedelta(days=1), metric="strain_score", value=2,
                            unit="score", source="whoop", is_canonical=True))
    session.commit()
    a = attribution(session, DAY)
    strain = next(d for d in a["drivers"] if d["key"] == "strain_score")
    assert strain["neutral"] is True
    # A rest day must not produce a confident directional headline.
    assert a["headline"] == "Everything is close to baseline today — steady as she goes."


def test_whoop_unscored_records_are_skipped():
    recs = [
        {"created_at": "2026-06-08T08:00:00Z", "score_state": "PENDING_SCORE",
         "score": {"hrv_rmssd_milli": 0, "resting_heart_rate": 0, "recovery_score": 0}},
        {"created_at": "2026-06-07T08:00:00Z", "score_state": "SCORED",
         "score": {"hrv_rmssd_milli": 42, "resting_heart_rate": 50, "recovery_score": 70}},
    ]
    points = normalize_recovery(recs)
    days = {p.date for p in points}
    assert date(2026, 6, 7) in days or len(days) == 1  # tz-shifted but single day
    assert all(p.value > 0 for p in points)

    cycles = [
        {"start": "2026-06-08T07:00:00Z", "score_state": "UNSCORABLE", "score": {"strain": 0}},
        {"start": "2026-06-07T07:00:00Z", "score_state": "SCORED", "score": {"strain": 8.2}},
    ]
    strain = normalize_cycles(cycles)
    assert len(strain) == 1
    assert strain[0].value == 8.2


def test_status_reports_per_source_freshness(session, client):
    session.add(DailyMetric(date=DAY, metric="hrv_rmssd", value=40, unit="ms",
                            source="eight_sleep", is_canonical=False))
    session.add(DailyMetric(date=DAY - timedelta(days=10), metric="hrv_rmssd", value=42,
                            unit="ms", source="whoop", is_canonical=True))
    session.commit()
    body = client.get("/api/status").json()
    assert body["sources"]["whoop"]["days_behind"] == 10
    assert body["sources"]["eight_sleep"]["days_behind"] == 0


def test_degenerate_correlation_flagged(session, client):
    # Metrics exist but zero inferred events -> degenerate, actionable copy.
    for i in range(20):
        session.add(DailyMetric(date=DAY - timedelta(days=i), metric="hrv_rmssd",
                                value=40 + i % 3, unit="ms", source="whoop",
                                is_canonical=True))
    session.commit()
    cards = client.get("/api/correlations?days=30").json()
    sauna = next(c for c in cards if "Sauna" in c["title"])
    assert sauna["degenerate"] is True
    assert "healthos infer" in sauna["interpretation"]


def test_concordance_endpoint(session, client):
    """Whoop vs Eight Sleep on shared nights: offset + correlation."""
    for i in range(10):
        d = DAY - timedelta(days=i)
        session.add(DailyMetric(date=d, metric="hrv_rmssd", value=34 + i % 4, unit="ms",
                                source="whoop", is_canonical=True))
        # Pod reads consistently ~10ms higher on the same nights.
        session.add(DailyMetric(date=d, metric="hrv_rmssd", value=44 + i % 4, unit="ms",
                                source="eight_sleep", is_canonical=False))
    # One whoop-only travel night.
    session.add(DailyMetric(date=DAY - timedelta(days=11), metric="hrv_rmssd", value=30,
                            unit="ms", source="whoop", is_canonical=True))
    session.commit()
    body = client.get("/api/concordance?metric=hrv_rmssd&days=30").json()
    assert body["n_overlap"] == 10
    assert body["median_offset"] == 10.0
    assert body["r"] == 1.0
    assert body["n_whoop"] == 11

    bad = client.get("/api/concordance?metric=bogus&days=30").json()
    assert "error" in bad


def test_metric_sources_matrix(session, client):
    """Device-by-metric breakdown: per-source day counts, canonical flag,
    freshness; zero-impossible placeholders excluded."""
    for i in range(5):
        d = DAY - timedelta(days=i)
        session.add(DailyMetric(date=d, metric="hrv_rmssd", value=40, unit="ms",
                                source="whoop", is_canonical=True))
        session.add(DailyMetric(date=d, metric="hrv_rmssd", value=44, unit="ms",
                                source="eight_sleep", is_canonical=False))
    # Garmin HRV on 2 of those days + a placeholder 0 that must NOT count.
    session.add(DailyMetric(date=DAY, metric="hrv_rmssd", value=38, unit="ms",
                            source="garmin", is_canonical=False))
    session.add(DailyMetric(date=DAY - timedelta(days=1), metric="hrv_rmssd", value=39,
                            unit="ms", source="garmin", is_canonical=False))
    session.add(DailyMetric(date=DAY - timedelta(days=2), metric="hrv_rmssd", value=0,
                            unit="ms", source="garmin", is_canonical=False))
    session.commit()
    body = client.get("/api/metric-sources?days=30").json()
    hrv = next(m for m in body["metrics"] if m["metric"] == "hrv_rmssd")
    assert hrv["canonical_source"] == "whoop"
    assert hrv["total_days"] == 5
    by_src = {s["source"]: s for s in hrv["sources"]}
    assert by_src["whoop"]["days"] == 5 and by_src["whoop"]["canonical"] is True
    assert by_src["eight_sleep"]["days"] == 5
    assert by_src["garmin"]["days"] == 2  # the zero is excluded
    assert hrv["sources"][0]["source"] == "whoop"  # canonical first
    # Resolution logic surfaced for the build phase.
    res = hrv["resolution"]
    assert res["canonical"] == "whoop"
    assert res["zero_is_missing"] is True
    assert res["fallback_order"] == ["eight_sleep", "garmin"]  # priority order
    # Whoop has the latest day -> it wins; not a fallback.
    assert res["current_winner"] == "whoop"
    assert res["current_winner_is_fallback"] is False
