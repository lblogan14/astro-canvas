"""``wrap_outputs`` / ``coerce`` / ``unwrap_linked`` and the in-process ``EngineContext``."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import numpy as np
import pytest
from astro_canvas_core import types as T

from astro_canvas.engine.context import EngineContext
from astro_canvas.engine.events import EventBus
from astro_canvas.engine.outputs import OutputError, coerce, unwrap_linked, wrap_outputs
from astro_canvas.sdk import NodeRegistry
from tests.sdk import sample_nodes


def test_wrap_single_tuple_named_and_none(registry: NodeRegistry) -> None:
    types = registry.types
    const = registry.get("core.math.constant")
    assert wrap_outputs(const, 2.5, types) == {"out": T.Float(value=2.5)}
    assert wrap_outputs(registry.get("core.note.markdown"), None, types) == {}

    swapped = wrap_outputs(sample_nodes.swap, (1.0, 2.0), types)
    assert swapped == {"second": T.Float(value=1.0), "first": T.Float(value=2.0)}
    with pytest.raises(OutputError):
        wrap_outputs(sample_nodes.swap, (1.0,), types)

    spec = T.Spectrum1D(wave=np.arange(4.0), flux=np.ones(4))
    named = wrap_outputs(sample_nodes.split, sample_nodes.split(spec, 2.0), types)
    assert set(named) == {"blue", "red", "pivot"} and named["pivot"] == T.Float(value=2.0)
    assert isinstance(named["blue"], T.Spectrum1D) and len(named["blue"]) == 2


def test_coerce_rules(registry: NodeRegistry) -> None:
    types = registry.types
    spec = T.Spectrum1D(wave=np.arange(2.0), flux=np.ones(2))
    assert coerce(spec, "astro.Spectrum1D", types) is spec
    assert coerce(spec, "astro.SpectrumCollection", types) is spec  # compatible_with
    with pytest.raises(OutputError, match="expected astro.Float"):
        coerce(spec, "astro.Float", types)
    assert coerce({"z": 0.5}, "astro.Redshift", types) == T.Redshift(z=0.5)
    assert coerce([1, 2], "astro.Json", types) == T.Json(value=[1, 2])
    with pytest.raises(OutputError, match="got int"):
        coerce(3, "astro.Redshift", types)
    with pytest.raises(ValueError):  # pydantic validation of the wrapped scalar
        coerce("nope", "astro.Float", types)


def test_unwrap_linked() -> None:
    assert unwrap_linked(T.Float(value=1.0)) == 1.0
    assert unwrap_linked(T.Json(value={"a": 1})) == {"a": 1}
    redshift = T.Redshift(z=1.0)
    assert unwrap_linked(redshift) is redshift


async def test_engine_context_publishes_events(tmp_path: Path) -> None:
    bus = EventBus()
    bus.bind()
    sub = bus.subscribe("w")
    cancel = threading.Event()
    ctx = EngineContext(
        bus=bus,
        workflow_id="w",
        node_id="n",
        workspace=tmp_path,
        scratch_dir=tmp_path / "scratch",
        resolver=lambda port: {"a": 1}[port],
        cancel_event=cancel,
    )
    assert ctx.workspace == tmp_path and ctx.scratch_dir.is_dir()
    ctx.progress(-1.0, "start")
    ctx.log("weird", "msg", n=1)
    ctx.preview({"type": "spectrum-thumb", "wave": [1]})
    await asyncio.sleep(0)
    events = [await sub.next(0.5) for _ in range(3)]
    assert [e.type for e in events] == ["node.progress", "node.log", "node.output.summary"]  # type: ignore[union-attr]
    assert events[0].frac == 0.0 and events[1].level == "info"  # type: ignore[union-attr]
    assert events[2].port == "$preview" and events[2].type_id == "spectrum-thumb"  # type: ignore[union-attr]
    assert ctx.needs("a") == 1
    assert not ctx.is_cancelled()
    cancel.set()
    assert ctx.is_cancelled()
    bare = EngineContext(
        bus=bus, workflow_id="w", node_id="n", workspace=tmp_path, scratch_dir=tmp_path
    )
    with pytest.raises(KeyError):
        bare.needs("x")
