"""``run(targets=…)`` runs only the needed ancestors; cache hits are reported as such."""

from __future__ import annotations

from tests.engine.conftest import Harness, make_doc


def _two_branches() -> object:
    return make_doc(
        {
            "c": {"type": "core.math.constant", "params": {"value": 2.0}},
            "sq": {"type": "core.math.expr", "params": {"expression": "x ** 2"}, "linked": ["x"]},
            "sum": {"type": "core.math.expr", "params": {"expression": "x + 1"}, "linked": ["x"]},
            "c2": {"type": "core.math.constant", "params": {"value": 7.0}},
            "other": {"type": "core.math.expr", "params": {"expression": "x * 3"}, "linked": ["x"]},
        },
        {
            "e1": {"from": ["c", "out"], "to": ["sq", "x"]},
            "e2": {"from": ["sq", "out"], "to": ["sum", "x"]},
            "e3": {"from": ["c2", "out"], "to": ["other", "x"]},
        },
    )


async def test_targets_run_only_needed_upstream(harness: Harness) -> None:
    doc = _two_branches()
    scheduler = harness.scheduler(doc)  # type: ignore[arg-type]
    scheduler.set_auto_run(False)
    run_id = await scheduler.run(["sq"])
    states = {nid: rec.state for nid, rec in scheduler.records.items()}
    assert states == {"c": "done", "sq": "done", "sum": "dirty", "c2": "dirty", "other": "dirty"}
    started = harness.events("run.started")[0]
    assert started.run_id == run_id and started.targets == ["sq"] and started.n_nodes == 2
    assert harness.events("run.finished")[0].cached == 0
    node_runs = {r.node_id for r in harness.runs.node_runs(run_id)}
    assert node_runs == {"c", "sq"}

    harness.bus.history.clear()
    await scheduler.run()
    assert all(r.state == "done" for r in scheduler.records.values())
    started = harness.events("run.started")[0]
    assert started.n_nodes == 3  # c and sq were already done and are not re-planned
    assert scheduler.output("sum", "out").value == 5.0  # type: ignore[union-attr]
    assert scheduler.output("other", "out").value == 21.0  # type: ignore[union-attr]


async def test_cache_hits_are_reported_for_a_fresh_scheduler(harness: Harness) -> None:
    doc = _two_branches()
    first = harness.scheduler(doc)  # type: ignore[arg-type]
    first.set_auto_run(False)
    await first.run()
    harness.bus.history.clear()

    second = harness.scheduler(doc)  # type: ignore[arg-type]  # same cache, fresh state
    second.set_auto_run(False)
    assert all(r.state == "dirty" for r in second.records.values())
    await second.run(["sum"])
    hits = [e for e in harness.events("node.status") if e.state == "done"]
    assert {e.node_id for e in hits} == {"c", "sq", "sum"}
    assert all(e.cache_hit for e in hits)
    assert "running" not in [e.state for e in harness.events("node.status")]
    finished = harness.events("run.finished")[0]
    assert finished.cached == 3 and finished.status == "done"
    assert harness.events("node.output.summary", "sum")  # summaries are re-sent on hits


async def test_disk_cache_survives_memory_eviction(harness: Harness) -> None:
    doc = _two_branches()
    scheduler = harness.scheduler(doc)  # type: ignore[arg-type]
    scheduler.set_auto_run(False)
    await scheduler.run(["sum"])
    harness.cache.memory.clear()
    harness.bus.history.clear()
    await scheduler.run(["sum"])
    assert scheduler.records["sum"].cache_hit is True
    assert "running" not in [e.state for e in harness.events("node.status")]


async def test_unknown_targets_are_ignored(harness: Harness) -> None:
    doc = _two_branches()
    scheduler = harness.scheduler(doc)  # type: ignore[arg-type]
    scheduler.set_auto_run(False)
    await scheduler.run(["nope"])
    assert all(r.state == "dirty" for r in scheduler.records.values())
    assert harness.events("run.finished")[0].n_nodes == 0
