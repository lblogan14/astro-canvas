"""Manager preferences: security level, uv path, registry URL -- env defaults, DB overrides.

``ASTRO_CANVAS_*`` variables give the defaults (so a lab-server deployment can pin
``strict`` for everyone), and what the user picks in Manager > Settings is written to the
workspace's ``settings`` table and wins from then on.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, get_args

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astro_canvas.settings import Settings
from astro_canvas.store.models import Setting

SecurityLevel = Literal["strict", "standard", "permissive"]
SECURITY_LEVELS: tuple[str, ...] = get_args(SecurityLevel)

KEY_SECURITY = "manager.security"
KEY_UV_PATH = "manager.uv_path"
KEY_REGISTRY_URL = "manager.registry_url"

SECURITY_HELP: dict[str, str] = {
    "strict": "Only packs listed in the registry index may be installed.",
    "standard": "Registry packs plus any package name from PyPI.",
    "permissive": "Any source, including git URLs and local paths.",
}


class ManagerSettings(BaseModel):
    """The manager's own preferences (``GET/POST /api/manager/settings``)."""

    security: SecurityLevel = "standard"
    uv_path: str | None = Field(default=None, description="Explicit uv binary; empty means auto.")
    registry_url: str = ""


class ManagerSettingsUpdate(BaseModel):
    """Partial update; omitted fields keep their current value."""

    security: SecurityLevel | None = None
    uv_path: str | None = None
    registry_url: str | None = None


class SettingsStore:
    """Key/value rows in the workspace database, typed for the manager's three preferences."""

    def __init__(self, sessions: sessionmaker[Session], defaults: Settings) -> None:
        self.sessions = sessions
        self.defaults = defaults

    def raw(self) -> dict[str, str]:
        with self.sessions() as session:
            return {row.key: row.value for row in session.scalars(select(Setting)).all()}

    def get(self) -> ManagerSettings:
        """Stored preferences layered over the environment defaults."""
        stored = self.raw()
        security = stored.get(KEY_SECURITY, self.defaults.pack_security)
        if security not in SECURITY_LEVELS:
            security = "standard"
        uv_path = stored.get(KEY_UV_PATH) or (
            str(self.defaults.uv_path) if self.defaults.uv_path else None
        )
        return ManagerSettings(
            security=security,
            uv_path=uv_path or None,
            registry_url=stored.get(KEY_REGISTRY_URL) or self.defaults.registry_url,
        )

    def update(self, patch: ManagerSettingsUpdate) -> ManagerSettings:
        """Write the non-``None`` fields of ``patch`` and return the resulting settings."""
        values: dict[str, str] = {}
        if patch.security is not None:
            values[KEY_SECURITY] = patch.security
        if patch.uv_path is not None:
            values[KEY_UV_PATH] = patch.uv_path.strip()
        if patch.registry_url is not None:
            values[KEY_REGISTRY_URL] = patch.registry_url.strip()
        self.write(values)
        return self.get()

    def write(self, values: Mapping[str, str]) -> None:
        with self.sessions() as session:
            for key, value in values.items():
                row = session.get(Setting, key)
                if row is None:
                    session.add(Setting(key=key, value=value))
                else:
                    row.value = value
            session.commit()


__all__ = [
    "KEY_REGISTRY_URL",
    "KEY_SECURITY",
    "KEY_UV_PATH",
    "SECURITY_HELP",
    "SECURITY_LEVELS",
    "ManagerSettings",
    "ManagerSettingsUpdate",
    "SecurityLevel",
    "SettingsStore",
]
