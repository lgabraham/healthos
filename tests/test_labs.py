"""Lab parsing, status flagging, idempotent import, and the /api/labs endpoint."""

from __future__ import annotations

from datetime import date

import pytest

from healthos.labs import (
    import_lab_rows,
    parse_instalab_longitudinal,
    parse_optimal,
    parse_value,
    status_for,
)
from healthos.models import LabResult

FIXTURE = """INSTALAB — BLOOD PANEL RESULTS (longitudinal)

Values listed chronologically: [2023-03-16 | 2023-12-18 | 2025-09-23]  (optimal/goal)

METABOLIC
Glucose (mg/dL): [100 | 97 | 97]  (70-90)

LIPOPROTEINS
Lipoprotein(a) (mg/dL): [<6 | <5 | <6]  (<30)

NUTRIENTS
Vitamin D 25-OH (ng/mL): [32.4 | 48 | 25]  (40-80)
Free T3 (pg/mL): [- | - | 3.6]  (2-4.4)
"""


def test_parse_value():
    assert parse_value("97") == (97.0, None)
    assert parse_value("<6") == (6.0, "<")
    assert parse_value(">=18") == (18.0, ">")
    assert parse_value("0.48") == (0.48, None)
    assert parse_value("e3/e3") == (None, None)
    assert parse_value("NON REACTIVE") == (None, None)


def test_parse_optimal():
    assert parse_optimal("70-90") == (70.0, 90.0, "70-90")
    assert parse_optimal("<8") == (None, 8.0, "<8")
    assert parse_optimal(">=18") == (18.0, None, ">=18")
    assert parse_optimal("<=1.2") == (None, 1.2, "<=1.2")
    assert parse_optimal("0") == (0.0, 0.0, "0")
    assert parse_optimal(None) == (None, None, None)


def test_status_for():
    assert status_for(80, None, 70, 90) == "in"
    assert status_for(95, None, 70, 90) == "high"
    assert status_for(60, None, 70, 90) == "low"
    # Qualified bounds clear an appropriate ceiling/floor.
    assert status_for(6, "<", None, 30) == "in"      # "<6" under a <30 ceiling
    assert status_for(78, ">", 90, None) == "low"    # below a >90 floor (no qualifier match)
    assert status_for(95, ">", 90, None) == "in"     # ">95" clears a >90 floor
    # No range or no number -> unknown.
    assert status_for(5, None, None, None) == "unknown"
    assert status_for(None, None, 1, 2) == "unknown"


def test_parse_longitudinal_shape():
    rows = parse_instalab_longitudinal(FIXTURE)
    # Header line must NOT become a marker.
    assert all("listed" not in r.marker.lower() for r in rows)
    markers = {r.marker for r in rows}
    assert markers == {"Glucose", "Lipoprotein(a)", "Vitamin D 25-OH", "Free T3"}

    # Free T3 only has the last draw (two dashes skipped).
    t3 = [r for r in rows if r.marker == "Free T3"]
    assert len(t3) == 1 and t3[0].date == date(2025, 9, 23)

    # Qualifier + unit + category + optimal captured.
    lpa = next(r for r in rows if r.marker == "Lipoprotein(a)")
    assert lpa.qualifier == "<" and lpa.value_num == 6.0 and lpa.unit == "mg/dL"
    assert lpa.category == "Lipoproteins" and (lpa.optimal_low, lpa.optimal_high) == (None, 30.0)

    glu = next(r for r in rows if r.marker == "Glucose")
    assert glu.category == "Metabolic" and (glu.optimal_low, glu.optimal_high) == (70.0, 90.0)


def test_import_is_idempotent(session):
    rows = parse_instalab_longitudinal(FIXTURE)
    import_lab_rows(session, rows, "instalab")
    session.commit()
    n1 = session.query(LabResult).count()
    # Re-import the same panel -> no duplicate rows.
    import_lab_rows(session, rows, "instalab")
    session.commit()
    assert session.query(LabResult).count() == n1


def test_labs_endpoint(session, client):
    import_lab_rows(session, parse_instalab_longitudinal(FIXTURE), "instalab")
    session.commit()

    body = client.get("/api/labs").json()
    assert body["marker_count"] == 4
    assert body["draw_dates"] == ["2023-03-16", "2023-12-18", "2025-09-23"]

    cats = {c["name"] for c in body["categories"]}
    assert {"Metabolic", "Lipoproteins", "Nutrients"} <= cats

    # Vitamin D latest (25) is below the 40-80 range -> flagged low.
    vitd = next(m for c in body["categories"] for m in c["markers"]
                if m["marker"] == "Vitamin D 25-OH")
    assert vitd["latest"]["status"] == "low"
    assert vitd["trend"] == "down"  # 48 -> 25
    assert len(vitd["history"]) == 3

    flagged = {f["marker"] for f in body["flagged"]}
    assert "Vitamin D 25-OH" in flagged  # low
    assert "Glucose" in flagged          # 97 > 90 high
    assert "Lipoprotein(a)" not in flagged  # <6 under <30 -> in range


def test_labs_endpoint_empty(session, client):
    body = client.get("/api/labs").json()
    assert body["marker_count"] == 0
    assert body["categories"] == []
    assert body["flagged"] == []


def test_bad_format_rejected():
    with pytest.raises(ValueError, match="draw-date header"):
        parse_instalab_longitudinal("METABOLIC\nGlucose (mg/dL): [100]  (70-90)\n")
