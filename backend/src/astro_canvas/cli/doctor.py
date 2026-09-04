"""``astro-canvas doctor``: is this installation able to run?

The point of this command is to answer a support email in one paste. It reports the interpreter,
the ``uv`` the pack manager will use, the packs that loaded (and the traceback of any that did
not), free disk, whether the port is free, whether the SPA is bundled, and -- because the whole
rbcodes port depends on it -- whether importing every pack pulled Qt into the process.

Nothing here re-derives what the server already knows: ``uv_status`` and ``installed`` are the
same calls ``/api/manager/status`` makes.
"""

from __future__ import annotations

import platform
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import typer

from astro_canvas._version import __version__
from astro_canvas.cli.context import open_app
from astro_canvas.settings import get_settings

Status = Literal["ok", "warn", "fail"]

MIN_FREE_GB = 5.0
QT_MODULES = ("PyQt5", "PyQt6", "PySide2", "PySide6")
MARK: dict[Status, str] = {"ok": "ok  ", "warn": "warn", "fail": "FAIL"}
COLOUR: dict[Status, str] = {
    "ok": typer.colors.GREEN,
    "warn": typer.colors.YELLOW,
    "fail": typer.colors.RED,
}


@dataclass(frozen=True)
class Check:
    """One line of the report."""

    name: str
    status: Status
    detail: str = ""


def port_free(host: str, port: int) -> bool:
    """Whether ``host:port`` can be bound right now."""
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def python_check() -> Check:
    """3.10 works; 3.12 is what the launcher installs and what the packs are tested on."""
    version = platform.python_version()
    detail = f"{version} ({sys.executable})"
    # The wheel's ``requires-python`` already rules out anything below 3.10.
    if sys.version_info < (3, 12):
        return Check("python", "warn", f"{detail} -- 3.12 is the recommended version")
    return Check("python", "ok", detail)


def qt_check() -> Check:
    """Qt must not be imported: it is what makes the rbcodes port headless-safe (design 8.5)."""
    loaded = [name for name in QT_MODULES if name in sys.modules]
    if loaded:
        return Check(
            "qt not imported",
            "fail",
            f"{', '.join(loaded)} was imported by a pack; it must be imported lazily "
            "inside the node function (see docs/dev/rbcodes-compat.md)",
        )
    return Check("qt not imported", "ok", "no Qt binding in sys.modules")


def static_check() -> Check:
    """A wheel built without the SPA serves an API and a blank page; say so plainly."""
    static = Path(__file__).resolve().parents[1] / "static"
    index = static / "index.html"
    if index.is_file():
        files = sum(1 for p in static.rglob("*") if p.is_file())
        return Check("bundled interface", "ok", f"{files} files, index.html {index.stat().st_size} B")
    return Check(
        "bundled interface",
        "warn",
        "no built interface in this install -- run `task build`, or use the published wheel",
    )


def disk_check(workspace: Path) -> Check:
    """Cubes are big; a workspace with no room is the most common real failure."""
    probe = workspace
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    free_gb = usage.free / 1024**3
    detail = f"{free_gb:.1f} GB free of {usage.total / 1024**3:.1f} GB on {probe}"
    return Check("disk", "ok" if free_gb >= MIN_FREE_GB else "warn", detail)


def report(workspace: Path | None = None) -> list[Check]:
    """Run every check and return the report."""
    settings = get_settings(workspace=workspace)
    checks = [
        Check("astro-canvas", "ok", f"{__version__} on {platform.platform()}"),
        python_check(),
        static_check(),
    ]
    with open_app(workspace) as ctx:
        path, version = (None, "") if ctx.manager is None else ctx.manager.uv_status()
        checks.append(
            Check("uv", "ok", f"{version} at {path}")
            if path
            else Check("uv", "fail", version or "the pack manager is unavailable")
        )
        checks.append(
            Check(
                "workspace",
                "ok" if ctx.runtime.workspace.root.is_dir() else "fail",
                str(ctx.runtime.workspace.root),
            )
        )
        checks.append(disk_check(ctx.runtime.workspace.root))
        packs = ctx.manager.installed() if ctx.manager is not None else []
        for pack in packs:
            if pack.error:
                checks.append(Check(f"pack {pack.name}", "fail", pack.error))
            elif not pack.enabled:
                checks.append(Check(f"pack {pack.name}", "warn", f"{pack.version} (disabled)"))
            else:
                checks.append(
                    Check(
                        f"pack {pack.name}",
                        "ok",
                        f"{pack.version}, {pack.node_count} nodes, {pack.type_count} types",
                    )
                )
        if not packs:
            checks.append(Check("packs", "warn", "no node packs are installed"))
        checks.append(qt_check())
    free = port_free(settings.host, settings.port)
    checks.append(
        Check("port", "ok" if free else "warn", f"{settings.host}:{settings.port}")
        if free
        else Check(
            "port",
            "warn",
            f"{settings.host}:{settings.port} is in use -- Astro Canvas may already be running",
        )
    )
    return checks


def doctor(
    workspace: Annotated[Path | None, typer.Option(help="Workspace folder to check.")] = None,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print pack load tracebacks in full.")
    ] = False,
) -> None:
    """Check this installation and print a report; exits non-zero if anything failed."""
    checks = report(workspace)
    for check in checks:
        typer.secho(f"[{MARK[check.status]}] ", fg=COLOUR[check.status], nl=False)
        typer.echo(f"{check.name:<24} {check.detail}")
    failed = [c for c in checks if c.status == "fail"]
    if verbose:
        with open_app(workspace) as ctx:
            for pack in ctx.manager.installed() if ctx.manager is not None else []:
                if pack.traceback:
                    typer.echo(f"\n--- {pack.name} ---\n{pack.traceback}")
    if failed:
        typer.secho(f"\n{len(failed)} check(s) failed", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    typer.secho("\nall checks passed", fg=typer.colors.GREEN)


__all__ = ["Check", "doctor", "port_free", "report"]
