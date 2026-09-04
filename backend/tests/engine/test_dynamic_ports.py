"""Compiling and running a node whose ports come from its params (the code node)."""

from __future__ import annotations

from astro_canvas.engine.graph import ExecGraph, ValidationErrors, compile
from astro_canvas.sdk import NodeRegistry
from tests.engine.conftest import Harness, make_doc, wait_for

CODE = "core.code.python"


def _doc(**overrides: object) -> object:
    """A constant feeding a code node that doubles it."""
    nodes = {
        "c": {"type": "core.math.constant", "params": {"value": 21.0}},
        "py": {
            "type": CODE,
            "params": {
                "source": "out = x * 2",
                "inputs": [{"name": "x", "type": "astro.Float"}],
                "outputs": [{"name": "out", "type": "astro.Float"}],
                **overrides,
            },
        },
    }
    return make_doc(nodes, {"e": {"from": ["c", "out"], "to": ["py", "x"]}})


def test_declared_ports_wire_like_any_other(registry: NodeRegistry) -> None:
    graph = compile(_doc(), registry)  # type: ignore[arg-type]
    assert isinstance(graph, ExecGraph)
    assert graph.nodes["py"].inputs == {"x": ("c", "out")}
    assert graph.order == ["c", "py"]


def test_a_missing_declared_input_is_a_missing_input_error(registry: NodeRegistry) -> None:
    doc = make_doc(
        {
            "py": {
                "type": CODE,
                "params": {
                    "source": "out = x",
                    "inputs": [{"name": "x", "type": "astro.Float"}],
                    "outputs": [{"name": "out"}],
                },
            }
        }
    )
    result = compile(doc, registry)
    assert isinstance(result, ValidationErrors)
    assert [i.code for i in result.node_errors["py"]] == ["missing_input"]


def test_a_wrongly_typed_edge_into_a_declared_port_is_reported(registry: NodeRegistry) -> None:
    doc = make_doc(
        {
            "s": {"type": "test.spec.make", "params": {"n": 8}},
            "py": {
                "type": CODE,
                "params": {
                    "source": "out = x",
                    "inputs": [{"name": "x", "type": "astro.Float"}],
                    "outputs": [{"name": "out"}],
                },
            },
        },
        {"e": {"from": ["s", "out"], "to": ["py", "x"]}},
    )
    result = compile(doc, registry)
    assert isinstance(result, ValidationErrors)
    assert [i.code for i in result.node_errors["py"]] == ["type_mismatch"]


async def test_a_declared_output_flows_downstream(harness: Harness) -> None:
    doc = make_doc(
        {
            "c": {"type": "core.math.constant", "params": {"value": 21.0}},
            "py": {
                "type": CODE,
                "params": {
                    "source": "out = x * 2",
                    "inputs": [{"name": "x", "type": "astro.Float"}],
                    "outputs": [{"name": "out", "type": "astro.Float"}],
                },
            },
            "sq": {"type": "core.math.expr", "params": {"expression": "x + 0"}, "linked": ["x"]},
        },
        {
            "e1": {"from": ["c", "out"], "to": ["py", "x"]},
            "e2": {"from": ["py", "out"], "to": ["sq", "x"]},
        },
    )
    scheduler = harness.scheduler(doc)
    await scheduler.run()
    await wait_for(lambda: scheduler.records["sq"].state == "done")
    value = scheduler.output("sq", "out")
    assert value is not None
    assert value.model_dump()["value"] == 42.0


async def test_renaming_an_output_port_changes_the_cache_key(harness: Harness) -> None:
    """The declaration is a param, so editing it dirties the node like any other edit."""
    scheduler = harness.scheduler(_doc())  # type: ignore[arg-type]
    first = scheduler.records["py"].key
    scheduler.update(_doc(outputs=[{"name": "renamed", "type": "astro.Float"}]))  # type: ignore[arg-type]
    assert scheduler.records["py"].key != first


def test_a_quarantined_node_and_its_consumers_are_kept_out_of_the_graph(
    registry: NodeRegistry,
) -> None:
    """The trust gate blocks a code node at compile time (phase 11, design 11)."""
    doc = make_doc(
        {
            "c": {"type": "core.math.constant", "params": {"value": 1.0}},
            "py": {
                "type": CODE,
                "params": {
                    "source": "out = x",
                    "inputs": [{"name": "x", "type": "astro.Float"}],
                    "outputs": [{"name": "out", "type": "astro.Float"}],
                },
            },
            "sq": {"type": "core.math.expr", "params": {"expression": "x"}, "linked": ["x"]},
        },
        {
            "e1": {"from": ["c", "out"], "to": ["py", "x"]},
            "e2": {"from": ["py", "out"], "to": ["sq", "x"]},
        },
    )
    result = compile(doc, registry, quarantined={"py": "review this snippet first"})
    assert isinstance(result, ValidationErrors)
    assert [i.code for i in result.node_errors["py"]] == ["quarantined"]
    assert result.node_errors["py"][0].message == "review this snippet first"
    # The constant still runs; the code node and everything it feeds do not.
    assert result.graph.order == ["c"]
    assert result.graph.blocked == {"sq"}
