"""Dirty propagation, debounce, cost gating, auto promotion, errors, fingerprints, timeouts."""

from __future__ import annotations

import asyncio

from tests.engine import nodes as test_nodes
from tests.engine.conftest import Harness, load_doc, make_doc, wait_for


async def test_cheap_edit_auto_runs_node_and_descendants(harness: Harness) -> None:
    doc = load_doc("math_chain")
    scheduler = harness.scheduler(doc)
    await wait_for(lambda: all(r.state == "done" for r in scheduler.records.values()))
    assert scheduler.output("sum", "out").value == 7.0  # 2**2 + 2 + 1  # type: ignore[union-attr]
    assert harness.events("run.started")[0].targets is None
    harness.bus.history.clear()

    doc.nodes["c"].params["value"] = 3.0
    scheduler.update(doc)
    assert scheduler.records["sq"].state == "dirty" and scheduler.records["note"].state == "done"
    await wait_for(lambda: scheduler.records["sum"].state == "done" and not scheduler.current_run)
    assert scheduler.output("sum", "out").value == 13.0  # type: ignore[union-attr]
    assert "running" in harness.states("sq") and "running" in harness.states("sum")
    assert harness.states("note") == []  # untouched node emitted nothing
    finished = harness.events("run.finished")
    assert len(finished) == 1 and finished[0].status == "done" and finished[0].n_nodes == 3


async def test_debounce_coalesces_rapid_edits(harness: Harness) -> None:
    doc = load_doc("math_chain")
    scheduler = harness.scheduler(doc)
    for value in (1.0, 2.0, 3.0, 4.0):
        doc.nodes["c"].params["value"] = value
        scheduler.update(doc)
        await asyncio.sleep(0.01)
    await wait_for(lambda: scheduler.records["sum"].state == "done" and not scheduler.current_run)
    assert len(harness.events("run.started")) == 1
    assert scheduler.output("sum", "out").value == 21.0  # type: ignore[union-attr]


async def test_expensive_node_is_gated_until_explicit_run(harness: Harness) -> None:
    doc = make_doc(
        {
            "c": {"type": "core.math.constant", "params": {"value": 2.0}},
            "slow": {"type": "test.sleep", "params": {"seconds": 0.01}, "linked": ["x"]},
            "after": {"type": "core.math.expr", "params": {"expression": "x + 1"}, "linked": ["x"]},
        },
        {
            "e1": {"from": ["c", "out"], "to": ["slow", "x"]},
            "e2": {"from": ["slow", "out"], "to": ["after", "x"]},
        },
    )
    scheduler = harness.scheduler(doc)
    await wait_for(lambda: scheduler.records["c"].state == "done" and not scheduler.current_run)
    slow, after = scheduler.records["slow"], scheduler.records["after"]
    assert (slow.state, slow.stale, slow.cost_class) == ("dirty", True, "expensive")
    assert (after.state, after.stale) == ("dirty", True)
    stale_events = [e for e in harness.events("node.status", "slow") if e.stale]
    assert stale_events and "running" not in harness.states("slow")

    await scheduler.run()
    assert slow.state == "done" and after.state == "done" and not slow.stale
    assert scheduler.output("after", "out").value == 3.0  # type: ignore[union-attr]

    doc.nodes["slow"].params["seconds"] = 0.02
    scheduler.update(doc)
    await asyncio.sleep(0.2)
    assert slow.state == "dirty" and slow.stale and after.state == "dirty"

    await scheduler.run(["after"])
    assert after.state == "done"


async def test_cost_override_in_document(harness: Harness) -> None:
    doc = make_doc({"c": {"type": "core.math.constant", "cost": "expensive"}})
    scheduler = harness.scheduler(doc)
    await asyncio.sleep(0.2)
    assert scheduler.records["c"].state == "dirty" and scheduler.records["c"].stale
    doc.nodes["c"].cost = None
    scheduler.update(doc)
    await wait_for(lambda: scheduler.records["c"].state == "done")


