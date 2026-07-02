"""Parse and import blood-panel results into ``lab_results``.

The primary format is the "Instalab longitudinal" layout captured from the
portal — a header declaring the draw dates, then per-category marker lines:

    Values listed chronologically: [2023-03-16 | 2023-05-30 | 2025-09-23]

    METABOLIC
    Glucose (mg/dL): [100 | 80 | 97]  (70-90)
    Insulin (µIU/mL): [6.0 | 3 | 5.2]  (<8)

Each value cell may be a number, a qualified bound (``<6``, ``>60``), a dash
(``-`` = no draw that day), or non-numeric (``e3/e3``, ``NON REACTIVE``). The
trailing parenthesis is the lab's optimal range. We keep the raw text alongside
a parsed number so nothing is lost, and store the optimal range for flagging.

Values are never committed to the repo — this module only knows how to parse
text you feed it (via ``healthos labs-import <file>``) and upsert the rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date as _date

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .models import LabResult


@dataclass
class LabRow:
    date: _date
    marker: str
    category: str | None
    value_num: float | None
    value_text: str
    qualifier: str | None
    unit: str | None
    optimal_low: float | None
    optimal_high: float | None
    optimal_text: str | None


# A cell that means "no draw on this date" — skipped entirely.
_MISSING = {"-", "", "—", "n/a", "na"}


def parse_value(cell: str) -> tuple[float | None, str | None]:
    """(numeric, qualifier) for one value cell. Non-numeric → (None, None).

    ``<6`` → (6.0, "<"); ``>=18`` → (18.0, ">"); ``97`` → (97.0, None);
    ``e3/e3`` / ``NON REACTIVE`` → (None, None) — kept only as raw text.
    """
    cell = cell.strip()
    m = re.match(r"^(<=|>=|<|>)?\s*(-?\d+(?:\.\d+)?)$", cell)
    if not m:
        return None, None
    op, num = m.group(1), float(m.group(2))
    qualifier = None if op is None else op[0]  # collapse <=/>= to </>
    return num, qualifier


def parse_optimal(text: str | None) -> tuple[float | None, float | None, str | None]:
    """(low, high, raw) from an optimal-range string like ``70-90``, ``<8``,
    ``>=18``, ``<=1.2``, ``0``. Returns (None, None, None) when absent."""
    if not text:
        return None, None, None
    raw = text.strip()
    rng = re.match(r"^(-?\d+(?:\.\d+)?)\s*[-–]\s*(-?\d+(?:\.\d+)?)$", raw)
    if rng:
        return float(rng.group(1)), float(rng.group(2)), raw
    bound = re.match(r"^(<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)$", raw)
    if bound:
        op, num = bound.group(1), float(bound.group(2))
        if op.startswith("<"):
            return None, num, raw
        return num, None, raw
    single = re.match(r"^(-?\d+(?:\.\d+)?)$", raw)
    if single:  # an exact target (e.g. CAC "0")
        v = float(single.group(1))
        return v, v, raw
    return None, None, raw or None


def status_for(value_num: float | None, qualifier: str | None,
               low: float | None, high: float | None) -> str:
    """Classify a value against its optimal range: 'in' | 'low' | 'high' | 'unknown'.

    A '<' qualifier is treated as at-or-below its number (favourable for an
    upper-bound target), '>' as at-or-above. No range or no number → 'unknown'.
    """
    if value_num is None or (low is None and high is None):
        return "unknown"
    # Qualified bounds: "<6" clears a "<30" ceiling; ">60" clears a ">=40" floor.
    if qualifier == "<" and high is not None and value_num <= high:
        return "in"
    if qualifier == ">" and low is not None and value_num >= low:
        return "in"
    if high is not None and value_num > high:
        return "high"
    if low is not None and value_num < low:
        return "low"
    return "in"


_HEADER_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
# "Marker (unit): [a | b | c]  (optimal)"  — unit and optimal are optional.
_LINE_RE = re.compile(
    r"^(?P<marker>[^:\[]+?)\s*(?:\((?P<unit>[^)]*)\))?\s*:\s*"
    r"\[(?P<values>[^\]]*)\]\s*(?:\((?P<optimal>[^)]*)\))?"
)
# Section headers are ALL-CAPS lines (letters/&/spaces), e.g. "RED BLOOD CELLS".
_CATEGORY_RE = re.compile(r"^[A-Z][A-Z &]+$")


def _clean(text: str) -> str:
    """Strip the doc's markdown escaping (\\[, \\<, \\*) so regexes see plain text."""
    return text.replace("\\[", "[").replace("\\]", "]").replace(
        "\\<", "<").replace("\\>", ">").replace("\\*", "*").replace("\\=", "=")


def parse_instalab_longitudinal(text: str) -> list[LabRow]:
    """Parse the longitudinal panel into one LabRow per (date, marker) with data.

    Draw dates come from the "Values listed …: [d1 | d2 | …]" header; each marker
    line's Nth value cell maps to the Nth date. Cells that are missing/dashes are
    skipped, so a marker only measured on later draws produces rows only for those.
    """
    text = _clean(text)
    lines = [ln.strip() for ln in text.splitlines()]

    dates: list[_date] = []
    for ln in lines:
        if "listed" in ln.lower() and "[" in ln:
            dates = [_date.fromisoformat(d) for d in _HEADER_DATE_RE.findall(ln)]
            break
    if not dates:
        raise ValueError("Could not find the draw-date header ('Values listed … [dates]').")

    rows: list[LabRow] = []
    category: str | None = None
    for ln in lines:
        if not ln:
            continue
        if "listed" in ln.lower():
            continue  # the draw-date header itself matches the marker shape — skip it
        if _CATEGORY_RE.match(ln) and "[" not in ln:
            category = ln.title()
            continue
        m = _LINE_RE.match(ln)
        if not m:
            continue
        marker = m.group("marker").strip()
        unit = (m.group("unit") or "").strip() or None
        cells = [c.strip() for c in m.group("values").split("|")]
        low, high, opt_raw = parse_optimal(m.group("optimal"))
        for i, cell in enumerate(cells):
            if i >= len(dates) or cell.lower() in _MISSING:
                continue
            num, qual = parse_value(cell)
            rows.append(LabRow(
                date=dates[i], marker=marker, category=category,
                value_num=num, value_text=cell, qualifier=qual, unit=unit,
                optimal_low=low, optimal_high=high, optimal_text=opt_raw,
            ))
    return rows


def import_lab_rows(session: Session, rows: list[LabRow], source: str) -> int:
    """Upsert rows keyed on (date, marker, source). Idempotent — re-importing an
    updated panel refreshes values in place. Returns the count written."""
    written = 0
    for r in rows:
        stmt = (
            pg_insert(LabResult)
            .values(
                date=r.date, marker=r.marker, category=r.category,
                value_num=r.value_num, value_text=r.value_text, qualifier=r.qualifier,
                unit=r.unit, optimal_low=r.optimal_low, optimal_high=r.optimal_high,
                optimal_text=r.optimal_text, source=source,
            )
            .on_conflict_do_update(
                constraint="uq_lab_date_marker_source",
                set_={
                    "category": r.category, "value_num": r.value_num,
                    "value_text": r.value_text, "qualifier": r.qualifier, "unit": r.unit,
                    "optimal_low": r.optimal_low, "optimal_high": r.optimal_high,
                    "optimal_text": r.optimal_text,
                },
            )
        )
        session.execute(stmt)
        written += 1
    return written
