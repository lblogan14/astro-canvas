"""Typed engine events, the in-process ``EventBus`` and the binary frame codec (design 6.4).

Text events are pydantic models discriminated by ``type``; the WebSocket layer serialises them
as JSON. Binary frames carry full arrays: ``u32 msg_type | u32 header_len | msgpack header |
raw buffers`` (little-endian header words).
"""

from __future__ import annotations

import asyncio
import struct
import threading
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Annotated, Any, Literal, Union

import msgpack
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from astro_canvas.sdk import Cost, PortType
from astro_canvas.sdk.blob import split_binary, to_manifest_data

NodeState = Literal["idle", "dirty", "queued", "running", "done", "error", "cancelled"]
RunStatus = Literal["running", "done", "error", "cancelled"]

FRAME_OUTPUT = 1
"""Binary frame type: one node output's arrays."""

BROADCAST = "*"
"""``workflow_id`` of events delivered to every subscriber (``workspace.changed`` etc.)."""

_HEADER = struct.Struct("<II")


class NodeIssue(BaseModel):
    """One compile-time problem on a node (returned per node like ComfyUI's ``node_errors``)."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    port: str | None = None
    param: str | None = None


class _Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: float = Field(default_factory=time.time)
    workflow_id: str


class RunStarted(_Event):
    type: Literal["run.started"] = "run.started"
    run_id: str
    targets: list[str] | None = None
    n_nodes: int = 0
    cached: int = 0


class RunFinished(_Event):
    type: Literal["run.finished"] = "run.finished"
    run_id: str
    targets: list[str] | None = None
    n_nodes: int = 0
    cached: int = 0
    status: RunStatus = "done"
    elapsed_ms: float = 0.0


class NodeStatus(_Event):
    type: Literal["node.status"] = "node.status"
    node_id: str
    state: NodeState
    run_id: str | None = None
    cache_hit: bool = False
    elapsed_ms: float | None = None
    cost_class: Cost = "cheap"
    stale: bool = False


class NodeProgress(_Event):
    type: Literal["node.progress"] = "node.progress"
    node_id: str
    frac: float
    message: str | None = None


class NodeLog(_Event):
    type: Literal["node.log"] = "node.log"
    node_id: str
    level: str
    message: str
    fields: dict[str, Any] = Field(default_factory=dict)


class NodeErrorEvent(_Event):
    type: Literal["node.error"] = "node.error"
    node_id: str
    message: str
    traceback: str = ""
    hint: str | None = None


class NodeOutputSummary(_Event):
    type: Literal["node.output.summary"] = "node.output.summary"
    node_id: str
    port: str
    type_id: str
    summary: dict[str, Any]


class GraphValidation(_Event):
    type: Literal["graph.validation"] = "graph.validation"
    node_errors: dict[str, list[NodeIssue]] = Field(default_factory=dict)


class WorkspaceChanged(_Event):
    type: Literal["workspace.changed"] = "workspace.changed"
    paths: list[str] = Field(default_factory=list)


class PacksChanged(_Event):
    type: Literal["packs.changed"] = "packs.changed"
    event: str


Event = Annotated[
    Union[  # noqa: UP007 - explicit Union keeps the discriminator readable
        RunStarted,
        RunFinished,
        NodeStatus,
        NodeProgress,
        NodeLog,
        NodeErrorEvent,
        NodeOutputSummary,
        GraphValidation,
        WorkspaceChanged,
        PacksChanged,
    ],
    Field(discriminator="type"),
]


class Subscription:
    """An async iterator over events, created by ``EventBus.subscribe``."""

    def __init__(self, bus: EventBus, workflow_id: str | None, maxsize: int) -> None:
        self._bus = bus
        self.workflow_id = workflow_id
        self.queue: asyncio.Queue[_Event | None] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def accepts(self, event: _Event) -> bool:
        return self.workflow_id is None or event.workflow_id in (self.workflow_id, BROADCAST)

    def _offer(self, event: _Event | None) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            self.dropped += 1

    def close(self) -> None:
        self._bus.unsubscribe(self)
        self._offer(None)

    def __aiter__(self) -> AsyncIterator[_Event]:
        return self

    async def __anext__(self) -> _Event:
        event = await self.queue.get()
        if event is None:
            raise StopAsyncIteration
        return event

    async def next(self, timeout: float | None = None) -> _Event | None:
        """Next event or ``None`` on timeout / close."""
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except TimeoutError:
            return None


class EventBus:
    """Fan-out of engine events to async subscribers; ``publish`` is thread-safe."""

    def __init__(self) -> None:
        self._subs: set[Subscription] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()
        self.history: list[_Event] = []
        self.keep_history = 0

    def bind(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """Attach to the event loop that owns the subscribers (defaults to the running loop)."""
        self._loop = loop or asyncio.get_running_loop()

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    def subscribe(self, workflow_id: str | None = None, *, maxsize: int = 4096) -> Subscription:
        if self._loop is None:
            self.bind()
        sub = Subscription(self, workflow_id, maxsize)
        with self._lock:
            self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            self._subs.discard(sub)

    def publish(self, event: _Event) -> None:
        """Deliver ``event`` to matching subscribers from any thread."""
        if self.keep_history:
            self.history.append(event)
            del self.history[: -self.keep_history]
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            in_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            in_loop = False
        if in_loop:
            self._deliver(event)
        else:
            loop.call_soon_threadsafe(self._deliver, event)

    def _deliver(self, event: _Event) -> None:
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            if sub.accepts(event):
                sub._offer(event)


def encode_frame(msg_type: int, header: Mapping[str, Any], buffers: Sequence[bytes]) -> bytes:
    """Build a binary frame: ``u32 type, u32 header_len, msgpack(header), *buffers``."""
    packed = msgpack.packb(dict(header), use_bin_type=True)
    return b"".join([_HEADER.pack(msg_type, len(packed)), packed, *buffers])


def decode_frame(data: bytes) -> tuple[int, dict[str, Any], bytes]:
    """Inverse of ``encode_frame``: ``(msg_type, header, payload)``."""
    if len(data) < _HEADER.size:
        raise ValueError("frame too short")
    msg_type, header_len = _HEADER.unpack_from(data)
    end = _HEADER.size + header_len
    header = msgpack.unpackb(data[_HEADER.size : end], raw=False)
    if not isinstance(header, dict):
        raise ValueError("frame header must be a map")
    return msg_type, header, data[end:]


def output_frame(node_id: str, port: str, value: PortType) -> bytes:
    """Encode a port value's arrays as one ``FRAME_OUTPUT`` frame.

    The header carries ``node_id, port, type_id, data`` (the JSON-safe remainder of the value)
    and ``arrays: [{name, dtype, shape, offset, nbytes}]`` describing consecutive C-contiguous
    little-endian buffers in the payload.
    """
    data, arrays, binaries = split_binary(value.model_dump(mode="python"))
    descriptors: list[dict[str, Any]] = []
    buffers: list[bytes] = []
    offset = 0
    for name in sorted(arrays):
        arr = np.ascontiguousarray(arrays[name])
        if arr.dtype.byteorder == ">":
            arr = arr.astype(arr.dtype.newbyteorder("<"))
        raw = arr.tobytes()
        descriptors.append(
            {
                "name": name,
                "dtype": arr.dtype.str.lstrip("<=|"),
                "shape": list(arr.shape),
                "offset": offset,
                "nbytes": len(raw),
            }
        )
        buffers.append(raw)
        offset += len(raw)
    for name in sorted(binaries):
        raw = binaries[name]
        descriptors.append(
            {
                "name": name,
                "dtype": "bytes",
                "shape": [len(raw)],
                "offset": offset,
                "nbytes": len(raw),
            }
        )
        buffers.append(raw)
        offset += len(raw)
    header = {
        "node_id": node_id,
        "port": port,
        "type_id": value.type_id(),
        "data": to_manifest_data(data),
        "arrays": descriptors,
    }
    return encode_frame(FRAME_OUTPUT, header, buffers)
