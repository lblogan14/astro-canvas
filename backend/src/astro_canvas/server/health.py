"""``/api/health`` and ``/api/system`` endpoints."""

from __future__ import annotations

import platform
import shutil
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from astro_canvas import __version__
from astro_canvas.settings import Settings

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Liveness probe payload."""

    status: Literal["ok"]
    version: str


class PackInfo(BaseModel):
    """Summary of an installed node pack (populated from phase 01 onwards)."""

    name: str
    version: str
    enabled: bool = True


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


@router.get("/system", response_model=SystemInfo)
def system(request: Request) -> SystemInfo:
    """Describe the running server: versions, workspace, disk, packs."""
    settings: Settings = request.app.state.settings
    free, total = _disk_usage(settings.workspace)
    return SystemInfo(
        version=__version__,
        python=platform.python_version(),
        platform=f"{platform.system()} {platform.release()} ({platform.machine()}) {sys.platform}",
        workspace=str(settings.workspace),
        workspace_exists=settings.workspace.is_dir(),
        disk_free_bytes=free,
        disk_total_bytes=total,
        packs=[],
    )
