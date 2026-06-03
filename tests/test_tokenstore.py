"""OAuth token store: DB persistence + env fallback + refresh persistence."""

from __future__ import annotations

import healthos.tokenstore as ts
from healthos.sync.whoop import WhoopClient


def _clear(session):
    session.execute(__import__("sqlalchemy").text("TRUNCATE oauth_tokens"))
    session.commit()


def test_save_and_load_roundtrip(session):
    _clear(session)
    ts.save("whoop", "acc-1", "ref-1")
    access, refresh = ts.load("whoop")
    assert access == "acc-1"
    assert refresh == "ref-1"


def test_save_upserts(session):
    _clear(session)
    ts.save("whoop", "acc-1", "ref-1")
    ts.save("whoop", "acc-2", "ref-2")
    assert ts.load("whoop") == ("acc-2", "ref-2")


def test_load_falls_back_to_env(session, monkeypatch):
    _clear(session)
    from healthos.config import settings

    monkeypatch.setattr(settings, "whoop_access_token", "env-acc", raising=False)
    monkeypatch.setattr(settings, "whoop_refresh_token", "env-ref", raising=False)
    assert ts.load("whoop") == ("env-acc", "env-ref")


def test_refresh_persists_tokens(session, monkeypatch):
    _clear(session)
    ts.save("whoop", "old-acc", "old-ref")
    client = WhoopClient.from_store()
    client.client_id = "cid"
    client.client_secret = "secret"

    class FakeResp:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "new-acc", "refresh_token": "new-ref"}

    monkeypatch.setattr("healthos.sync.whoop.httpx.post", lambda *a, **k: FakeResp())
    client._refresh()

    # In-memory updated AND persisted to the store.
    assert client.access_token == "new-acc"
    assert ts.load("whoop") == ("new-acc", "new-ref")
