"""Auth gate: disabled by default, enforced when HEALTHOS_AUTH_TOKEN is set."""

from __future__ import annotations

import pytest

from healthos.config import settings


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setattr(settings, "auth_token", "s3cret", raising=False)
    yield "s3cret"


def test_auth_disabled_by_default(client, monkeypatch):
    """With no token configured, everything is open (frictionless local dev)."""
    monkeypatch.setattr(settings, "auth_token", None, raising=False)
    assert client.get("/api/status").status_code == 200


def test_api_requires_token_when_enabled(client, auth_on):
    assert client.get("/api/status").status_code == 401
    r = client.get("/api/status", headers={"Authorization": f"Bearer {auth_on}"})
    assert r.status_code == 200
    assert client.get("/api/status", headers={"X-API-Key": auth_on}).status_code == 200
    assert client.get(f"/api/status?token={auth_on}").status_code == 200
    assert client.get("/api/status", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_health_and_oauth_callback_stay_public(client, auth_on):
    assert client.get("/health").status_code == 200
    # The Whoop callback must be reachable without a cookie (Whoop calls it).
    # It errors on a bad/missing code, but must NOT be a 401 from the auth gate.
    assert client.get("/auth/whoop/callback").status_code != 401


def test_browser_request_redirects_to_login(client, auth_on):
    r = client.get("/api/status", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login?next=/api/status"


def test_login_sets_cookie_and_grants_access(client, auth_on):
    bad = client.post("/login", data={"password": "wrong"}, follow_redirects=False)
    assert bad.status_code == 401

    ok = client.post("/login", data={"password": auth_on, "next": "/"}, follow_redirects=False)
    assert ok.status_code == 303
    assert "healthos_session" in ok.cookies
    # The cookie (now on the client) authenticates subsequent API calls.
    assert client.get("/api/status").status_code == 200


def test_login_rejects_open_redirect(client, auth_on):
    r = client.post(
        "/login", data={"password": auth_on, "next": "//evil.com"}, follow_redirects=False
    )
    assert r.headers["location"] == "/"  # sanitized to a same-site path
