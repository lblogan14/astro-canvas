"""``NodeContext`` implementations for the thread executor and for process workers."""

from __future__ import annotations

import contextlib
import queue
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from astro_canvas.engine.events import EventBus, NodeLog, NodeOutputSummary, NodeProgress

LEVELS = ("debug", "info", "warning", "error")


class EngineContext:
    """Context for nodes running in the server process (thread pool or event loop).

    Progress, logs and previews become events on the bus; cancellation is a ``threading.Event``
    the scheduler sets; lazy ports are resolved through ``resolver`` (blocking the node thread).
    """

    def __init__(
        self,
        *,
        bus: EventBus,
        workflow_id: str,
        node_id: str,
        workspace: Path,
        scratch_dir: Path,
        resolver: Callable[[str], Any] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self._bus = bus
        self._workflow_id = workflow_id
        self._node_id = node_id
        self._workspace = workspace
        self._scratch = scratch_dir
        self._resolver = resolver
        self.cancel_event = cancel_event or threading.Event()

    @property
    def scratch_dir(self) -> Path:
        self._scratch.mkdir(parents=True, exist_ok=True)
        return self._scratch

    @property
    def workspace(self) -> Path:
        return self._workspace

    def progress(self, fraction: float, message: str | None = None) -> None:
        self._bus.publish(
            NodeProgress(
                workflow_id=self._workflow_id,
                node_id=self._node_id,
                frac=min(max(float(fraction), 0.0), 1.0),
                message=message,
            )
        )

    def log(self, level: str, message: str, **fields: Any) -> None:
        self._bus.publish(
            NodeLog(
                workflow_id=self._workflow_id,
                node_id=self._node_id,
                level=level if level in LEVELS else "info",
                message=message,
                fields=dict(fields),
            )
        )

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def needs(self, port: str) -> Any:
        if self._resolver is None:
            raise KeyError(f"lazy input {port!r} cannot be resolved here")
        return self._resolver(port)

    def preview(self, payload: Mapping[str, Any]) -> None:
        self._bus.publish(
            NodeOutputSummary(
                workflow_id=self._workflow_id,
                node_id=self._node_id,
                port="$preview",
                type_id=str(payload.get("type", "preview")),
                summary=dict(payload),
            )
        )


class WorkerContext:
    """Context inside a pebble worker: events go through a manager queue; cancel means kill."""

    def __init__(
        self,
        *,
        node_id: str,
        workspace: Path,
        scratch_dir: Path,
        events: queue.Queue[tuple[str, str, dict[str, Any]]] | None,
        lazy_inputs: Mapping[str, Any],
    ) -> None:
        self._node_id = node_id
        self._workspace = workspace
        self._scratch = scratch_dir
        self._events = events
        self._lazy = dict(lazy_inputs)

    @property
    def scratch_dir(self) -> Path:
        self._scratch.mkdir(parents=True, exist_ok=True)
        return self._scratch

    @property
    def workspace(self) -> Path:
        return self._workspace

    def _emit(self, kind: str, payload: dict[str, Any]) -> None:
        if self._events is not None:
            # The parent may have gone away; never fail the node because of telemetry.
            with contextlib.suppress(Exception):
                self._events.put((kind, self._node_id, payload))

    def progress(self, fraction: float, message: str | None = None) -> None:
        self._emit("progress", {"frac": min(max(float(fraction), 0.0), 1.0), "message": message})

    def log(self, level: str, message: str, **fields: Any) -> None:
        self._emit(
            "log",
            {"level": level if level in LEVELS else "info", "message": message, "fields": fields},
        )

    def is_cancelled(self) -> bool:
        return False

    def needs(self, port: str) -> Any:
        if port not in self._lazy:
            raise KeyError(f"lazy input {port!r} was not provided")
        return self._lazy[port]

    def preview(self, payload: Mapping[str, Any]) -> None:
        self._emit("preview", {"summary": dict(payload)})
