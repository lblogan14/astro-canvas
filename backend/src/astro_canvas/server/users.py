"""``--auth users``: logins, per-user workspaces and the admin flag (design 12).

The desktop tier has one workspace and one token. A lab server has one *process* and many people,
so this module supplies the three things that difference needs:

1. **Identity** -- fastapi-users over the identity database (``store/identity.py``): email and
   password, GitHub, and a generic OpenID provider that covers ORCID. Browsers authenticate with
   an httpOnly cookie (``Secure`` behind TLS, ``SameSite=Lax``, and the OAuth flow carries
   fastapi-users' CSRF cookie); scripts and the CLI use the same JWT as a bearer token.
2. **Isolation** -- one ``EngineRuntime`` per user, created on first request, rooted at
   ``<users_dir>/<user id>``. A separate runtime means a separate cache, run queue, event bus and
   ``trust`` table: nothing one user does is visible to anyone else. ``shared_dir`` is mounted
   read-only into all of them as ``shared/``.
3. **Authority** -- ``is_superuser`` gates ``/api/manager``, because the pack manager installs
   into the *server's* environment and therefore changes what every other user runs.

The identity tables are the only shared state; everything else stays in the per-user workspace.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, exceptions, schemas
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
    JWTStrategy,
)
from httpx_oauth.oauth2 import BaseOAuth2
from pydantic import BaseModel
from starlette.websockets import WebSocket

from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.runtime import EngineRuntime
from astro_canvas.settings import Settings
from astro_canvas.store.identity import IdentityStore, User

log = structlog.get_logger("astro_canvas.server")

COOKIE_NAME = "astro_canvas_auth"
SESSION_LIFETIME_S = 7 * 24 * 3600
MIN_PASSWORD_LENGTH = 8
SECRET_FILE = "secret"


class UsersUnavailableError(RuntimeError):
    """``--auth users`` was requested but the ``users`` extra is not installed."""


def ensure_secret(settings: Settings) -> str:
    """The cookie/JWT signing secret, persisted next to the token file when it was generated.

    A generated secret must survive a restart or every session is invalidated, so it lives in the
    config folder with ``0600`` permissions -- the same place and treatment as the desktop token.
    """
    if settings.secret:
        return settings.secret
    path = Path(settings.config_dir) / SECRET_FILE
    with contextlib.suppress(OSError):
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    secret = secrets.token_urlsafe(48)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secret, encoding="utf-8")
        with contextlib.suppress(OSError):  # Windows ACLs
            path.chmod(0o600)
    except OSError as exc:  # pragma: no cover - unwritable config dir
        log.warning("could not persist the auth secret", path=str(path), error=str(exc))
    return secret


class UserRead(schemas.BaseUser[uuid.UUID]):
    """A user as ``/api/users/me`` returns it."""

    display_name: str = ""


class UserCreate(schemas.BaseUserCreate):
    """Sign-up payload."""

    display_name: str = ""


class UserUpdate(schemas.BaseUserUpdate):
    """Profile update payload."""

    display_name: str | None = None


class AuthInfo(BaseModel):
    """``GET /api/auth/info``: what the login page needs before anybody is logged in."""

    mode: str
    registration: bool = True
    providers: list[str] = []
    """OAuth provider names with a configured client (``github``, ``orcid``, ...)."""


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Password rules, the admin list and the first-login workspace."""

    def __init__(self, user_db: Any, settings: Settings) -> None:
        super().__init__(user_db)
        self.settings = settings
        self.reset_password_token_secret = ensure_secret(settings)
        self.verification_token_secret = self.reset_password_token_secret

    async def validate_password(self, password: str, user: Any) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise exceptions.InvalidPasswordException(
                f"the password must be at least {MIN_PASSWORD_LENGTH} characters"
            )
        email = str(getattr(user, "email", "") or "")
        if email and password.lower() in email.lower():
            raise exceptions.InvalidPasswordException("the password must not contain your email")

    async def on_after_register(self, user: User, request: Request | None = None) -> None:
        """Promote the configured admin addresses and create the user's workspace folder."""
        if user.email.lower() in self.settings.admins and not user.is_superuser:
            await self.user_db.update(user, {"is_superuser": True})
            user.is_superuser = True
        workspace_root(self.settings, user.id).mkdir(parents=True, exist_ok=True)
        log.info("user registered", user=str(user.id), admin=user.is_superuser)