async def test_auto_cost_is_promoted_after_slow_runs(harness: Harness) -> None:
    doc = make_doc({"a": {"type": "test.slow.auto", "params": {"seconds": 0.05, "x": 1.0}}})
    scheduler = harness.scheduler(doc, auto_threshold_ms=10.0)
    await wait_for(lambda: scheduler.records["a"].state == "done")
    assert scheduler.records["a"].cost_class == "expensive"  # promoted after measuring ~50 ms
    doc.nodes["a"].params["x"] = 2.0
    scheduler.update(doc)
    await asyncio.sleep(0.25)
    assert scheduler.records["a"].state == "dirty" and scheduler.records["a"].stale
    await scheduler.run()
    assert scheduler.output("a", "out").value == 2.0  # type: ignore[union-attr]
    assert harness.stats.values["a"][1] == 2


async def test_error_halts_descendants_but_not_siblings(harness: Harness) -> None:
    doc = make_doc(
        {
            "c": {"type": "core.math.constant", "params": {"value": 1.0}},
            "bad": {"type": "test.fail", "params": {"message": "kaboom"}, "linked": ["x"]},
            "child": {"type": "core.math.expr", "linked": ["x"]},
            "sibling": {
                "type": "core.math.expr",
                "params": {"expression": "x * 10"},
                "linked": ["x"],
            },
        },
        {
            "e1": {"from": ["c", "out"], "to": ["bad", "x"]},
            "e2": {"from": ["bad", "out"], "to": ["child", "x"]},
            "e3": {"from": ["c", "out"], "to": ["sibling", "x"]},
        },
    )
    scheduler = harness.scheduler(doc)
    await wait_for(lambda: bool(harness.events("run.finished")))
    assert scheduler.records["bad"].state == "error"
    assert scheduler.records["child"].state == "dirty"
    assert scheduler.records["sibling"].state == "done"
    error = harness.events("node.error", "bad")[0]
    assert error.message == "RuntimeError: kaboom" and "kaboom" in error.traceback
    assert harness.events("run.finished")[0].status == "error"
    runs = harness.runs.list(doc.id)
    assert runs[0].status == "error"
    statuses = {r.node_id: r.status for r in harness.runs.node_runs(runs[0].id)}
    assert statuses["bad"] == "error" and statuses["sibling"] == "done" and "child" not in statuses


async def test_fingerprint_busts_the_cache(harness: Harness) -> None:
    doc = make_doc({"f": {"type": "test.fingerprint", "params": {"x": 1.0}}})
    scheduler = harness.scheduler(doc)
    scheduler.set_auto_run(False)
    await scheduler.run()
    key = scheduler.records["f"].key
    scheduler.update(doc)
    assert scheduler.records["f"].key == key and scheduler.records["f"].state == "done"
    test_nodes.bump_fingerprint()
    scheduler.update(doc)
    assert scheduler.records["f"].key != key and scheduler.records["f"].state == "dirty"


async def test_validation_issues_are_published_and_nodes_idle(harness: Harness) -> None:
    doc = load_doc("invalid/missing_input")
    scheduler = harness.scheduler(doc)
    validation = harness.events("graph.validation")[0]
    assert validation.node_errors["crop"][0].code == "missing_input"
    assert scheduler.records["crop"].state == "idle" and scheduler.records["vel"].state == "idle"
    await asyncio.sleep(0.15)
    assert harness.events("run.started") == []  # nothing runnable


async def test_run_wall_clock_limit_cancels(harness: Harness) -> None:
    doc = make_doc({"s": {"type": "test.sleep", "params": {"seconds": 30}}})
    scheduler = harness.scheduler(doc, run_timeout_s=0.2)
    scheduler.set_auto_run(False)
    await asyncio.wait_for(scheduler.run(), timeout=5)
    info = scheduler.run_history[-1]
    assert info.status == "cancelled" and "exceeded" in (info.message or "")
    assert scheduler.records["s"].state == "cancelled"


async def test_note_without_ports_runs_and_summaries_flow(harness: Harness) -> None:
    doc = make_doc({"s": {"type": "test.spec.make", "params": {"n": 5000}}})
    scheduler = harness.scheduler(doc)
    await wait_for(lambda: scheduler.records["s"].state == "done")
    summary = harness.events("node.output.summary", "s")[0]
    assert summary.type_id == "astro.Spectrum1D" and summary.summary["n"] == 5000
    assert len(summary.summary["wave"]) <= 4000
    statuses = harness.events("node.status", "s")
    assert statuses[-1].elapsed_ms is not None and statuses[-1].cost_class == "cheap"
