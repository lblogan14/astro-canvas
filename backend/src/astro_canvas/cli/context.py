"""Building the engine and the pack manager without a server, for the offline subcommands.

``pack``, ``bundle`` and ``doctor`` need exactly what ``create_app`` builds -- a discovered
registry, an ``EngineRuntime`` on a workspace, and a ``PackManager`` wired to both -- and nothing
else it builds. ``open_app`` is that subset, and it reuses ``server.app.build_manager`` rather
than repeating the wiring, so a CLI install behaves like the one in the app.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import typer

from astro_canvas.logging import configure_logging
from astro_canvas.manager.packs import PackManager
from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.runtime import EngineRuntime
from astro_canvas.settings import Settings, get_settings


@dataclass(frozen=True)
class CliContext:
    """One command's view of the installation."""

    settings: Settings
    discovery: DiscoveryResult
    runtime: EngineRuntime
    manager: PackManager | None

    @property
    def packs(self) -> PackManager:
        """The pack manager, or a clean exit explaining why there is none."""
        if self.manager is None:
            typer.secho(
                "the pack manager is unavailable for this workspace", fg=typer.colors.RED, err=True
            )
            raise typer.Exit(code=1)
        return self.manager


def cli_settings(workspace: Path | None = None, **overrides: object) -> Settings:
    """Settings for a short-lived command: no auth, no watcher, no process pool."""
    return get_settings(
        workspace=workspace,
        auth="none",
        watch_workspace=False,
        process_pool=False,
        **overrides,
    )


@contextmanager
def open_app(
    workspace: Path | None = None, *, manager: bool = True, log_level: str = "warning"
) -> Iterator[CliContext]:
    """Open the workspace, discover packs and yield the pieces; always shuts the engine down."""
    from astro_canvas.sdk import discover  # noqa: PLC0415 - importing packs is the slow part
    from astro_canvas.server.app import build_manager  # noqa: PLC0415 - same

    settings = cli_settings(workspace)
    configure_logging(log_level)
    discovery = discover()
    runtime = EngineRuntime(settings, discovery.registry)
    try:
        packs = build_manager(settings, runtime, discovery) if manager else None
        yield CliContext(settings=settings, discovery=discovery, runtime=runtime, manager=packs)
    finally:
        asyncio.run(runtime.shutdown())


__all__ = ["CliContext", "cli_settings", "open_app"]
