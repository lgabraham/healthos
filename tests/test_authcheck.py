"""Auth self-check: reports configured/connected without leaking secrets."""

from __future__ import annotations

import json

import healthos.authcheck as ac


def test_all_unconfigured_reports_not_set_up(monkeypatch):
    from healthos.config import settings

    for attr in (
        "whoop_client_id",
        "whoop_client_secret",
        "garmin_email",
        "garmin_password",
        "garmin_tokenstore",
        "eight_sleep_email",
        "eight_sleep_password",
    ):
        monkeypatch.setattr(settings, attr, None, raising=False)
    monkeypatch.setattr(ac, "load_tokens", lambda provider: (None, None))

    rows = ac.check_all()
    by_provider = {r["provider"]: r for r in rows}
    assert by_provider["whoop"]["configured"] is False
    assert by_provider["garmin"]["configured"] is False
    assert by_provider["eight_sleep"]["configured"] is False
    # Not attempted when not configured.
    assert all(r["connected"] is None for r in rows)


def test_whoop_connected(monkeypatch):
    from healthos.config import settings

    monkeypatch.setattr(settings, "whoop_client_id", "cid", raising=False)
    monkeypatch.setattr(settings, "whoop_client_secret", "secret", raising=False)
    monkeypatch.setattr(ac, "load_tokens", lambda provider: ("acc", "ref"))

    class FakeClient:
        @classmethod
        def from_store(cls):
            return cls()

        def profile(self):
            return {"first_name": "Pat", "email": "pat@example.com"}

        def close(self):
            pass

    monkeypatch.setattr("healthos.sync.whoop.WhoopClient", FakeClient)
    status = ac.check_whoop()
    assert status.configured is True
    assert status.connected is True
    assert status.symbol == "✓"


def test_status_never_includes_secret_values(monkeypatch):
    from healthos.config import settings

    monkeypatch.setattr(settings, "whoop_client_id", "SUPER_SECRET_ID", raising=False)
    monkeypatch.setattr(settings, "whoop_client_secret", "SUPER_SECRET_VALUE", raising=False)
    monkeypatch.setattr(ac, "load_tokens", lambda provider: ("TOKEN_ABC", "REFRESH_XYZ"))

    class BoomClient:
        @classmethod
        def from_store(cls):
            return cls()

        def profile(self):
            raise RuntimeError("401 unauthorized")

        def close(self):
            pass

    monkeypatch.setattr("healthos.sync.whoop.WhoopClient", BoomClient)
    blob = json.dumps(ac.check_all())
    for secret in ("SUPER_SECRET_ID", "SUPER_SECRET_VALUE", "TOKEN_ABC", "REFRESH_XYZ"):
        assert secret not in blob
