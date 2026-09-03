"""Application settings, read from ``ASTRO_CANVAS_*`` environment variables."""

from __future__ import annotations

from pathlib import Path

import platformdirs
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_workspace() -> Path:
    """Return the default workspace folder (``<Documents>/AstroCanvas``)."""
    return Path(platformdirs.user_documents_dir()) / "AstroCanvas"


def default_config_dir() -> Path:
    """Per-user config folder holding the ``token`` file."""
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
    auth: bool = True
    token: str | None = None
    config_dir: Path = Field(default_factory=default_config_dir)

    # Execution engine (design 6.2-6.3).
    cache_memory_mb: int = Field(default=2048, ge=1)
    cache_disk_gb: float = Field(default=20.0, gt=0)
    cache_max_age_days: int = Field(default=30, ge=1)
    max_workers: int | None = Field(default=None, ge=1)
    process_pool: bool = True
    run_timeout_s: float | None = Field(default=3600.0, gt=0)
    debounce_ms: int = Field(default=250, ge=0)
    auto_threshold_ms: int = Field(default=2000, ge=0)

    # Workspace (design 6.5): publish ``workspace.changed`` events from a file watcher.
    watch_workspace: bool = True


def get_settings(**overrides: object) -> Settings:
    """Build settings from the environment, applying non-``None`` overrides on top."""
    return Settings(**{k: v for k, v in overrides.items() if v is not None})  # type: ignore[arg-type]
