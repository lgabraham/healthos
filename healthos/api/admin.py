"""Admin / operational routes: manual sync triggers and inference replay."""

from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, BackgroundTasks, Query

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/sync")
def trigger_sync(
    background: BackgroundTasks,
    start: str | None = Query(default=None, description="YYYY-MM-DD"),
    end: str | None = Query(default=None, description="YYYY-MM-DD"),
    source: str | None = Query(default=None, description="whoop|garmin|eight_sleep; all if omitted"),
) -> dict:
    """Kick a sync in the background. Defaults to yesterday for all sources."""
    from ..sync.runner import SOURCES, daily_sync, sync_all, sync_source

    if start and end:
        s, e = _date.fromisoformat(start), _date.fromisoformat(end)
        if source:
            if source not in SOURCES:
                return {"ok": False, "error": f"unknown source '{source}'"}
            background.add_task(sync_source, source, s, e, "manual")
        else:
            background.add_task(sync_all, s, e, "manual")
        return {"ok": True, "queued": {"start": start, "end": end, "source": source or "all"}}

    background.add_task(daily_sync)
    return {"ok": True, "queued": "daily_sync (yesterday)"}


@router.get("/auth-status")
def auth_status() -> dict:
    """Per-provider auth check (no secrets returned). Makes live calls, so it
    may take a few seconds."""
    from ..authcheck import check_all

    return {"providers": check_all()}


@router.post("/reinfer")
def reinfer(
    background: BackgroundTasks,
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
) -> dict:
    """Re-run behavioral inference over a historical range without re-syncing."""
    from ..database import get_session
    from ..inference.behavioral import run_inference_for_date

    def _job(s: _date, e: _date) -> None:
        with get_session() as session:
            day = s
            while day <= e:
                run_inference_for_date(session, day)
                day = _date.fromordinal(day.toordinal() + 1)

    background.add_task(_job, _date.fromisoformat(start), _date.fromisoformat(end))
    return {"ok": True, "queued": {"start": start, "end": end}}
