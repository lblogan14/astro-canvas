"""Engine cost at 500 nodes: compiling, keying, running, and the reactive re-run after an edit.

Design 1.6 sets the shape of the graph a user may build and still expect the canvas to answer an
edit immediately. The frame-rate half of that gate is `e2e/perf-500.spec.ts`; this is the server
half — how long the engine takes to notice one changed parameter among five hundred nodes and to
produce the new value.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from astro_canvas.engine.graph import ValidationErrors, WorkflowDoc, compile
from tests.engine.conftest import Harness, make_doc
from tests.perf.conftest import Perf

pytestmark = pytest.mark.perf

COUNT = 500


def synthetic(count: int = COUNT) -> WorkflowDoc:
    """`count` alternating constant -> expr nodes, the same graph the e2e perf spec opens."""
    nodes: dict[str, Any] = {}
    edges: dict[str, Any] = {}
    for i in range(count):
        if i % 2 == 0:
            nodes[f"n{i}"] = {"type": "core.math.constant", "params": {"value": float(i)}}
        else:
            nodes[f"n{i}"] = {
                "type": "core.math.expr",
                "params": {"expression": "x + 1"},
                "linked": ["x"],
            }
            edges[f"e{i}"] = {"from": [f"n{i - 1}", "out"], "to": [f"n{i}", "x"]}
    return make_doc(nodes, edges, id="perf-500")


def test_compile_and_key_500_nodes(perf: Perf, harness: Harness) -> None:
    doc = synthetic()
    compile(doc, harness.registry)  # warm the pydantic validators and the spec cache
    with perf.timed("compile a 500-node document", gate=250.0) as t:
        graph = compile(doc, harness.registry)
    assert not isinstance(graph, ValidationErrors)
    assert len(graph.nodes) == COUNT
    assert t.elapsed < 250.0

    scheduler = harness.scheduler()
    scheduler.set_auto_run(False)
    with perf.timed("scheduler.update (compile + 500 cache keys)", gate=400.0) as t:
        scheduler.update(doc)
    assert t.elapsed < 400.0
    assert sum(1 for r in scheduler.records.values() if r.state == "dirty") == COUNT


async def test_reactive_re_run_after_one_edit(perf: Perf, harness: Harness) -> None:
    """One parameter changes: only its descendants re-run, and the answer is under 300 ms."""
    doc = synthetic()
    scheduler = harness.scheduler(doc)
    scheduler.set_auto_run(False)
    with perf.timed("first run of 500 cheap nodes", gate=20_000.0) as t:
        await scheduler.run()
    assert all(r.state == "done" for r in scheduler.records.values())
    assert t.elapsed < 20_000.0

    # A leaf edit: two nodes to re-run out of five hundred.
    doc.nodes["n499"].params["expression"] = "x + 2"
    started = time.perf_counter()
    scheduler.update(doc)
    await scheduler.run()
    elapsed = (time.perf_counter() - started) * 1000
    perf.record("re-run after a leaf edit (500 nodes)", elapsed, "ms", gate=300.0)
    assert scheduler.records["n499"].state == "done"
    assert elapsed < 300.0

    # A root edit: everything downstream is one long chain of two nodes, because the synthetic
    # graph is pairs — so this measures the cache lookups for the 498 nodes that did not change.
    doc.nodes["n0"].params["value"] = -1.0
    started = time.perf_counter()
    scheduler.update(doc)
    await scheduler.run()
    elapsed = (time.perf_counter() - started) * 1000
    perf.record("re-run after a root edit (500 nodes)", elapsed, "ms", gate=1000.0)
    assert elapsed < 1000.0


async def test_status_snapshot_is_cheap(perf: Perf, harness: Harness) -> None:
    """`snapshot()` is what a page load and every reconnect ask for."""
    scheduler = harness.scheduler(synthetic())
    scheduler.set_auto_run(False)
    scheduler.snapshot()
    with perf.timed("status snapshot of 500 nodes", gate=100.0) as t:
        snapshot = scheduler.snapshot()
    assert len(snapshot) == COUNT
    assert t.elapsed < 100.0
