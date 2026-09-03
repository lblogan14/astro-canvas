"""Lazy inputs resolve on demand; expanding nodes run sub-graphs cached under the parent key."""

from __future__ import annotations

from astro_canvas.engine.cache import sub_key
from astro_canvas.sdk import ExpandNode, Expansion
from tests.engine.conftest import Harness, make_doc


def _switch_doc(pick: str) -> object:
    return make_doc(
        {
            "a": {"type": "core.math.constant", "params": {"value": 1.0}},
            "b": {"type": "test.fail", "params": {"message": "b was computed"}},
            "sw": {"type": "test.switch", "params": {"pick": pick}},
        },
        {
            "e1": {"from": ["a", "out"], "to": ["sw", "a"]},
            "e2": {"from": ["b", "out"], "to": ["sw", "b"]},
        },
    )


async def test_only_the_picked_lazy_branch_is_computed(harness: Harness) -> None:
    doc = _switch_doc("a")
    scheduler = harness.scheduler(doc)  # type: ignore[arg-type]
    scheduler.set_auto_run(False)
    await scheduler.run()
    assert scheduler.records["sw"].state == "done"
    assert scheduler.output("sw", "out").value == 1.0  # type: ignore[union-attr]
    assert scheduler.records["b"].state == "dirty"  # never ran
    assert "running" not in harness.states("b")
    assert scheduler.run_history[-1].status == "done"


async def test_lazy_branch_failure_surfaces_on_the_consumer(harness: Harness) -> None:
    doc = _switch_doc("b")
    scheduler = harness.scheduler(doc)  # type: ignore[arg-type]
    scheduler.set_auto_run(False)
    await scheduler.run()
    assert scheduler.records["b"].state == "error"
    assert scheduler.records["sw"].state == "error"
    error = harness.events("node.error", "sw")[0]
    assert "did not finish" in error.message and error.hint is not None


async def test_lazy_source_runs_once_when_needed_twice(harness: Harness) -> None:
    doc = make_doc(
        {
            "a": {"type": "core.math.constant", "params": {"value": 3.0}},
            "sw1": {"type": "test.switch", "params": {"pick": "a"}},
            "sw2": {"type": "test.switch", "params": {"pick": "a"}},
        },
        {
            "e1": {"from": ["a", "out"], "to": ["sw1", "a"]},
            "e2": {"from": ["a", "out"], "to": ["sw1", "b"]},
            "e3": {"from": ["a", "out"], "to": ["sw2", "a"]},
            "e4": {"from": ["a", "out"], "to": ["sw2", "b"]},
        },
    )
    scheduler = harness.scheduler(doc)
    scheduler.set_auto_run(False)
    await scheduler.run()
    assert scheduler.output("sw1", "out").value == 3.0  # type: ignore[union-attr]
    assert scheduler.output("sw2", "out").value == 3.0  # type: ignore[union-attr]
    assert harness.states("a").count("running") == 1


async def test_expansion_runs_sub_nodes_and_caches_under_parent_key(harness: Harness) -> None:
    doc = make_doc({"ex": {"type": "test.expand.sum3", "params": {"x": 2.0, "k": 3}}})
    scheduler = harness.scheduler(doc)
    scheduler.set_auto_run(False)
    await scheduler.run()
    assert scheduler.output("ex", "out").value == 6.0  # type: ignore[union-attr]
    parent_key = scheduler.records["ex"].key
    for i in range(3):
        sub = scheduler.records[f"ex/s{i}"]
        assert sub.state == "done" and sub.key == sub_key(parent_key, f"s{i}")
        assert harness.cache.lookup(sub.key) is not None
    assert "running" in harness.states("ex/s1")

    # Same params -> parent cache hit, sub-nodes untouched.
    harness.bus.history.clear()
    second = harness.scheduler(doc)
    second.set_auto_run(False)
    await second.run()
    assert second.records["ex"].cache_hit and harness.states("ex/s0") == []

    # Changed params -> new parent key -> fresh sub keys.
    doc.nodes["ex"].params["x"] = 3.0
    second.update(doc)
    await second.run()
    assert second.output("ex", "out").value == 9.0  # type: ignore[union-attr]
    assert second.records["ex/s0"].key != sub_key(parent_key, "s0")


def test_expansion_model_validates_references() -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown sub-node"):
        Expansion(nodes={"a": ExpandNode(type="t", inputs={"x": ("zzz", "out")})}, outputs={})
    with pytest.raises(ValueError, match="unknown sub-node"):
        Expansion(nodes={"a": ExpandNode(type="t")}, outputs={"out": ("b", "out")})
    with pytest.raises(ValueError, match="invalid sub-node id"):
        Expansion(nodes={"$in": ExpandNode(type="t")}, outputs={})
    ok = Expansion(
        nodes={"a": ExpandNode(type="t", inputs={"x": (Expansion.PARENT, "spec")})},
        outputs={"out": ("a", "out")},
    )
    assert ok.nodes["a"].inputs["x"] == ("$in", "spec")


async def test_any_values_stay_in_process(harness: Harness) -> None:
    doc = make_doc(
        {
            "mk": {"type": "test.any.make", "params": {"text": "hello"}},
            "rd": {"type": "test.any.read"},
            "rdx": {"type": "test.any.read.expensive"},
        },
        {
            "e1": {"from": ["mk", "out"], "to": ["rd", "value"]},
            "e2": {"from": ["mk", "out"], "to": ["rdx", "value"]},
        },
    )
    scheduler = harness.scheduler(doc)
    scheduler.set_auto_run(False)
    await scheduler.run()
    assert scheduler.output("rd", "out").value == "hello"  # type: ignore[union-attr]
    assert scheduler.output("rdx", "out").value == "hello"  # type: ignore[union-attr]
    assert harness.cache.refs(scheduler.records["mk"].key) is None  # never on disk
    summary = harness.events("node.output.summary", "mk")[0].summary
    assert summary == {"type": "astro.Any", "python_type": "dict"}
