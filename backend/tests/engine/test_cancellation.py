"""Cancellation: killed process workers, cooperative threads, superseding edits."""

from __future__ import annotations

import asyncio
import time

from tests.engine.conftest import Harness, make_doc, wait_for


def _sleep_doc(node_type: str, seconds: float = 30.0) -> object:
    return make_doc(
        {
            "c": {"type": "core.math.constant", "params": {"value": 4.0}},
            "s": {"type": node_type, "params": {"seconds": seconds}, "linked": ["x"]},
        },
        {"e1": {"from": ["c", "out"], "to": ["s", "x"]}},
    )


async def test_process_worker_sleeping_30s_is_killed_within_a_second(
    process_harness: Harness,
) -> None:
    doc = _sleep_doc("test.sleep.hard")
    scheduler = process_harness.scheduler(doc)  # type: ignore[arg-type]
    scheduler.set_auto_run(False)
    run = asyncio.create_task(scheduler.run())
    await wait_for(lambda: scheduler.records["s"].state == "running", timeout=60)
    await asyncio.sleep(1.5)  # the worker has imported everything and is inside time.sleep
    started = time.perf_counter()
    assert scheduler.cancel(node_id="s") is True
    await asyncio.wait_for(run, timeout=10)
    assert time.perf_counter() - started < 1.0
    assert scheduler.records["s"].state == "cancelled"
    assert scheduler.records["s"].cost_class == "expensive"
    assert scheduler.run_history[-1].status == "cancelled"
    assert process_harness.states("s")[-1] == "cancelled"

    # The pool replaces the killed worker; a follow-up run succeeds.
    doc.nodes["s"].params["seconds"] = 0.01  # type: ignore[attr-defined]
    scheduler.update(doc)  # type: ignore[arg-type]
    await asyncio.wait_for(scheduler.run(), timeout=60)
    assert scheduler.records["s"].state == "done"
    assert scheduler.output("s", "out").value == 4.0  # type: ignore[union-attr]


async def test_thread_node_cancels_cooperatively(harness: Harness) -> None:
    doc = _sleep_doc("test.sleep")
    scheduler = harness.scheduler(doc)  # type: ignore[arg-type]
    scheduler.set_auto_run(False)
    run = asyncio.create_task(scheduler.run())
    await wait_for(lambda: scheduler.records["s"].state == "running")
    run_id = scheduler.current_run.run_id  # type: ignore[union-attr]
    assert scheduler.cancel(run_id="not-this-one") is False
    started = time.perf_counter()
    assert scheduler.cancel(run_id=run_id) is True
    await asyncio.wait_for(run, timeout=5)
    assert time.perf_counter() - started < 1.0
    assert scheduler.records["s"].state == "cancelled"
    assert scheduler.run_history[-1].status == "cancelled"
    assert scheduler.cancel() is False  # nothing running any more


async def test_edit_while_running_cancels_the_running_node(harness: Harness) -> None:
    doc = _sleep_doc("test.sleep")
    scheduler = harness.scheduler(doc)  # type: ignore[arg-type]
    scheduler.set_auto_run(False)
    run = asyncio.create_task(scheduler.run())
    await wait_for(lambda: scheduler.records["s"].state == "running")
    doc.nodes["s"].params["seconds"] = 0.01  # type: ignore[attr-defined]
    scheduler.update(doc)  # type: ignore[arg-type]
    await asyncio.wait_for(run, timeout=5)
    assert scheduler.records["s"].state == "dirty"  # superseded: marked dirty for the next run
    await scheduler.run()
    assert scheduler.records["s"].state == "done"


async def test_pending_nodes_are_left_dirty_when_run_is_cancelled(harness: Harness) -> None:
    doc = make_doc(
        {
            "s": {"type": "test.sleep", "params": {"seconds": 30}},
            "after": {"type": "core.math.expr", "linked": ["x"]},
        },
        {"e1": {"from": ["s", "out"], "to": ["after", "x"]}},
    )
    scheduler = harness.scheduler(doc)
    scheduler.set_auto_run(False)
    run = asyncio.create_task(scheduler.run())
    await wait_for(lambda: scheduler.records["s"].state == "running")
    scheduler.cancel()
    await asyncio.wait_for(run, timeout=5)
    assert scheduler.records["after"].state == "dirty"
    assert "running" not in harness.states("after")


async def test_close_cancels_everything(harness: Harness) -> None:
    doc = _sleep_doc("test.sleep")
    scheduler = harness.scheduler(doc)  # type: ignore[arg-type]
    scheduler.set_auto_run(False)
    scheduler.start_run()
    await wait_for(lambda: scheduler.records["s"].state == "running")
    await asyncio.wait_for(scheduler.close(), timeout=5)
    assert scheduler.records["s"].state == "cancelled"
