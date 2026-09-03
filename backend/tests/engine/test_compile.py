"""``compile``: invalid fixtures match golden node errors; inlining, bypass and linking work."""

from __future__ import annotations

import pytest

from astro_canvas.engine.graph import ExecGraph, ValidationErrors, WorkflowDoc, compile
from astro_canvas.sdk import NodeRegistry
from tests.engine.conftest import load_doc, load_expected, make_doc

INVALID = ["cycle", "type_mismatch", "unknown_node", "missing_input", "bad_param"]


@pytest.mark.parametrize("name", INVALID)
def test_invalid_fixture_matches_golden(name: str, registry: NodeRegistry) -> None:
    result = compile(load_doc(f"invalid/{name}"), registry)
    assert isinstance(result, ValidationErrors)
    expected = load_expected(name)
    assert result.model_dump()["node_errors"] == expected["node_errors"]
    assert result.graph.order == expected["runnable"]
    assert sorted(result.graph.blocked) == expected["blocked"]


def test_cycle_reports_every_member_and_keeps_the_rest_runnable(registry: NodeRegistry) -> None:
    result = compile(load_doc("invalid/cycle"), registry)
    assert isinstance(result, ValidationErrors)
    assert {n for n, issues in result.node_errors.items() if issues[0].code == "cycle"} == {
        "a",
        "b",
    }
    assert result.graph.order == ["c"]


def test_valid_chain_compiles_in_topological_order(registry: NodeRegistry) -> None:
    graph = compile(load_doc("math_chain"), registry)
    assert isinstance(graph, ExecGraph)
    assert graph.order.index("c") < graph.order.index("sq") < graph.order.index("sum")
    total = graph.nodes["sum"]
    assert total.inputs == {"x": ("sq", "out"), "y": ("c", "out")}
    assert total.linked == frozenset({"x", "y"})
    # Defaults are filled and linked params are left out of the resolved params.
    assert total.params == {"expression": "x + y + z", "z": 1.0}
    assert graph.nodes["c"].params == {"value": 2.0}
    assert graph.nodes["note"].params == {"text": "# Sample\nA tiny reactive chain."}
    assert graph.ancestors(["sum"]) == {"c", "sq"}
    assert graph.descendants(["c"]) == {"sq", "sum"}


def test_subgraph_instance_is_inlined(registry: NodeRegistry) -> None:
    graph = compile(load_doc("subgraph_math"), registry)
    assert isinstance(graph, ExecGraph)
    assert set(graph.nodes) == {"c", "inst/plus", "dbl"}
    assert graph.nodes["inst/plus"].inputs == {"x": ("c", "out")}
    assert graph.nodes["dbl"].inputs == {"x": ("inst/plus", "out")}
    assert graph.nodes["inst/plus"].doc_id == "inst"


def test_unknown_subgraph_and_ports_are_reported(registry: NodeRegistry) -> None:
    doc = load_doc("subgraph_math")
    doc.nodes["ghost"] = doc.nodes["inst"].model_copy(update={"type": "subgraph:nope"})
    doc.edges["bad"] = doc.edges["e2"].model_copy(update={"source": ("inst", "missing")})
    result = compile(doc, registry)
    assert isinstance(result, ValidationErrors)
    assert result.node_errors["ghost"][0].code == "unknown_subgraph"
    assert any(i.code == "unknown_port" for i in result.node_errors["dbl"])


def test_disabled_node_passes_matching_input_through(registry: NodeRegistry) -> None:
    graph = compile(load_doc("disabled_passthrough"), registry)
    assert isinstance(graph, ExecGraph)
    assert "crop" not in graph.nodes
    assert graph.nodes["rest"].inputs == {"spec": ("src", "out")}


def test_disabled_node_without_passthrough_blocks_consumer(registry: NodeRegistry) -> None:
    doc = make_doc(
        {
            "c": {"type": "core.math.constant", "params": {"value": 1.0}, "disabled": True},
            "e": {"type": "core.math.expr", "params": {"expression": "x"}, "linked": ["x"]},
        },
        {"e1": {"from": ["c", "out"], "to": ["e", "x"]}},
    )
    result = compile(doc, registry)
    assert isinstance(result, ValidationErrors)
    assert result.node_errors["e"][0].code == "upstream_disabled"


def test_edge_errors(registry: NodeRegistry) -> None:
    doc = make_doc(
        {
            "a": {"type": "core.math.constant"},
            "b": {"type": "core.math.constant"},
            "e": {"type": "core.math.expr", "linked": ["x"]},
        },
        {
            "dup1": {"from": ["a", "out"], "to": ["e", "x"]},
            "dup2": {"from": ["b", "out"], "to": ["e", "x"]},
            "noport": {"from": ["a", "nope"], "to": ["e", "y"]},
            "noinput": {"from": ["a", "out"], "to": ["e", "q"]},
            "dangling": {"from": ["zzz", "out"], "to": ["e", "z"]},
            "dangling2": {"from": ["a", "out"], "to": ["yyy", "z"]},
        },
    )
    result = compile(doc, registry)
    assert isinstance(result, ValidationErrors)
    codes = sorted(i.code for i in result.node_errors["e"])
    assert codes == ["dangling_edge", "multiple_inputs", "unknown_port", "unknown_port"]
    assert result.node_errors["a"][0].code == "dangling_edge"


def test_linked_param_type_uses_link_type(registry: NodeRegistry) -> None:
    doc = make_doc(
        {
            "s": {"type": "test.spec.make"},
            "e": {"type": "core.math.expr", "linked": ["x"]},
        },
        {"e1": {"from": ["s", "out"], "to": ["e", "x"]}},
    )
    result = compile(doc, registry)
    assert isinstance(result, ValidationErrors)
    assert result.node_errors["e"][0].code == "type_mismatch"
    assert "astro.Float" in result.node_errors["e"][0].message


def test_document_round_trips_unknown_fields_and_aliases() -> None:
    raw = {
        "id": "w",
        "nodes": {"a": {"type": "core.math.constant", "custom": {"x": 1}}},
        "edges": {"e": {"from": ["a", "out"], "to": ["a", "x"]}},
        "layouts": {"app": {"sections": []}},
        "future_field": True,
    }
    doc = WorkflowDoc.model_validate(raw)
    dumped = doc.model_dump(by_alias=True)
    assert dumped["edges"]["e"] == {"from": ("a", "out"), "to": ("a", "x")}
    assert dumped["future_field"] is True
    assert dumped["nodes"]["a"]["custom"] == {"x": 1}
    assert dumped["layouts"] == {"app": {"sections": []}}
    assert doc.format == "astro-canvas/workflow" and doc.version == 1