def workspace_root(settings: Settings, user_id: uuid.UUID) -> Path:
    """``<users_dir>/<user id>`` -- the folder that *is* this user's workspace."""
    return Path(settings.users_root) / str(user_id)


class RuntimePool:
    """A lazily built ``EngineRuntime`` per user, all sharing one node registry.

    A runtime is not cheap (caches, a thread pool and -- on the first expensive node -- a process
    pool), which is why it is created on the user's first request rather than at start-up, and why
    a lab deployment is sized for concurrent users rather than for accounts.
    """

    def __init__(self, settings: Settings, discovery: DiscoveryResult) -> None:
        self.settings = settings
        self.discovery = discovery
        self._runtimes: dict[str, EngineRuntime] = {}
        self._lock = asyncio.Lock()

    def settings_for(self, user_id: uuid.UUID) -> Settings:
        """Per-user settings: their own workspace, and their own config folder inside it."""
        root = workspace_root(self.settings, user_id)
        return self.settings.model_copy(
            update={"workspace": root, "config_dir": root / ".astro-canvas"}
        )

    async def get(self, user: User) -> EngineRuntime:
        """This user's engine, started on first use."""
        key = str(user.id)
        existing = self._runtimes.get(key)
        if existing is not None:
            return existing
        async with self._lock:
            existing = self._runtimes.get(key)
            if existing is not None:
                return existing
            runtime = EngineRuntime(self.settings_for(user.id), self.discovery.registry)
            runtime.bus.bind(asyncio.get_running_loop())
            runtime.start_watcher()
            self._runtimes[key] = runtime
            log.info("engine started", user=key, workspace=str(runtime.workspace.root))
            return runtime

    @property
    def runtimes(self) -> list[EngineRuntime]:
        """The engines started so far (a pack change has to reach every one of them)."""
        return list(self._runtimes.values())

    async def shutdown(self) -> None:
        runtimes, self._runtimes = list(self._runtimes.values()), {}
        await asyncio.gather(*(r.shutdown() for r in runtimes), return_exceptions=True)


def oauth_clients(settings: Settings) -> list[BaseOAuth2[Any]]:
    """The OAuth clients the operator configured (none by default)."""
    clients: list[BaseOAuth2[Any]] = []
    if settings.oauth_github_client_id and settings.oauth_github_client_secret:
        from httpx_oauth.clients.github import GitHubOAuth2  # noqa: PLC0415 - optional provider

        clients.append(
            GitHubOAuth2(settings.oauth_github_client_id, settings.oauth_github_client_secret)
        )
    if settings.oidc_client_id and settings.oidc_configuration_url:
        from httpx_oauth.clients.openid import OpenID  # noqa: PLC0415 - optional provider

        clients.append(
            OpenID(
                settings.oidc_client_id,
                settings.oidc_client_secret,
                settings.oidc_configuration_url,
                name=settings.oidc_name,
            )
        )
    return clients


