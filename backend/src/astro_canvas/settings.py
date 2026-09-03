"""Application settings, read from ``ASTRO_CANVAS_*`` environment variables."""

from __future__ import annotations

from pathlib import Path

import platformdirs
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def default_workspace() -> Path:
    """Return the default workspace folder (``<Documents>/AstroCanvas``)."""
    return Path(platformdirs.user_documents_dir()) / "AstroCanvas"


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


def get_settings(**overrides: object) -> Settings:
    """Build settings from the environment, applying non-``None`` overrides on top."""
    return Settings(**{k: v for k, v in overrides.items() if v is not None})  # type: ignore[arg-type]
