"""``/api/health`` and ``/api/system`` endpoints."""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from astro_canvas._version import __version__
from astro_canvas.server.deps import get_runtime
from astro_canvas.settings import Settings

router = APIRouter(tags=["system"])
system_router = APIRouter(tags=["system"])
"""``/api/system`` describes the *caller's* workspace, so on a users server it is authenticated."""


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    status: Literal["ok"]
    version: str


class PackInfo(BaseModel):
    """Summary of a discovered node pack (full detail at ``/api/packs``)."""

    name: str
    version: str
    enabled: bool = True
    node_count: int = 0
    security: str = "standard"
    error: str | None = None


class SystemInfo(BaseModel):
    """Environment report shown in the shell's About panel."""

    version: str
    python: str
    platform: str
    workspace: str
    workspace_exists: bool
    disk_free_bytes: int
    disk_total_bytes: int
    packs: list[PackInfo]


def _disk_usage(path: Path) -> tuple[int, int]:
    """Return ``(free, total)`` bytes for the nearest existing ancestor of ``path``."""
    probe = path
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    return usage.free, usage.total


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return ``ok`` and the server version."""
    return HealthResponse(status="ok", version=__version__)


@system_router.get("/system", response_model=SystemInfo)
def system(request: Request) -> SystemInfo:
    """Describe the running server: versions, workspace, disk, packs."""
    settings: Settings = request.app.state.settings
    runtime = get_runtime(request) if hasattr(request.app.state, "runtime") else None
    workspace: Path = runtime.workspace.root if runtime is not None else settings.workspace
    free, total = _disk_usage(workspace)
    return SystemInfo(
        version=__version__,
        python=platform.python_version(),
        platform=f"{platform.system()} {platform.release()} ({platform.machine()}) {sys.platform}",
        workspace=str(workspace),
        workspace_exists=workspace.is_dir(),
        disk_free_bytes=free,
        disk_total_bytes=total,
        packs=[
            PackInfo(
                name=p.name,
                version=p.version,
                enabled=p.enabled,
                node_count=p.node_count,
                security=p.security,
                error=p.error.error if p.error else None,
            )
            for p in request.app.state.packs
        ],
    )


__all__ = ["HealthResponse", "PackInfo", "SystemInfo", "router", "system_router"]