class UserAuth:
    """Everything ``create_app`` needs to serve a multi-user deployment."""

    def __init__(
        self, settings: Settings, discovery: DiscoveryResult, identity: IdentityStore
    ) -> None:
        self.settings = settings
        self.identity = identity
        self.pool = RuntimePool(settings, discovery)
        self.secret = ensure_secret(settings)
        self.clients = oauth_clients(settings)

        def strategy() -> JWTStrategy[User, uuid.UUID]:
            return JWTStrategy(secret=self.secret, lifetime_seconds=SESSION_LIFETIME_S)

        self.strategy = strategy
        self.cookie = AuthenticationBackend(
            name="cookie",
            transport=CookieTransport(
                cookie_name=COOKIE_NAME,
                cookie_max_age=SESSION_LIFETIME_S,
                cookie_secure=settings.secure_cookies,
                cookie_httponly=True,
                cookie_samesite="lax",
            ),
            get_strategy=strategy,
        )
        self.bearer = AuthenticationBackend(
            name="bearer",
            transport=BearerTransport(tokenUrl="api/auth/bearer/login"),
            get_strategy=strategy,
        )
        self.users: FastAPIUsers[User, uuid.UUID] = FastAPIUsers(
            self.get_user_manager, [self.cookie, self.bearer]
        )
        self.current_user = self.users.current_user(active=True)
        self.current_admin = self.users.current_user(active=True, superuser=True)

    async def get_user_manager(self) -> AsyncIterator[UserManager]:
        """The fastapi-users manager (a FastAPI dependency)."""
        async for user_db in self.identity.user_db():
            yield UserManager(user_db, self.settings)

    @property
    def info(self) -> AuthInfo:
        return AuthInfo(
            mode="users",
            registration=self.settings.registration,
            providers=[client.name for client in self.clients],
        )

    # --- dependencies ------------------------------------------------------------------------

    def runtime_dependency(self) -> Any:
        """A router dependency that puts the caller's engine on ``request.state.runtime``."""

        async def bind(
            request: Request,
            user: User = Depends(self.current_user),  # noqa: B008 - FastAPI's contract
        ) -> None:
            request.state.user = user
            request.state.runtime = await self.pool.get(user)

        return Depends(bind)

    def admin_dependency(self) -> Any:
        """The same, but only for a user with the admin flag."""

        async def bind(
            request: Request,
            user: User = Depends(self.current_admin),  # noqa: B008 - FastAPI's contract
        ) -> None:
            request.state.user = user
            request.state.runtime = await self.pool.get(user)

        return Depends(bind)

    # --- websocket ---------------------------------------------------------------------------

    async def authenticate_ws(self, websocket: WebSocket) -> User | None:
        """Resolve the cookie (or ``?token=`` bearer JWT) of a WebSocket handshake to a user."""
        token = websocket.cookies.get(COOKIE_NAME) or websocket.query_params.get("token")
        if not token:
            return None
        async for manager in self.get_user_manager():
            user = await self.strategy().read_token(token, manager)
            return user if user is not None and user.is_active else None
        return None  # pragma: no cover - the generator always yields once

    # --- lifecycle ---------------------------------------------------------------------------

    async def shutdown(self) -> None:
        await self.pool.shutdown()
        await self.identity.close()


def auth_router(auth: UserAuth) -> APIRouter:
    """``/api/auth/*`` and ``/api/users/*``: login, logout, sign-up, OAuth and the profile."""
    router = APIRouter()
    router.include_router(auth.users.get_auth_router(auth.cookie), prefix="/auth", tags=["auth"])
    router.include_router(
        auth.users.get_auth_router(auth.bearer), prefix="/auth/bearer", tags=["auth"]
    )
    if auth.settings.registration:
        router.include_router(
            auth.users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"]
        )
    router.include_router(
        auth.users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"]
    )
    for client in auth.clients:
        router.include_router(
            auth.users.get_oauth_router(
                client,
                auth.cookie,
                auth.secret,
                associate_by_email=True,
                is_verified_by_default=True,
                csrf_token_cookie_secure=auth.settings.secure_cookies,
            ),
            prefix=f"/auth/{client.name}",
            tags=["auth"],
        )

    @router.get("/auth/info", response_model=AuthInfo, tags=["auth"])
    def auth_info() -> AuthInfo:
        """Which login methods this server offers (public: the login page needs it)."""
        return auth.info

    return router


def build_user_auth(
    settings: Settings, discovery: DiscoveryResult, *, identity: IdentityStore | None = None
) -> UserAuth:
    """Open the identity database and wire the login backends.

    Raises:
        UsersUnavailableError: when the optional ``users`` dependencies are missing.
    """
    try:
        store = identity if identity is not None else IdentityStore.open(settings)
    except ImportError as exc:  # pragma: no cover - only without the extra
        raise UsersUnavailableError(
            "--auth users needs the users extra: uv tool install 'astro-canvas[users]'"
        ) from exc
    Path(settings.users_root).mkdir(parents=True, exist_ok=True)
    return UserAuth(settings, discovery, store)


def user_state(app: FastAPI) -> UserAuth | None:
    """The ``UserAuth`` of a running app, or ``None`` on a single-user server."""
    state: UserAuth | None = getattr(app.state, "users", None)
    return state


__all__ = [
    "COOKIE_NAME",
    "AuthInfo",
    "RuntimePool",
    "UserAuth",
    "UserCreate",
    "UserManager",
    "UserRead",
    "UserUpdate",
    "UsersUnavailableError",
    "auth_router",
    "build_user_auth",
    "ensure_secret",
    "user_state",
    "workspace_root",
]
