"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI

from astro_canvas import __version__
from astro_canvas.server.health import router as health_router
from astro_canvas.server.static import mount_static
from astro_canvas.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the ASGI application.

    Args:
        settings: Explicit settings; defaults to reading ``ASTRO_CANVAS_*`` env vars.
    """
    settings = settings or get_settings()
    app = FastAPI(
        title="Astro Canvas",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings
    app.include_router(health_router, prefix="/api")
    mount_static(app)
    return app
