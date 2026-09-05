"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import APIRouter, FastAPI

from astro_canvas._version import __version__
from astro_canvas.manager.packs import PackManager
from astro_canvas.manager.registry import RegistryClient
from astro_canvas.manager.settings import SettingsStore
from astro_canvas.sdk import DiscoveryResult, discover
from astro_canvas.server.auth import TokenAuthMiddleware, ensure_token
from astro_canvas.server.batch import router as batch_router
from astro_canvas.server.bundles import router as bundles_router
from astro_canvas.server.errors import install_error_handlers
from astro_canvas.server.exports import router as exports_router
from astro_canvas.server.guard import check_exposure
from astro_canvas.server.health import router as health_router
from astro_canvas.server.health import system_router
from astro_canvas.server.manager import router as manager_router
from astro_canvas.server.nodes import router as nodes_router
from astro_canvas.server.outputs import router as outputs_router
from astro_canvas.server.runs import router as runs_router
from astro_canvas.server.runtime import EngineRuntime
from astro_canvas.server.static import mount_static
from astro_canvas.server.templates import router as templates_router
from astro_canvas.server.trust import router as trust_router
from astro_canvas.server.workflows import router as workflows_router
from astro_canvas.server.workspace import router as workspace_router
from astro_canvas.server.ws import router as ws_router
from astro_canvas.settings import (
    Settings,
    apply_array_settings,
    apply_security_level,
    get_settings,
)

log = structlog.get_logger("astro_canvas.server")

DOCUMENT_ROUTERS: tuple[APIRouter, ...] = (
    system_router,
    nodes_router,
    workflows_router,
    batch_router,
    exports_router,
    templates_router,
    bundles_router,
    trust_router,
    runs_router,
    outputs_router,
    workspace_router,
)
"""Routers that act on one user's documents; in users mode each gets the caller's engine."""


def create_app(
    settings: Settings | None = None, discovery: DiscoveryResult | None = None
) -> FastAPI:
    """Create the ASGI application.

    Args:
        settings: Explicit settings; defaults to reading ``ASTRO_CANVAS_*`` env vars.
        discovery: Pre-built node registry; defaults to loading every installed pack.

    Raises:
        ExposureError: when the bind address would expose the server without user accounts.
    """
    settings = settings or get_settings()
    check_exposure(settings)
    apply_array_settings(settings)
    discovery = discovery if discovery is not None else discover()
    for pack in discovery.packs:
        if pack.error is not None:
            log.warning("pack failed to load", pack=pack.name, error=pack.error.error)
    for problem in discovery.registry.validate_unique():
        log.warning("registry problem", detail=problem)

    runtime = EngineRuntime(settings, discovery.registry)
    token = ensure_token(settings) if settings.token_auth else None
    users = _build_users(settings, discovery)
    engines = _engines(runtime, users)
    manager = build_manager(settings, runtime, discovery, engines) if settings.manager else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        runtime.bus.bind()
        runtime.start_watcher()
        yield
        if users is not None:
            await users.shutdown()
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
    app.state.packs = manager.records if manager is not None else discovery.packs
    app.state.runtime = runtime
    app.state.manager = manager
    app.state.token = token
    app.state.users = users
    install_error_handlers(app)
    app.include_router(health_router, prefix="/api")
    if users is not None:
        from astro_canvas.server.users import auth_router  # noqa: PLC0415 - optional extra

        app.include_router(auth_router(users), prefix="/api")
    scoped: list[Any] = [users.runtime_dependency()] if users is not None else []
    for router in DOCUMENT_ROUTERS:
        app.include_router(router, prefix="/api", dependencies=scoped)
    if manager is not None:
        # The manager mutates the server's own environment, so on a shared server it is
        # admin-only (design 12); the trust routes stay per-user, in ``trust_router``.
        admin: list[Any] = [users.admin_dependency()] if users is not None else []
        app.include_router(manager_router, prefix="/api", dependencies=admin)
    app.include_router(ws_router)
    if token is not None:
        app.add_middleware(TokenAuthMiddleware, token=token)
        log.info("auth token written", path=str(settings.config_dir / "token"))
    mount_static(app)
    return app


def _engines(runtime: EngineRuntime, users: Any) -> Callable[[], list[EngineRuntime]]:
    """Every engine a pack change has to reach: the server's, plus one per logged-in user."""
    if users is None:
        return lambda: [runtime]
    return lambda: [runtime, *users.pool.runtimes]


def _build_users(settings: Settings, discovery: DiscoveryResult) -> Any:
    """The multi-user backend, or ``None`` unless ``--auth users`` asked for it."""
    if not settings.user_auth:
        return None
    from astro_canvas.server.users import build_user_auth  # noqa: PLC0415 - optional extra

    users = build_user_auth(settings, discovery)
    log.info(
        "user accounts enabled",
        users_dir=str(settings.users_root),
        providers=[client.name for client in users.clients],
        registration=settings.registration,
    )
    return users


def build_manager(
    settings: Settings,
    runtime: EngineRuntime,
    discovery: DiscoveryResult,
    engines: Callable[[], list[EngineRuntime]] | None = None,
) -> PackManager | None:
    """Wire the pack manager to the runtime: save hook and recompile-on-decision.

    ``engines`` lists the runtimes a pack change has to reach. With one user that is just this
    one; with ``--auth users`` it is every session that is currently open, because installing a
    pack changed the code *all* of them run.

    A manager that cannot be built (an unreadable database, say) is logged and skipped: the app
    is still a canvas without it.
    """
    reach = engines if engines is not None else (lambda: [runtime])

    def recompile_everywhere() -> None:
        for engine in reach():
            engine.recompile_all()

    try:
        store = SettingsStore(runtime.workspace.sessions, settings)
        apply_security_level(store.get().security)
        return PackManager(
            discovery.registry,
            runtime.workspace.sessions,
            store,
            bus=runtime.bus,
            records=discovery.packs,
            on_change=lambda _packs: recompile_everywhere(),
            on_recompile=recompile_everywhere,
            registry_client=RegistryClient(store.get().registry_url, settings.config_dir),
            trust=runtime.trust,
        )
    except Exception as exc:  # noqa: BLE001 - the manager is optional, never fatal
        log.warning("pack manager unavailable", error=str(exc))
        return None
