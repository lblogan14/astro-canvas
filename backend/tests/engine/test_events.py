"""Event models, the thread-safe ``EventBus`` and the binary frame codec."""

from __future__ import annotations

import asyncio
import threading

import numpy as np
import pytest
from astro_canvas_core import types as T
from pydantic import TypeAdapter

from astro_canvas.engine.events import (
    BROADCAST,
    FRAME_OUTPUT,
    Event,
    EventBus,
    NodeProgress,
    NodeStatus,
    RunStarted,
    WorkspaceChanged,
    decode_frame,
    encode_frame,
    output_frame,
)


def test_events_are_discriminated_by_type() -> None:
    adapter: TypeAdapter[object] = TypeAdapter(Event)
    raw = {"type": "node.status", "workflow_id": "w", "node_id": "n", "state": "done", "ts": 1.0}
    event = adapter.validate_python(raw)
    assert isinstance(event, NodeStatus) and event.cache_hit is False
    with pytest.raises(ValueError):
        adapter.validate_python({"type": "nope", "workflow_id": "w"})
    assert RunStarted(workflow_id="w", run_id="r").model_dump(mode="json")["type"] == "run.started"


async def test_bus_filters_by_workflow_and_accepts_threads() -> None:
    bus = EventBus()
    bus.bind()
    all_events = bus.subscribe()
    only_w2 = bus.subscribe("w2", maxsize=2)
    bus.publish(NodeProgress(workflow_id="w1", node_id="a", frac=0.1))

    def from_thread() -> None:
        for i in range(4):
            bus.publish(NodeProgress(workflow_id="w2", node_id="b", frac=i / 4))

    thread = threading.Thread(target=from_thread)
    thread.start()
    thread.join()
    await asyncio.sleep(0.05)
    assert all_events.queue.qsize() == 5
    assert only_w2.queue.qsize() == 2 and only_w2.dropped == 2  # bounded queue drops extras
    first = await only_w2.next(timeout=1)
    assert isinstance(first, NodeProgress) and first.workflow_id == "w2"
    assert isinstance(await only_w2.next(timeout=1), NodeProgress)
    only_w2.close()
    assert await only_w2.next(timeout=0.2) is None  # the close sentinel
    all_events.close()
    drained = [e async for e in all_events]  # everything queued before the sentinel
    assert len(drained) == 5 and drained[0].workflow_id == "w1"
    bus.publish(NodeProgress(workflow_id="w1", node_id="a", frac=0.5))  # no subscribers left
    assert all_events.queue.qsize() == 0


async def test_broadcast_events_reach_every_subscriber() -> None:
    bus = EventBus()
    bus.bind()
    only_w1 = bus.subscribe("w1")
    bus.publish(WorkspaceChanged(workflow_id=BROADCAST, paths=["a.fits"]))
    bus.publish(WorkspaceChanged(workflow_id="w2", paths=["b.fits"]))
    await asyncio.sleep(0)
    assert only_w1.queue.qsize() == 1
    event = await only_w1.next(timeout=1)
    assert isinstance(event, WorkspaceChanged) and event.paths == ["a.fits"]
    only_w1.close()


def test_publish_without_loop_is_a_noop() -> None:
    bus = EventBus()
    bus.keep_history = 2
    for i in range(3):
        bus.publish(NodeProgress(workflow_id="w", node_id="n", frac=i))
    assert [e.frac for e in bus.history] == [1.0, 2.0]  # type: ignore[attr-defined]


def test_frame_round_trip() -> None:
    frame = encode_frame(7, {"a": 1, "name": "x"}, [b"\x00\x01", b"\x02"])
    msg_type, header, payload = decode_frame(frame)
    assert (msg_type, header, payload) == (7, {"a": 1, "name": "x"}, b"\x00\x01\x02")
    assert frame[:4] == (7).to_bytes(4, "little")
    with pytest.raises(ValueError):
        decode_frame(b"\x00")


def test_output_frame_carries_typed_buffers() -> None:
    wave = np.linspace(1.0, 2.0, 1_000_000)
    spec = T.Spectrum1D(wave=wave, flux=np.ones_like(wave, dtype=np.float32), z=0.1)
    frame = output_frame("n1", "out", spec)
    msg_type, header, payload = decode_frame(frame)
    assert msg_type == FRAME_OUTPUT
    assert header["node_id"] == "n1" and header["port"] == "out"
    assert header["type_id"] == "astro.Spectrum1D" and header["data"]["z"] == 0.1
    arrays = {a["name"]: a for a in header["arrays"]}
    assert arrays["wave"]["dtype"] == "f8" and arrays["wave"]["shape"] == [1_000_000]
    assert arrays["flux"]["dtype"] == "f8"  # Float1D coerces to float64
    view = np.frombuffer(payload, dtype="<f8", count=1_000_000, offset=arrays["wave"]["offset"])
    assert np.array_equal(view, wave)
    assert len(payload) == arrays["wave"]["nbytes"] + arrays["flux"]["nbytes"]


def test_output_frame_includes_bytes_parts() -> None:
    fig = T.Figure(kind="png", png=b"\x89PNG")
    _, header, payload = decode_frame(output_frame("n", "fig", fig))
    assert header["arrays"] == [
        {"name": "png", "dtype": "bytes", "shape": [4], "offset": 0, "nbytes": 4}
    ]
    assert payload == b"\x89PNG"
