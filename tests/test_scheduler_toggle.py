"""The ENABLE_SCHEDULER toggle gates the in-process nightly scheduler."""

from __future__ import annotations

from fastapi.testclient import TestClient


def _run_lifespan(monkeypatch, enabled: bool) -> list[str]:
    import healthos.main as m
    from healthos.config import settings

    calls: list[str] = []
    monkeypatch.setattr(settings, "enable_scheduler", enabled, raising=False)
    monkeypatch.setattr(m, "start_scheduler", lambda: calls.append("start"))
    monkeypatch.setattr(m, "shutdown_scheduler", lambda: calls.append("stop"))
    with TestClient(m.app):
        pass
    return calls


def test_scheduler_disabled_skips_startup(monkeypatch):
    assert _run_lifespan(monkeypatch, enabled=False) == []


def test_scheduler_enabled_starts(monkeypatch):
    calls = _run_lifespan(monkeypatch, enabled=True)
    assert "start" in calls
