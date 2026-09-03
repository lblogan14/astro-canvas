"""``NodeContext``: the side-effect channel handed to node functions."""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class NodeContext(Protocol):
    """Runtime services available to a node while it executes.

    A node declares ``ctx: NodeContext | None = None`` to receive one. Nodes must stay pure with
    respect to their inputs; every side effect (progress, logging, previews, scratch files) goes
    through this object so the engine can record, stream, and cancel it.
    """

    @property
    def scratch_dir(self) -> Path:
        """Per-run temporary directory, deleted after the run."""
        ...

    @property
    def workspace(self) -> Path:
        """Root of the user's workspace folder."""
        ...

    def progress(self, fraction: float, message: str | None = None) -> None:
        """Report progress in ``[0, 1]`` with an optional status message."""
        ...

    def log(self, level: str, message: str, **fields: Any) -> None:
        """Emit a structured log line (``debug``/``info``/``warning``/``error``)."""
        ...

    def is_cancelled(self) -> bool:
        """Return ``True`` when the run was cancelled; long loops should poll this."""
        ...

    def needs(self, port: str) -> Any:
        """Resolve a lazy input port on demand (see ``@node(lazy=...)``)."""
        ...

    def preview(self, payload: Mapping[str, Any]) -> None:
        """Push an intermediate preview payload to the node's inline view."""
        ...


@dataclass
class NullContext:
    """Minimal ``NodeContext`` for direct calls and tests: records everything, cancels nothing."""

    workspace: Path = field(default_factory=Path.cwd)
    inputs: dict[str, Any] = field(default_factory=dict)
    cancelled: bool = False
    progress_events: list[tuple[float, str | None]] = field(default_factory=list)
    logs: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    previews: list[dict[str, Any]] = field(default_factory=list)
    _scratch: Path | None = field(default=None, repr=False)

    @property
    def scratch_dir(self) -> Path:
        if self._scratch is None:
            self._scratch = Path(tempfile.mkdtemp(prefix="astro-canvas-"))
        return self._scratch

    def progress(self, fraction: float, message: str | None = None) -> None:
        self.progress_events.append((min(max(fraction, 0.0), 1.0), message))

    def log(self, level: str, message: str, **fields: Any) -> None:
        self.logs.append((level, message, dict(fields)))

    def is_cancelled(self) -> bool:
        return self.cancelled

    def needs(self, port: str) -> Any:
        if port not in self.inputs:
            raise KeyError(f"lazy input {port!r} was not provided")
        return self.inputs[port]

    def preview(self, payload: Mapping[str, Any]) -> None:
        self.previews.append(dict(payload))
