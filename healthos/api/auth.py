"""Whoop OAuth bootstrap routes.

Used once to authorize HealthOS against your Whoop account. Visit
``/auth/whoop`` to start the consent flow; Whoop redirects back to
``/auth/whoop/callback`` with a code we exchange for tokens. Tokens are saved
straight to the DB token store (and refreshed in place thereafter), so there's
nothing to copy-paste — this works the same from a phone.
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

    # Persist straight to the DB so there's nothing to copy-paste — refreshes
    # from here on update the store in place. Works the same from a phone.
    from ..tokenstore import save

    save("whoop", access, refresh)

    return HTMLResponse(
        """
        <html><body style="font-family:monospace;background:#0a0a0a;color:#e5e5e5;padding:2rem">
          <h2 style="color:#f59e0b">Whoop connected.</h2>
          <p>Tokens were saved to HealthOS. Nothing to copy — you can close this tab.</p>
        </body></html>
        """
    )
