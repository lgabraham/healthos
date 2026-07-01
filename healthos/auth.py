"""Single-user authentication for the whole app.

HealthOS is deployed on a public URL (Railway) and holds a complete personal
health history, so the API and dashboard must not be world-readable. This module
adds one shared secret, ``HEALTHOS_AUTH_TOKEN``:

- **Dashboard**: an unauthenticated browser request is redirected to ``/login``,
  a one-field password form. Submitting the correct secret sets a signed,
  HttpOnly session cookie (30 days), so you log in once per device.
- **API / webhooks / curl / iOS Shortcut**: send the same secret as
  ``Authorization: Bearer <token>``, an ``X-API-Key`` header, or a ``?token=``
  query param.

Fail-safe: when ``HEALTHOS_AUTH_TOKEN`` is unset, auth is disabled entirely
(local dev stays frictionless) and the app logs a loud warning at startup so a
public deployment is never *accidentally* left open.

The MCP server is a separate process that talks to the DB directly and is not
exposed over HTTP, so it isn't affected by this middleware.
"""

from __future__ import annotations

import hmac
import logging
from hashlib import sha256

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import settings

log = logging.getLogger("healthos.auth")

COOKIE_NAME = "healthos_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days

# Paths reachable without auth. The Whoop OAuth *callback* must be public (Whoop's
# servers call it with no cookie); the health probe is for Railway; the login page
# and its icon obviously can't require being logged in.
_PUBLIC_EXACT = {"/health", "/login", "/auth/whoop/callback", "/favicon.svg"}
_PUBLIC_PREFIXES = ("/apple-touch-icon",)


def _session_value() -> str:
    """The opaque cookie value: an HMAC of the secret, so the cookie never
    carries the raw token and can be checked without any server-side store."""
    secret = (settings.auth_token or "").encode()
    return hmac.new(secret, b"healthos-session-v1", sha256).hexdigest()


def _presented_token(request: Request) -> str | None:
    """Pull a bearer token from the request (header, X-API-Key, or ?token)."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    api_key = request.headers.get("x-api-key")
    if api_key:
        return api_key.strip()
    return request.query_params.get("token")


def _is_authenticated(request: Request) -> bool:
    token = settings.auth_token
    if not token:  # auth disabled
        return True
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie and hmac.compare_digest(cookie, _session_value()):
        return True
    presented = _presented_token(request)
    return bool(presented and hmac.compare_digest(presented, token))


def _is_public(path: str) -> bool:
    return path in _PUBLIC_EXACT or path.startswith(_PUBLIC_PREFIXES)


def _wants_html(request: Request) -> bool:
    return "text/html" in request.headers.get("accept", "")


class AuthMiddleware(BaseHTTPMiddleware):
    """Gate every request behind the shared secret (a no-op when it's unset)."""

    async def dispatch(self, request: Request, call_next):
        if (
            settings.auth_token
            and request.method != "OPTIONS"  # let CORS preflight through
            and not _is_public(request.url.path)
            and not _is_authenticated(request)
        ):
            if _wants_html(request):
                nxt = request.url.path
                if request.url.query:
                    nxt += "?" + request.url.query
                return RedirectResponse(f"/login?next={_safe_next(nxt)}", status_code=303)
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return await call_next(request)


router = APIRouter(tags=["auth"])


def _safe_next(nxt: str | None) -> str:
    """Only allow same-site relative redirects (prevent open-redirect)."""
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return "/"


def _secure(request: Request) -> bool:
    """Mark the cookie Secure when the browser reached us over HTTPS (directly or
    via a proxy like Railway), but not on plain-HTTP localhost dev."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto == "https"


_LOGIN_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark"><title>HealthOS</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
    background:#0a0a0a; color:#e5e5e5; font-family:ui-monospace,"IBM Plex Mono",Menlo,monospace; }}
  form {{ width:min(90vw,320px); display:flex; flex-direction:column; gap:.9rem; }}
  .brand {{ font-weight:700; letter-spacing:.04em; font-size:1.3rem; margin-bottom:.4rem; }}
  .dot {{ color:#f59e0b; }}
  input {{ background:#141414; border:1px solid #262626; color:#e5e5e5; border-radius:8px;
    padding:.7rem .8rem; font:inherit; }}
  input:focus {{ outline:none; border-color:#f59e0b; }}
  button {{ background:#f59e0b; color:#0a0a0a; border:0; border-radius:8px; padding:.7rem;
    font:inherit; font-weight:700; cursor:pointer; }}
  .err {{ color:#f87171; font-size:.85rem; min-height:1em; }}
</style></head>
<body><form method="post" action="/login">
  <div class="brand">HEALTH<span class="dot">·</span>OS</div>
  <input type="password" name="password" placeholder="password" autofocus autocomplete="current-password" required>
  <input type="hidden" name="next" value="{next}">
  <div class="err">{error}</div>
  <button type="submit">Sign in</button>
</form></body></html>"""


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/") -> HTMLResponse:
    if not settings.auth_token or _is_authenticated(request):
        return RedirectResponse(_safe_next(next), status_code=303)  # type: ignore[return-value]
    return HTMLResponse(_LOGIN_PAGE.format(next=_safe_next(next), error=""))


@router.post("/login")
def login_submit(request: Request, password: str = Form(...), next: str = Form("/")):
    token = settings.auth_token
    if not token or not hmac.compare_digest(password, token):
        page = _LOGIN_PAGE.format(next=_safe_next(next), error="Incorrect password.")
        return HTMLResponse(page, status_code=401)
    resp = RedirectResponse(_safe_next(next), status_code=303)
    resp.set_cookie(
        COOKIE_NAME,
        _session_value(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=_secure(request),
    )
    return resp


@router.post("/logout")
def logout(request: Request):
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp
