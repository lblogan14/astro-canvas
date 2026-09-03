"""``engine.worker.run_job`` and ``WorkerContext`` exercised in-process."""

from __future__ import annotations

import queue
from pathlib import Path

import pytest
from astro_canvas_core import types as T

from astro_canvas.engine.cache import BlobStore, OutputRef
from astro_canvas.engine.context import WorkerContext
from astro_canvas.engine.worker import WorkerJob, load_registry, rehydrate, run_job
from astro_canvas.sdk import BlobError, NodeRegistry
from tests.engine.conftest import REGISTRY_FACTORY


def _store(tmp_path: Path, value: T.Float) -> tuple[BlobStore, OutputRef]:
    blobs = BlobStore(tmp_path / "blobs")
    data = value.to_blob().pack()
    return blobs, OutputRef("k", "out", value.type_id(), blobs.put(data), len(data), "t")


def test_run_job_rehydrates_inputs_and_writes_outputs(
    tmp_path: Path, registry: NodeRegistry
) -> None:
    blobs, ref = _store(tmp_path, T.Float(value=4.0))
    events: queue.Queue[tuple[str, str, dict[str, object]]] = queue.Queue()
    job = WorkerJob(
        node_id="s",
        node_type="test.progress",
        params={"steps": 2},
        token="run:s",
        input_refs={},
        linked=frozenset(),
        lazy_refs={},
        blob_root=blobs.root,
        workspace=tmp_path,
        scratch_dir=tmp_path / "scratch" / "s",
        registry_factory=REGISTRY_FACTORY,
    )
    result = run_job(job, events)
    assert set(result.refs) == {"out"} and result.refs["out"].type_id == "astro.Int"
    loaded = rehydrate({"out": result.refs["out"]}, blobs, registry)
    assert loaded["out"].value == 2  # type: ignore[attr-defined]
    kinds = [events.get_nowait() for _ in range(events.qsize())]
    assert [k[0] for k in kinds] == ["progress", "progress", "log"]
    assert kinds[0][1] == "run:s" and kinds[-1][2]["fields"] == {"steps": 2}
    assert (tmp_path / "scratch" / "s" / "note.txt").read_text(encoding="utf-8") == "hi"
    assert result.elapsed_ms >= 0

    linked = WorkerJob(
        node_id="e",
        node_type="core.math.expr",
        params={"expression": "x * 2"},
        token="run:e",
        input_refs={"x": ref},
        linked=frozenset({"x"}),
        lazy_refs={},
        blob_root=blobs.root,
        workspace=tmp_path,
        scratch_dir=tmp_path / "scratch" / "e",
        registry_factory=REGISTRY_FACTORY,
    )
    out = rehydrate(run_job(linked).refs, blobs, registry)
    assert out["out"].value == 8.0  # type: ignore[attr-defined]


def test_run_job_lazy_and_inline_inputs(tmp_path: Path, registry: NodeRegistry) -> None:
    blobs, ref = _store(tmp_path, T.Float(value=9.0))
    job = WorkerJob(
        node_id="sw",
        node_type="test.switch",
        params={"pick": "b"},
        token="t",
        input_refs={},
        linked=frozenset(),
        lazy_refs={"a": ref, "b": ref},
        blob_root=blobs.root,
        workspace=tmp_path,
        scratch_dir=tmp_path / "scratch",
        registry_factory=REGISTRY_FACTORY,
        inline_inputs={},
    )
    out = rehydrate(run_job(job).refs, blobs, registry)
    assert out["out"].value == 9.0  # type: ignore[attr-defined]
    inline = WorkerJob(
        node_id="e",
        node_type="core.math.expr",
        params={"expression": "x + y"},
        token="t2",
        input_refs={},
        linked=frozenset({"x"}),
        lazy_refs={},
        blob_root=blobs.root,
        workspace=tmp_path,
        scratch_dir=tmp_path / "scratch",
        registry_factory=REGISTRY_FACTORY,
        inline_inputs={"x": 1.5, "y": 2.0},
    )
    with pytest.raises(TypeError):  # ``y`` is a param, not an input: unknown input rejected
        run_job(inline)


def test_run_job_rejects_unserialisable_outputs(tmp_path: Path) -> None:
    blobs = BlobStore(tmp_path / "blobs")
    job = WorkerJob(
        node_id="a",
        node_type="test.any.make",
        params={},
        token="t",
        input_refs={},
        linked=frozenset(),
        lazy_refs={},
        blob_root=blobs.root,
        workspace=tmp_path,
        scratch_dir=tmp_path / "scratch",
        registry_factory=REGISTRY_FACTORY,
    )
    with pytest.raises(BlobError):
        run_job(job)


def test_registry_factory_is_cached() -> None:
    assert load_registry(REGISTRY_FACTORY) is load_registry(REGISTRY_FACTORY)
    assert "test.sleep" in load_registry(REGISTRY_FACTORY)


def test_worker_context_without_queue(tmp_path: Path) -> None:
    ctx = WorkerContext(
        node_id="n", workspace=tmp_path, scratch_dir=tmp_path / "s", events=None, lazy_inputs={}
    )
    ctx.progress(2.0, "over")  # clamped, no queue: no error
    ctx.log("bogus-level", "hello")
    ctx.preview({"type": "x"})
    assert ctx.is_cancelled() is False and ctx.workspace == tmp_path
    assert ctx.scratch_dir.is_dir()
    with pytest.raises(KeyError):
        ctx.needs("missing")

    class Broken:
        def put(self, _item: object) -> None:
            raise OSError("pipe closed")

    silent = WorkerContext(
        node_id="n",
        workspace=tmp_path,
        scratch_dir=tmp_path,
        events=Broken(),
        lazy_inputs={},  # type: ignore[arg-type]
    )
    silent.progress(0.5)  # swallowed
