"""FastAPI application entrypoint + scheduler startup.

Run with: ``uvicorn healthos.main:app --reload`` (or ``python -m healthos.main``).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import admin, auth, events, journal, metrics, webhooks
from .auth import AuthMiddleware, router as auth_gate_router
from .config import settings
from .sync.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("healthos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.enable_scheduler:
        start_scheduler()
    else:
        log.info("In-process scheduler disabled (ENABLE_SCHEDULER=false); expecting external cron.")
    if not settings.auth_token:
        log.warning(
            "HEALTHOS_AUTH_TOKEN is not set — the API and dashboard are UNPROTECTED. "
            "This is fine for local dev, but set it before exposing HealthOS publicly."
        )
    else:
        log.info("Auth enabled (HEALTHOS_AUTH_TOKEN set).")
    log.info("HealthOS %s started", __version__)
    try:
        yield
    finally:
        if settings.enable_scheduler:
            shutdown_scheduler()


app = FastAPI(title="HealthOS", version=__version__, lifespan=lifespan)

# Auth gate wraps everything (added before CORS so it runs *after* CORS in the
# middleware stack — preflight OPTIONS still get their CORS headers, and the gate
# also covers the static SPA mount below).
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_gate_router)  # /login, /logout
app.include_router(metrics.router)
app.include_router(webhooks.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(events.router)
app.include_router(journal.router)


@app.get("/health")
def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "version": __version__}


class _SpaStaticFiles(StaticFiles):
    """``StaticFiles`` that tolerates a not-yet-built ``dist``.

    Starlette validates the directory exists on the first request (``check_config``)
    and 500s if it's missing — even with ``check_dir=False``, which only defers
    that check from init to first request. We skip it entirely so the SPA paths
    cleanly 404 while ``dist`` is absent (per-file lookup already 404s missing
    files) and start serving the moment a ``pnpm build`` creates it — no restart,
    so boot order never matters.
    """

    async def check_config(self) -> None:  # intentionally a no-op
        return None


def _mount_frontend() -> None:
    """Serve the built dashboard from the same service.

    Lets a single Railway deploy host both the API and the SPA (one URL — handy
    on mobile). No-op in dev, where Vite serves the frontend and proxies the API.

    Mounted unconditionally (see ``_SpaStaticFiles``) so a build done *after* the
    server booted is served without a restart. API routers are registered first,
    so they take precedence over this catch-all; html=True serves index.html at
    the root.
    """
    from pathlib import Path

    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    app.mount("/", _SpaStaticFiles(directory=str(dist), html=True, check_dir=False), name="frontend")
    if dist.is_dir():
        log.info("Serving frontend from %s", dist)
    else:
        log.info("Frontend not built yet (%s); will serve once `pnpm build` runs.", dist)


_mount_frontend()


def main() -> None:
    import uvicorn

    uvicorn.run("healthos.main:app", host="0.0.0.0", port=settings.port, reload=False)


if __name__ == "__main__":
    main()
