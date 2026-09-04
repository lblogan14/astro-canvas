"""Subgraphs: inlining, nesting, promoted params, disabled instances and cache-key identity."""

from __future__ import annotations

from typing import Any

from astro_canvas.engine.graph import ExecGraph, ValidationErrors, WorkflowDoc, compile
from astro_canvas.sdk import NodeRegistry
from tests.engine.conftest import Harness, make_doc

# ``ADD`` adds ``y`` to its linked input ``x``; ``SCALE`` multiplies by ``y``.
ADD = {"type": "core.math.expr", "params": {"expression": "x + y", "y": 1.0}, "linked": ["x"]}
SCALE = {"type": "core.math.expr", "params": {"expression": "x * y", "y": 2.0}, "linked": ["x"]}


def _body(**extra: Any) -> dict[str, Any]:
    """A one-node subgraph exposing ``value`` -> ``result`` and promoting ``plus.y``."""
    return {
        "name": "Add k",
        "nodes": {"plus": ADD},
        "edges": {},
        "inputs": [{"name": "value", "node": "plus", "port": "x"}],
        "outputs": [{"name": "result", "node": "plus", "port": "out"}],
        "promoted": [{"node": "plus", "param": "y", "label": "Offset"}],
        **extra,
    }


def _doc(instance: dict[str, Any], **extra: Any) -> WorkflowDoc:
    return make_doc(
        {
            "c": {"type": "core.math.constant", "params": {"value": 5.0}},
            "inst": {"type": "subgraph:add", **instance},
        },
        {"e1": {"from": ["c", "out"], "to": ["inst", "value"]}},
        subgraphs={"add": _body()},
        **extra,
    )


def test_promoted_param_on_the_instance_overrides_the_inner_node(registry: NodeRegistry) -> None:
    graph = compile(_doc({"params": {"plus.y": 10.0}}), registry)
    assert isinstance(graph, ExecGraph)
    assert graph.nodes["inst/plus"].params["y"] == 10.0


def test_unpromoted_instance_param_is_reported(registry: NodeRegistry) -> None:
    result = compile(_doc({"params": {"plus.nope": 1.0}}), registry)
    assert isinstance(result, ValidationErrors)
    issue = result.node_errors["inst"][0]
    assert issue.code == "unknown_param" and issue.param == "plus.nope"


def test_promoted_param_pointing_at_a_missing_node_is_reported(registry: NodeRegistry) -> None:
    doc = _doc({"params": {"ghost.y": 1.0}})
    doc.subgraphs["add"].promoted.append(
        type(doc.subgraphs["add"].promoted[0])(node="ghost", param="y")
    )
    result = compile(doc, registry)
    assert isinstance(result, ValidationErrors)
    assert "has no node" in result.node_errors["inst"][0].message


def test_linked_promoted_param_becomes_an_input_port_on_the_instance(
    registry: NodeRegistry,
) -> None:
    doc = _doc({"linked": ["plus.y"]})
    doc.nodes["off"] = doc.nodes["c"].model_copy(update={"params": {"value": 7.0}})
    doc.edges["e2"] = doc.edges["e1"].model_copy(
        update={"source": ("off", "out"), "target": ("inst", "plus.y")}
    )
    graph = compile(doc, registry)
    assert isinstance(graph, ExecGraph)
    inner = graph.nodes["inst/plus"]
    assert inner.inputs == {"x": ("c", "out"), "y": ("off", "out")}
    assert "y" in inner.linked


