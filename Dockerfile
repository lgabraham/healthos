# ---------------------------------------------------------------------------
# Multi-stage build: compile the React dashboard, then serve it + the API from
# a single Python process. One image, one Railway service, one URL.
# ---------------------------------------------------------------------------

# --- Stage 1: build the frontend ------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /build
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build   # -> /build/dist

# --- Stage 2: runtime ------------------------------------------------------
FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install the package (editable, so `healthos` imports from /app and the app can
# locate frontend/dist at runtime). Eight Sleep client included.
COPY pyproject.toml README.md ./
COPY healthos/ ./healthos/
RUN pip install -e ".[eightsleep]"

# Migrations + the rest of the source tree.
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY scripts/ ./scripts/

# Built dashboard from stage 1 -> served at / by FastAPI when present.
COPY --from=frontend /build/dist ./frontend/dist

EXPOSE 8000
# Apply migrations, then boot the API + embedded nightly scheduler. Railway
# injects $PORT; default to 8000 for local `docker run`.
CMD ["sh", "-c", "alembic upgrade head && uvicorn healthos.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
