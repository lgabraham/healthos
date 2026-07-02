"""Lab-results endpoint: biomarkers grouped by system, with history + flags.

Read-only view over ``lab_results``. Each marker carries its full draw history,
its latest value, the lab's optimal range, and an in/low/high status computed
against that range — so the dashboard can flag out-of-range values and show a
sparkline without hardcoding any reference intervals.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import db_session
from ..labs import status_for
from ..models import LabResult

router = APIRouter(prefix="/api/labs", tags=["labs"])

# Clinical-ish display order; anything unlisted falls to the end alphabetically.
_CATEGORY_ORDER = [
    "Aging", "Metabolic", "Lipoproteins", "Lipids", "Inflammation",
    "Hormonal", "Thyroid", "Nutrients", "Kidney", "Liver", "Electrolytes",
    "Red Blood Cells", "Immune Function", "Blood Clotting", "Cancer Detection",
    "Bone & Muscle", "Vital Signs", "Cardiac", "Genetics",
]


def _f(v) -> float | None:
    return float(v) if v is not None else None


def _trend(history: list[dict]) -> str | None:
    """Direction of the last two numeric draws — a compact 'getting better/worse'
    hint is left to the UI (which knows if higher is good); here just up/down/flat."""
    nums = [h["value_num"] for h in history if h["value_num"] is not None]
    if len(nums) < 2:
        return None
    delta = nums[-1] - nums[-2]
    scale = abs(nums[-2]) or 1
    if abs(delta) / scale < 0.02:
        return "flat"
    return "up" if delta > 0 else "down"


@router.get("")
def labs(db: Session = Depends(db_session)) -> dict:
    rows = db.scalars(
        select(LabResult).order_by(LabResult.marker, LabResult.date)
    ).all()

    draw_dates = sorted({r.date for r in rows})
    by_marker: dict[str, list[LabResult]] = {}
    for r in rows:
        by_marker.setdefault(r.marker, []).append(r)

    categories: dict[str, list[dict]] = {}
    for marker, history in by_marker.items():
        history.sort(key=lambda r: r.date)
        first = history[0]
        low, high = _f(first.optimal_low), _f(first.optimal_high)
        hist = [
            {
                "date": r.date.isoformat(),
                "value_num": _f(r.value_num),
                "value_text": r.value_text,
                "qualifier": r.qualifier,
                "status": status_for(_f(r.value_num), r.qualifier, low, high),
            }
            for r in history
        ]
        latest = hist[-1]
        cat = first.category or "Other"
        categories.setdefault(cat, []).append({
            "marker": marker,
            "unit": first.unit,
            "optimal_text": first.optimal_text,
            "optimal_low": low,
            "optimal_high": high,
            "latest": latest,
            "history": hist,
            "trend": _trend(hist),
        })

    def cat_key(name: str) -> tuple[int, str]:
        return (_CATEGORY_ORDER.index(name) if name in _CATEGORY_ORDER
                else len(_CATEGORY_ORDER), name)

    ordered = [
        {"name": name, "markers": sorted(markers, key=lambda m: m["marker"])}
        for name, markers in sorted(categories.items(), key=lambda kv: cat_key(kv[0]))
    ]
    flagged = [
        {"marker": m["marker"], "category": c["name"],
         "value_text": m["latest"]["value_text"], "unit": m["unit"],
         "status": m["latest"]["status"], "optimal_text": m["optimal_text"]}
        for c in ordered for m in c["markers"]
        if m["latest"]["status"] in ("low", "high")
    ]
    return {
        "draw_dates": [d.isoformat() for d in draw_dates],
        "categories": ordered,
        "flagged": flagged,
        "marker_count": len(by_marker),
    }
