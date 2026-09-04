"""The batch runner: per-row binding, cache reuse, continue-on-error, events and cancellation."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from astro_canvas.engine.batch import (
    BatchBinding,
    BatchCollect,
    BatchRunner,
    BatchSpec,
    bind_row,
    coerce_cell,
    spec_from_layout,
)
from astro_canvas.engine.scheduler import SchedulerConfig
from tests.engine.conftest import Harness, make_doc, wait_for

REGISTRY_FACTORY = "tests.engine.nodes:build_registry"


def pipeline() -> Any:
    """``value -> x + y`` where ``value`` and ``y`` are the batch-bound params."""
    return make_doc(
        {
            "src": {"type": "core.math.constant", "params": {"value": 1.0}},
            "add": {
                "type": "core.math.expr",
                "params": {"expression": "x + y", "y": 0.0},
                "linked": ["x"],
            },
        },
        {"e1": {"from": ["src", "out"], "to": ["add", "x"]}},
        promoted=[{"node": "src", "param": "value"}, {"node": "add", "param": "y"}],
        layouts={
            "batch": {
                "columns": [{"promoted": "src.value", "column": "x0"}, "add.y"],
                "collect": ["add.out"],
            }
        },
    )


def runner(harness: Harness) -> BatchRunner:
    return BatchRunner(
        registry=harness.registry,
        cache=harness.cache,
        bus=harness.bus,
        workspace_root=harness.workspace.root,
        scratch_root=harness.workspace.scratch_dir,
        threads=harness.threads,
        processes=harness.processes,
        config=lambda: SchedulerConfig(debounce_s=0.01, registry_factory=REGISTRY_FACTORY),
    )


def test_spec_from_layout_reads_both_column_forms() -> None:
    spec = spec_from_layout(pipeline().layouts["batch"])
    assert [(b.node, b.param, b.column) for b in spec.bindings] == [
        ("src", "value", "x0"),
        ("add", "y", "add.y"),
    ]
    assert [c.ref for c in spec.collect] == ["add.out"]
    assert spec.continue_on_error is True


def test_bind_row_writes_params_and_unlinks_bound_ports() -> None:
    doc = pipeline()
    spec = BatchSpec(bindings=[BatchBinding(node="add", param="x", column="x")])
    variant = bind_row(doc, spec, {"x": 4.0})
    assert variant.nodes["add"].params["x"] == 4.0
    assert variant.nodes["add"].linked == []
    assert doc.nodes["add"].linked == ["x"]  # the source document is untouched


def test_text_cells_widen_to_the_param_type(harness: Harness) -> None:
    registry = harness.registry
    assert coerce_cell(registry, "core.math.constant", "value", "1.5") == 1.5
    assert coerce_cell(registry, "core.math.expr", "expression", "x + 1") == "x + 1"
    assert coerce_cell(registry, "core.math.constant", "value", 2.0) == 2.0
    # Unknown nodes, unknown params and unconvertible text pass straight through.
    assert coerce_cell(registry, "nope.node", "value", "1.5") == "1.5"
    assert coerce_cell(registry, "core.math.constant", "ghost", "1.5") == "1.5"
    assert coerce_cell(registry, "core.math.constant", "value", "many") == "many"


async def test_a_csv_row_of_strings_runs(harness: Harness) -> None:
    doc = pipeline()
    spec = spec_from_layout(doc.layouts["batch"])
    run = await runner(harness).execute(doc, [{"x0": "2", "add.y": "3.5"}], spec)
    assert run.status == "done"
    assert run.results().rows[0]["value"] == 5.5


async def test_every_row_runs_with_its_own_params_and_results(harness: Harness) -> None:
    doc = pipeline()
    spec = spec_from_layout(doc.layouts["batch"])
    rows = [{"x0": float(i), "add.y": 10.0} for i in range(20)]
    run = await runner(harness).execute(doc, rows, spec)

    assert run.status == "done"
    assert run.counts() == {"done": 20}
    results = run.results()
    assert results.columns[:3] == ["x0", "add.y", "value"]
    assert [row["value"] for row in results.rows] == [float(i) + 10.0 for i in range(20)]
    assert {row["status"] for row in results.rows} == {"done"}
    assert all(row["calculation_timestamp"] for row in results.rows)


async def test_a_bad_row_errors_without_stopping_the_others(harness: Harness) -> None:
    doc = pipeline()
    spec = spec_from_layout(doc.layouts["batch"])
    rows: list[dict[str, Any]] = [{"x0": float(i), "add.y": 1.0} for i in range(4)]
    rows[2]["add.y"] = "not a number"
    run = await runner(harness).execute(doc, rows, spec)

    assert run.status == "error"
    assert run.counts() == {"done": 3, "error": 1}
    assert run.records[2].error is not None and "add" in run.records[2].error
    results = run.results()
    assert results.rows[2]["status"] == "error" and results.rows[2]["error_message"]
    assert results.rows[3]["value"] == 4.0


async def test_continue_on_error_false_aborts_the_rest(harness: Harness) -> None:
    doc = pipeline()
    spec = spec_from_layout(doc.layouts["batch"]).model_copy(
        update={"continue_on_error": False, "max_workers": 1}
    )
    rows: list[dict[str, Any]] = [{"x0": float(i), "add.y": 1.0} for i in range(4)]
    rows[1]["add.y"] = "boom"
    run = await runner(harness).execute(doc, rows, spec)
    assert run.status == "cancelled"
    assert [r.state for r in run.records] == ["done", "error", "cancelled", "cancelled"]


async def test_repeating_a_row_is_a_pure_cache_hit(harness: Harness) -> None:
    doc = pipeline()
    spec = spec_from_layout(doc.layouts["batch"])
    rows = [{"x0": 2.0, "add.y": 3.0}]
    batch = runner(harness)
    first = await batch.execute(doc, rows, spec)
    assert first.results().rows[0]["value"] == 5.0
    stored = len(harness.cache.memory)
    second = await batch.execute(doc, rows, spec)
    assert second.results().rows[0]["value"] == 5.0
    assert len(harness.cache.memory) == stored  # nothing new was computed


async def test_rows_publish_batch_events(harness: Harness) -> None:
    doc = pipeline()
    spec = spec_from_layout(doc.layouts["batch"])
    run = await runner(harness).execute(doc, [{"x0": 1.0, "add.y": 1.0}], spec)

    started = harness.events("batch.started")
    assert started[0].n_rows == 1 and started[0].batch_id == run.batch_id
    states = [e.state for e in harness.events("batch.row")]
    assert states == ["running", "done"]
    finished = harness.events("batch.finished")[0]
    assert finished.status == "done" and finished.done == 1
    # Node chatter from the row schedulers stays off the shared bus.
    assert harness.events("node.status", "add") == []


async def test_cancel_stops_queued_rows_and_running_nodes(harness: Harness) -> None:
    doc = make_doc(
        {"slow": {"type": "test.sleep", "params": {"seconds": 30.0, "x": 0.0}}},
        {},
        layouts={"batch": {"columns": ["slow.x"], "collect": ["slow.out"]}},
    )
    spec = spec_from_layout(doc.layouts["batch"]).model_copy(update={"max_workers": 2})
    batch = runner(harness)
    rows = [{"slow.x": float(i)} for i in range(6)]
    run = batch.start(doc, rows, spec)

    await wait_for(lambda: sum(r.state == "running" for r in run.records) == 2)
    assert batch.cancel(run.batch_id)
    await asyncio.wait_for(batch._tasks[run.batch_id], timeout=10)

    assert run.status == "cancelled"
    assert all(r.state == "cancelled" for r in run.records[2:])
    assert not any(r.state == "done" for r in run.records)


async def test_a_batch_over_more_than_the_row_cap_is_refused(harness: Harness) -> None:
    doc = pipeline()
    with pytest.raises(ValueError, match="limited to"):
        await runner(harness).execute(
            doc, [{"x0": 1.0}] * 5001, BatchSpec(collect=[BatchCollect(node="add", port="out")])
        )


async def test_a_collected_column_clashing_with_an_input_is_qualified(harness: Harness) -> None:
    doc = pipeline()
    spec = spec_from_layout(doc.layouts["batch"]).model_copy(
        update={"bindings": [BatchBinding(node="src", param="value", column="value")]}
    )
    run = await runner(harness).execute(doc, [{"value": 3.0}], spec)
    row = run.results().rows[0]
    assert row["value"] == 3.0 and row["add.value"] == 3.0