def test_nested_subgraphs_inline_with_namespaced_ids(registry: NodeRegistry) -> None:
    doc = make_doc(
        {
            "c": {"type": "core.math.constant", "params": {"value": 5.0}},
            "outer": {"type": "subgraph:outer", "params": {"inner.plus.y": 4.0}},
        },
        {"e1": {"from": ["c", "out"], "to": ["outer", "value"]}},
        subgraphs={
            "add": _body(),
            "outer": {
                "name": "Outer",
                "nodes": {"inner": {"type": "subgraph:add"}, "times": SCALE},
                "edges": {"i1": {"from": ["inner", "result"], "to": ["times", "x"]}},
                "inputs": [{"name": "value", "node": "inner", "port": "value"}],
                "outputs": [{"name": "out", "node": "times", "port": "out"}],
                "promoted": [{"node": "inner", "param": "plus.y"}],
            },
        },
    )
    graph = compile(doc, registry)
    assert isinstance(graph, ExecGraph)
    assert set(graph.nodes) == {"c", "outer/inner/plus", "outer/times"}
    assert graph.nodes["outer/inner/plus"].params["y"] == 4.0
    assert graph.nodes["outer/times"].inputs == {"x": ("outer/inner/plus", "out")}
    assert graph.nodes["outer/inner/plus"].doc_id == "outer"


def test_subgraph_nesting_depth_is_capped(registry: NodeRegistry) -> None:
    subgraphs: dict[str, Any] = {
        "loop": {
            "name": "Loop",
            "nodes": {"inner": {"type": "subgraph:loop"}},
            "inputs": [],
            "outputs": [],
        }
    }
    result = compile(
        make_doc({"top": {"type": "subgraph:loop"}}, {}, subgraphs=subgraphs), registry
    )
    assert isinstance(result, ValidationErrors)
    codes = {i.code for issues in result.node_errors.values() for i in issues}
    assert "subgraph_depth" in codes


def test_disabled_instance_is_dropped_and_consumers_report_it(registry: NodeRegistry) -> None:
    doc = _doc({"disabled": True})
    doc.nodes["dbl"] = doc.nodes["c"].model_copy(update={"type": "core.math.expr"})
    doc.nodes["dbl"] = doc.nodes["dbl"].model_copy(
        update={"params": {"expression": "x * 2"}, "linked": ["x"]}
    )
    doc.edges["e2"] = doc.edges["e1"].model_copy(
        update={"source": ("inst", "result"), "target": ("dbl", "x")}
    )
    result = compile(doc, registry)
    assert isinstance(result, ValidationErrors)
    assert result.node_errors["dbl"][0].code == "upstream_disabled"
    assert not any(nid.startswith("inst") for nid in result.graph.nodes)


async def test_collapsed_and_expanded_graphs_agree_on_values_and_cache_keys(
    harness: Harness,
) -> None:
    """The acceptance case: collapsing nodes must not change results or cache keys."""
    flat = make_doc(
        {
            "c": {"type": "core.math.constant", "params": {"value": 5.0}},
            "plus": {**ADD, "params": {"expression": "x + y", "y": 3.0}},
            "times": SCALE,
        },
        {
            "e1": {"from": ["c", "out"], "to": ["plus", "x"]},
            "e2": {"from": ["plus", "out"], "to": ["times", "x"]},
        },
    )
    collapsed = make_doc(
        {
            "c": {"type": "core.math.constant", "params": {"value": 5.0}},
            "inst": {"type": "subgraph:pipe", "params": {"plus.y": 3.0}},
        },
        {"e1": {"from": ["c", "out"], "to": ["inst", "value"]}},
        id="wf2",
        subgraphs={
            "pipe": {
                "name": "Pipe",
                "nodes": {"plus": ADD, "times": SCALE},
                "edges": {"i1": {"from": ["plus", "out"], "to": ["times", "x"]}},
                "inputs": [{"name": "value", "node": "plus", "port": "x"}],
                "outputs": [{"name": "result", "node": "times", "port": "out"}],
                "promoted": [{"node": "plus", "param": "y"}],
            }
        },
    )

    first = harness.scheduler(flat)
    first.set_auto_run(False)
    await first.run()
    second = harness.scheduler(collapsed)
    second.set_auto_run(False)
    await second.run()

    assert first.output("times", "out").value == 16.0  # type: ignore[union-attr]
    assert second.output("inst/times", "out").value == 16.0  # type: ignore[union-attr]
    assert second.records["inst/plus"].key == first.records["plus"].key
    assert second.records["inst/times"].key == first.records["times"].key
    # Same keys mean the second run is a pure cache hit.
    assert second.records["inst/times"].cache_hit
