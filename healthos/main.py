"""FastAPI application entrypoint + scheduler startup.

Run with: ``uvicorn healthos.main:app --reload`` (or ``python -m healthos.main``).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .api import admin, auth, metrics, webhooks
from .config import settings
from .sync.scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("healthos")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = start_scheduler()
    log.info("HealthOS %s started", __version__)
    try:
        yield
    finally:
        shutdown_scheduler()
        del scheduler


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


@app.get("/health")
def health() -> dict:
    """Liveness probe."""
    return {"status": "ok", "version": __version__}


def main() -> None:
    import uvicorn

    uvicorn.run("healthos.main:app", host="0.0.0.0", port=settings.port, reload=False)


if __name__ == "__main__":
    main()
