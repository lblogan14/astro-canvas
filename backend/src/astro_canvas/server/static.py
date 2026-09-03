"""Serve the built single-page app from ``astro_canvas/static`` when present."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
API_PREFIXES = ("api", "ws")


def mount_static(app: FastAPI, static_dir: Path = STATIC_DIR) -> bool:
    """Mount the SPA if ``static_dir/index.html`` exists.

    ``/assets/*`` is served as plain files; every other non-API path falls back to
    ``index.html`` so Vue Router history mode works on reload.

    Returns:
        ``True`` if the SPA was mounted, ``False`` if no build is present.
    """
    static_dir = static_dir.resolve()
    index = static_dir / "index.html"
    if not index.is_file():
        return False

    assets = static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        first = full_path.split("/", 1)[0]
        if first in API_PREFIXES:
            raise HTTPException(status_code=404)
        candidate = (static_dir / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(static_dir):
            return FileResponse(candidate)
        return FileResponse(index)

    return True
