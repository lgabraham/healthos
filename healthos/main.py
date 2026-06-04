"""FastAPI application entrypoint + scheduler startup.

Run with: ``uvicorn healthos.main:app --reload`` (or ``python -m healthos.main``).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import admin, auth, events, metrics, webhooks
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
    log.info("HealthOS %s started", __version__)
    try:
        yield
    finally:
        if settings.enable_scheduler:
            shutdown_scheduler()


app = FastAPI(title="HealthOS", version=__version__, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(metrics.router)
app.include_router(webhooks.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(events.router)


@app.get("/health")
def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "version": __version__}


def _mount_frontend() -> None:
    """Serve the built dashboard from the same service when present.

    Lets a single Railway deploy host both the API and the SPA (one URL — handy
    on mobile). No-op in dev, where Vite serves the frontend and proxies the API.
    """
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    if dist.is_dir():
        # API routers are registered first, so they take precedence over this
        # catch-all; html=True serves index.html at the root.
        app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
        log.info("Serving frontend from %s", dist)


_mount_frontend()


def main() -> None:
    import uvicorn

    uvicorn.run("healthos.main:app", host="0.0.0.0", port=settings.port, reload=False)


if __name__ == "__main__":
    main()
