"""Ports declared by a node's own parameters (phase 11, the code node's contract)."""

from __future__ import annotations

from typing import Annotated, Any

import pytest

from astro_canvas.sdk import (
    ANY_TYPE,
    DynamicPorts,
    NodeContext,
    NodeDefinitionError,
    NullContext,
    Param,
    declared_ports,
    effective_ports,
    node,
    parse_declarations,
)


@node(
    id="tests.dyn.echo",
    name="Echo",
    category="Test",
    dynamic_ports=DynamicPorts(inputs="ins", outputs="outs", values="values"),
)
def echo(
    ctx: NodeContext,
    values: dict[str, Any],
    ins: Annotated[list[dict[str, Any]], Param(widget="ports")] = [],  # noqa: B006
    outs: Annotated[list[dict[str, Any]], Param(widget="ports")] = [],  # noqa: B006
) -> dict[str, Any]:
    """Return every input under the name of the output declared in the same position.

    Args:
        ins: Input port declarations.
        outs: Output port declarations.
    """
    assert ctx is not None
    names = [str(o["name"]) for o in outs]
    return dict(zip(names, values.values(), strict=False))


def test_static_spec_has_no_ports() -> None:
    """The registry spec carries the declaration, not the ports: those are per instance."""
    assert echo.spec.inputs == []
    assert echo.spec.outputs == []
    assert echo.spec.dynamic_ports == DynamicPorts(inputs="ins", outputs="outs", values="values")
    assert echo.output_kind == "dynamic"
    assert {p.name for p in echo.spec.params} == {"ins", "outs"}


def test_effective_ports_come_from_the_params() -> None:
    params = {
        "ins": [{"name": "a", "type": "astro.Float"}, {"name": "b"}],
        "outs": [{"name": "sum", "type": "astro.Float"}],
    }
    inputs, outputs = effective_ports(echo.spec, params)
    assert [(p.name, p.type) for p in inputs] == [("a", "astro.Float"), ("b", ANY_TYPE)]
    assert [(p.name, p.type) for p in outputs] == [("sum", "astro.Float")]


def test_effective_ports_of_a_normal_node_are_the_static_ones() -> None:
    from tests.sdk import sample_nodes

    inputs, outputs = effective_ports(sample_nodes.measure.spec, {"vmin": -10.0})
    assert inputs == list(sample_nodes.measure.spec.inputs)
    assert outputs == list(sample_nodes.measure.spec.outputs)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "not-a-list",
        [{"name": ""}],
        [{"name": "9lives"}],
        [{"name": "has space"}],
        [{"nope": 1}],
    ],
)
def test_malformed_declarations_are_dropped_not_raised(value: object) -> None:
    """Half-typed declarations are normal while editing; the compiler reports the missing port."""
    assert declared_ports(value) == []


def test_duplicate_names_keep_the_first() -> None:
    decls = parse_declarations([{"name": "a", "type": "astro.Int"}, {"name": "a"}])
    assert [(d.name, d.type) for d in decls] == [("a", "astro.Int")]


def test_bare_strings_declare_any_ports() -> None:
    assert [(d.name, d.type) for d in parse_declarations(["x", "y"])] == [
        ("x", ANY_TYPE),
        ("y", ANY_TYPE),
    ]


def test_call_routes_declared_inputs_into_the_values_parameter() -> None:
    params = {
        "ins": [{"name": "a"}, {"name": "b"}],
        "outs": [{"name": "first"}, {"name": "second"}],
    }
    assert echo.call({"a": 1, "b": 2}, params, NullContext()) == {"first": 1, "second": 2}


def test_a_dynamic_node_needs_a_values_parameter() -> None:
    with pytest.raises(NodeDefinitionError, match="values"):

        @node(
            id="tests.dyn.broken",
            name="Broken",
            category="Test",
            dynamic_ports=DynamicPorts(inputs="ins"),
        )
        def broken(ins: list[dict[str, Any]] = []) -> float:  # noqa: B006
            """No values parameter to receive the declared inputs."""
            return 0.0


def test_the_declaring_parameter_must_exist() -> None:
    with pytest.raises(NodeDefinitionError, match="is not a parameter"):

        @node(
            id="tests.dyn.missing",
            name="Missing",
            category="Test",
            dynamic_ports=DynamicPorts(outputs="nope"),
        )
        def missing() -> float:
            """Declares outputs in a parameter that does not exist."""
            return 0.0
