"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from astro_canvas._version import __version__
from astro_canvas.sdk import DiscoveryResult, discover
from astro_canvas.server.auth import TokenAuthMiddleware, ensure_token
from astro_canvas.server.health import router as health_router
from astro_canvas.server.nodes import router as nodes_router
from astro_canvas.server.outputs import router as outputs_router
from astro_canvas.server.runs import router as runs_router
from astro_canvas.server.runtime import EngineRuntime
from astro_canvas.server.static import mount_static
from astro_canvas.server.workflows import router as workflows_router
from astro_canvas.server.ws import router as ws_router
from astro_canvas.settings import Settings, get_settings

log = structlog.get_logger("astro_canvas.server")


def create_app(
    settings: Settings | None = None, discovery: DiscoveryResult | None = None
) -> FastAPI:
    """Create the ASGI application.

    Args:
        settings: Explicit settings; defaults to reading ``ASTRO_CANVAS_*`` env vars.
        discovery: Pre-built node registry; defaults to loading every installed pack.
    """
    settings = settings or get_settings()
    discovery = discovery if discovery is not None else discover()
    for pack in discovery.packs:
        if pack.error is not None:
            log.warning("pack failed to load", pack=pack.name, error=pack.error.error)
    for problem in discovery.registry.validate_unique():
        log.warning("registry problem", detail=problem)

    runtime = EngineRuntime(settings, discovery.registry)
    token = ensure_token(settings) if settings.auth else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await runtime.shutdown()

    app = FastAPI(
        title="Astro Canvas",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.registry = discovery.registry
    app.state.packs = discovery.packs
    app.state.runtime = runtime
    app.state.token = token
    app.include_router(health_router, prefix="/api")
    app.include_router(nodes_router, prefix="/api")
    app.include_router(workflows_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(outputs_router, prefix="/api")
    app.include_router(ws_router)
    if token is not None:
        app.add_middleware(TokenAuthMiddleware, token=token)
        log.info("auth token written", path=str(settings.config_dir / "token"))
    mount_static(app)
    return app
