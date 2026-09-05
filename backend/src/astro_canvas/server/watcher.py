"""Workspace file watcher: ``watchfiles`` changes become broadcast ``workspace.changed`` events."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import structlog
from watchfiles import Change, awatch

from astro_canvas.engine.events import BROADCAST, EventBus, WorkspaceChanged
from astro_canvas.store.workspace import STATE_DIR

log = structlog.get_logger("astro_canvas.workspace")


class WorkspaceWatcher:
    """Watch ``root`` recursively (ignoring ``.astro-canvas``) and publish changed paths.

    Granularity is the operating system's. inotify and the Windows backend report the file, so
    ``paths`` names it; macOS watches through FSEvents, which reports the *directory*, so a change
    can arrive as its containing folder — the workspace root itself included, as ``"."``. Both are
    correct answers to "something changed under here", which is all a client needs to refresh a
    listing. The one consequence worth knowing is that a directory-granular event cannot be
    filtered by `_filter`: a write inside ``.astro-canvas`` can surface as its parent, so on macOS
    the app's own state writes may cost a tree refresh.
    """

    def __init__(self, bus: EventBus, root: Path, *, debounce_ms: int = 300) -> None:
        self.bus = bus
        self.root = Path(root).resolve()
        self.debounce_ms = debounce_ms
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None
        self.events_published = 0

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._stop = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name=f"workspace-watch:{self.root}")

    async def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(self._task, timeout=5.0)
            self._task = None
        self._stop = None

    def _filter(self, _change: Change, path: str) -> bool:
        try:
            parts = Path(path).resolve().relative_to(self.root).parts
        except ValueError:
            return False
        return STATE_DIR not in parts

    def _relative(self, path: str) -> str:
        try:
            return Path(path).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return Path(path).name

    async def _run(self) -> None:
        assert self._stop is not None
        try:
            async for changes in awatch(
                self.root,
                watch_filter=self._filter,
                debounce=self.debounce_ms,
                step=50,
                stop_event=self._stop,
                recursive=True,
            ):
                paths = sorted({self._relative(path) for _, path in changes})
                if not paths:
                    continue
                self.events_published += 1
                self.bus.publish(WorkspaceChanged(workflow_id=BROADCAST, paths=paths))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a broken watcher must not take the server down
            log.warning("workspace watcher stopped", root=str(self.root), error=str(exc))
