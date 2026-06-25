"""The SPA catch-all must be mounted unconditionally and tolerate a missing
``dist`` so the dashboard is served regardless of whether the frontend was built
before or after the server booted (Starlette otherwise 500s on a missing dir).
"""

from __future__ import annotations

import asyncio

from healthos.main import _SpaStaticFiles, app


def test_spa_catch_all_is_mounted():
    mounts = [r for r in app.routes if getattr(r, "name", None) == "frontend"]
    assert mounts, "frontend SPA catch-all should always be mounted"
    assert isinstance(mounts[0].app, _SpaStaticFiles)


def test_spa_staticfiles_tolerates_missing_directory():
    # Starlette's stock StaticFiles.check_config raises on a missing dir; ours
    # must not, so boot-before-build cleanly 404s instead of 500-ing.
    sf = _SpaStaticFiles(directory="/no/such/dist", html=True, check_dir=False)
    asyncio.run(sf.check_config())  # must not raise
