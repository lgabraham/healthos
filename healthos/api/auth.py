"""Whoop OAuth bootstrap routes.

Used once to authorize HealthOS against your Whoop account. Visit
``/auth/whoop`` to start the consent flow; Whoop redirects back to
``/auth/whoop/callback`` with a code we exchange for tokens. The tokens are
printed/returned so you can paste them into .env or Railham env vars — we don't
persist secrets to disk automatically.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from ..sync import whoop

router = APIRouter(prefix="/auth/whoop", tags=["auth"])


@router.get("")
def start() -> RedirectResponse:
    return RedirectResponse(whoop.authorize_url())


@router.get("/callback", response_class=HTMLResponse)
def callback(code: str | None = Query(default=None), error: str | None = Query(default=None)):
    if error:
        raise HTTPException(status_code=400, detail=f"Whoop authorization failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code.")
    tokens = whoop.exchange_code(code)
    access = tokens.get("access_token", "")
    refresh = tokens.get("refresh_token", "")
    return HTMLResponse(
        f"""
        <html><body style="font-family:monospace;background:#0a0a0a;color:#e5e5e5;padding:2rem">
          <h2 style="color:#f59e0b">Whoop connected.</h2>
          <p>Copy these into your environment, then restart HealthOS:</p>
          <pre>WHOOP_ACCESS_TOKEN={access}
WHOOP_REFRESH_TOKEN={refresh}</pre>
          <p>You can close this tab.</p>
        </body></html>
        """
    )
