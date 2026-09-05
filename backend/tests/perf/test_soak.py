"""Memory soak: a 200-row batch, and two users' engines side by side.

Two things in the server are unbounded by construction and have to be checked rather than argued
about: `BatchRunner` keeps the last runs' rows in memory, and `RuntimePool` builds an
`EngineRuntime` per account and never evicts it (a known gap — see `docs/dev/performance.md`).
The gate is that a long batch's resident set comes back to where it started, not that it never
grows: a run that is holding two hundred rows' results is *supposed* to be using memory.
"""

from __future__ import annotations

import gc
from typing import Any

import psutil
import pytest

from astro_canvas.engine.batch import BatchRunner, spec_from_layout
from astro_canvas.engine.scheduler import SchedulerConfig
from tests.engine.conftest import Harness, make_doc, wait_for
from tests.perf.conftest import Perf

pytestmark = pytest.mark.perf

REGISTRY_FACTORY = "tests.engine.nodes:build_registry"
ROWS = 200
MB = 1024 * 1024


def rss_mb() -> float:
    gc.collect()
    return psutil.Process().memory_info().rss / MB


def pipeline() -> Any:
    """`value -> x * y`, both bound per row, with the product collected."""
    return make_doc(
        {
            "src": {"type": "core.math.constant", "params": {"value": 1.0}},
            "mul": {
                "type": "core.math.expr",
                "params": {"expression": "x * y", "y": 1.0},
                "linked": ["x"],
            },
        },
        {"e1": {"from": ["src", "out"], "to": ["mul", "x"]}},
        promoted=[{"node": "src", "param": "value"}, {"node": "mul", "param": "y"}],
        layouts={
            "batch": {
                "columns": [{"promoted": "src.value", "column": "x"}, "mul.y"],
                "collect": ["mul.out"],
            }
        },
    )


async def test_two_hundred_rows_come_back_to_the_baseline(perf: Perf, harness: Harness) -> None:
    doc = pipeline()
    spec = spec_from_layout(doc.layouts["batch"])
    runner = BatchRunner(
        registry=harness.registry,
        cache=harness.cache,
        bus=harness.bus,
        workspace_root=harness.workspace.root,
        scratch_root=harness.workspace.scratch_dir,
        threads=harness.threads,
        processes=harness.processes,
        config=lambda: SchedulerConfig(debounce_s=0.01, registry_factory=REGISTRY_FACTORY),
    )
    rows = [{"x": float(i), "mul.y": float(i % 7)} for i in range(ROWS)]

    baseline = rss_mb()
    perf.record("rss before the batch", baseline, "MB")
    run = runner.start(doc, rows, spec)
    await wait_for(lambda: run.status in ("done", "error", "cancelled"), timeout=300.0)
    assert run.status == "done", run.status
    assert run.counts().get("done") == ROWS
    elapsed = ((run.finished or run.started) - run.started) * 1000
    perf.record("batch of 200 rows", elapsed, "ms", gate=120_000.0)
    during = rss_mb()
    perf.record("rss holding 200 rows of results", during - baseline, "MB above baseline")

    # Dropping the run is what a server does when the ring buffer rolls over.
    runner.runs.clear()
    harness.cache.memory.clear()
    harness.bus.history.clear()
    after = rss_mb()
    perf.record("rss after dropping the batch", after - baseline, "MB above baseline", gate=64.0)
    assert after - baseline < 64.0


async def test_a_second_engine_costs_what_a_second_engine_costs(
    perf: Perf, harness: Harness
) -> None:
    """`RuntimePool` never evicts, so the per-account cost is the number that sizes a server."""
    doc = pipeline()
    first = harness.scheduler(doc)
    first.set_auto_run(False)
    await first.run()
    baseline = rss_mb()

    doc.id = "wf-2"
    second = harness.scheduler(doc)
    second.set_auto_run(False)
    await second.run()
    perf.record("rss for a second open document", rss_mb() - baseline, "MB above baseline")
    assert all(r.state == "done" for r in second.records.values())
