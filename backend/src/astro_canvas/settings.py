"""Application settings, read from ``ASTRO_CANVAS_*`` environment variables."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import platformdirs
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from astro_canvas.sdk.memmap import MMAP_MIN_BYTES_ENV

CODE_SECURITY_ENV = "ASTRO_CANVAS_CODE_SECURITY"
"""Read by ``core.code.python``; worker processes inherit it from the server's environment."""

AuthMode = Literal["none", "token", "users"]
"""``astro-canvas serve --auth <mode>`` (design 11-12)."""

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
"""Bind addresses that are only reachable from this machine."""


def default_workspace() -> Path:
    """The workspace to open: the one the user last chose, else ``<Documents>/AstroCanvas``."""
    from astro_canvas.store.recent import RecentWorkspaces  # noqa: PLC0415 - avoids a cycle

    chosen = RecentWorkspaces(default_config_dir()).selected()
    return chosen if chosen is not None else Path(platformdirs.user_documents_dir()) / "AstroCanvas"


def default_config_dir() -> Path:
    """Per-user config folder holding the ``token`` file.

    Reads ``ASTRO_CANVAS_CONFIG_DIR`` itself rather than leaving it to pydantic-settings, because
    ``default_workspace`` needs the folder *before* a ``Settings`` object exists.
    """
    override = os.environ.get("ASTRO_CANVAS_CONFIG_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_config_dir("AstroCanvas", appauthor=False))


class Settings(BaseSettings):
    """Runtime configuration.

    Every field can be overridden with an environment variable prefixed with
    ``ASTRO_CANVAS_`` (for example ``ASTRO_CANVAS_PORT=9000``).
    """

    model_config = SettingsConfigDict(env_prefix="ASTRO_CANVAS_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)
    workspace: Path = Field(default_factory=default_workspace)
    log_level: str = "info"

    # Security (design 11): bearer token for /api and /ws; generated when unset.
    auth: AuthMode = "token"
    """``none`` serves unauthenticated, ``token`` uses one bearer token for the whole server,
    ``users`` enables the multi-user login backend (design 12; needs the ``users`` extra)."""
    token: str | None = None
    config_dir: Path = Field(default_factory=default_config_dir)

    # Lab server (design 12). Only read when ``auth == "users"``.
    users_dir: Path | None = None
    """Parent of the per-user workspaces; defaults to ``<workspace>/users``."""
    shared_dir: Path | None = None
    """Read-only folder mounted as ``shared/`` in every user's workspace."""
    database_url: str = ""
    """Identity database; empty means ``<config>/users.db`` (SQLite)."""
    secret: str | None = None
    """Signs login cookies and JWTs; generated and persisted next to the token when unset."""
    cookie_secure: bool | None = None
    """Force the ``Secure`` cookie flag; ``None`` derives it from ``public_url``/``https``."""
    public_url: str = ""
    """External origin (``https://canvas.lab.example``) a reverse proxy serves this app on."""
    registration: bool = True
    """Allow self-service sign-up; turn it off to invite users with ``astro-canvas user add``."""
    admin_emails: str = ""
    """Comma-separated addresses that become superusers on registration."""
    oauth_github_client_id: str = ""
    oauth_github_client_secret: str = ""
    oidc_name: str = "oidc"
    """Label of the generic OpenID provider (``orcid`` for ORCID)."""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_configuration_url: str = ""
    """The provider's ``.well-known/openid-configuration``."""
    allow_public_bind: bool = False
    """``--i-know-what-i-am-doing``: serve on a public interface without user accounts."""

    # Execution engine (design 6.2-6.3).
    cache_memory_mb: int = Field(default=2048, ge=1)
    cache_disk_gb: float = Field(default=20.0, gt=0)
    cache_max_age_days: int = Field(default=30, ge=1)
    max_workers: int | None = Field(default=None, ge=1)
    process_pool: bool = True
    run_timeout_s: float | None = Field(default=3600.0, gt=0)
    debounce_ms: int = Field(default=250, ge=0)
    auto_threshold_ms: int = Field(default=2000, ge=0)
    mmap_min_mb: int = Field(default=8, ge=0)
    """Arrays this big (IFU cubes) are stored as mappable blob parts and never copied into the
    memory cache; ``0`` disables mapping and keeps everything inline."""

    # Workspace (design 6.5): publish ``workspace.changed`` events from a file watcher.
    watch_workspace: bool = True

    # Pack manager (design 9). These are defaults; what the user picks in Manager > Settings is
    # stored in the workspace database and wins from then on.
    pack_security: Literal["strict", "standard", "permissive"] = "standard"
    """``strict`` installs registry packs only, ``standard`` adds PyPI, ``permissive`` adds git
    URLs and local paths (and lifts the code node's import restrictions)."""
    uv_path: Path | None = None
    """Explicit ``uv`` binary; unset means "next to the launcher, then ``PATH``"."""
    registry_url: str = ""
    """Pack registry ``index.json``; empty uses the built-in default."""
    manager: bool = True
    """Set false to serve without ``/api/manager`` (a locked-down lab deployment)."""

    @property
    def token_auth(self) -> bool:
        """True when one shared bearer token guards ``/api`` and ``/ws``."""
        return self.auth == "token"

    @property
    def user_auth(self) -> bool:
        """True when the multi-user login backend is enabled."""
        return self.auth == "users"

    @property
    def is_loopback(self) -> bool:
        """True when ``host`` is only reachable from this machine."""
        return self.host in LOOPBACK

    @property
    def users_root(self) -> Path:
        """Parent folder of the per-user workspaces."""
        return Path(self.users_dir) if self.users_dir else Path(self.workspace) / "users"

    @property
    def https(self) -> bool:
        """True when the app is reached over TLS (directly or through a proxy)."""
        return self.public_url.startswith("https://")

    @property
    def secure_cookies(self) -> bool:
        """Whether login cookies get the ``Secure`` flag."""
        return self.https if self.cookie_secure is None else self.cookie_secure

    @property
    def admins(self) -> frozenset[str]:
        """Normalised ``admin_emails``."""
        return frozenset(
            part.strip().lower() for part in self.admin_emails.split(",") if part.strip()
        )


def apply_array_settings(settings: Settings) -> None:
    """Publish ``mmap_min_mb`` to the SDK (and to worker processes) as an environment variable."""
    os.environ[MMAP_MIN_BYTES_ENV] = str(settings.mmap_min_mb * 1024 * 1024)


def apply_security_level(level: str) -> None:
    """Publish the pack security level so the code node sees it, in this process and in workers."""
    os.environ[CODE_SECURITY_ENV] = level


def get_settings(**overrides: object) -> Settings:
    """Build settings from the environment, applying non-``None`` overrides on top."""
    return Settings(**{k: v for k, v in overrides.items() if v is not None})  # type: ignore[arg-type]
