"""Shared pytest fixtures.

Tests run against the Postgres database in DATABASE_URL (CI/local spins up a
throwaway db). Each test gets a clean set of tables via TRUNCATE so they don't
bleed into one another.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from healthos.database import SessionLocal


@pytest.fixture
def session():
    s = SessionLocal()
    s.execute(
        text(
            "TRUNCATE daily_metrics, sleep_sessions, workouts, daily_events, "
            "calendar_events, sync_log RESTART IDENTITY CASCADE"
        )
    )
    s.commit()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from healthos.main import app

    with TestClient(app) as c:
        yield c
