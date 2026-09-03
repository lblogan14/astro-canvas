"""``@node`` introspection: ports vs params, outputs, errors, validation, and calling."""

from __future__ import annotations

from typing import Annotated, Literal

import astropy.units as u
import numpy as np
import pytest
from astro_canvas_core.types import Redshift, Spectrum1D
from pydantic import ValidationError

from astro_canvas.sdk import (
    NodeContext,
    NodeDef,
    NodeDefinitionError,
    NullContext,
    Param,
    node,
    parse_docstring,
    validate_call,
)
from tests.sdk import sample_nodes


def test_ports_params_context_and_meta() -> None:
    spec = sample_nodes.measure.spec
    assert spec.id == "sample.spec.measure" and spec.version == "1.2.0"
    assert spec.cost == "expensive" and spec.experimental and not spec.deprecated
    assert (spec.icon, spec.preview, spec.editor) == ("ruler", "ew-summary", "range-editor")
    assert spec.description.startswith("Measure a sample quantity on a spectrum.\n\nThe long")
    assert [(p.name, p.type, p.required, p.lazy) for p in spec.inputs] == [
        ("spec", "astro.Spectrum1D", True, False),
        ("reference", "astro.Spectrum1D", False, True),
    ]
    assert spec.inputs[0].description == "Continuum-normalized spectrum slice in velocity space."
    assert [p.name for p in spec.params] == [
        "vmin", "vmax", "method", "weights", "snr", "tag", "smoothing", "wrest",
    ]  # fmt: skip
    assert all(p.linkable for p in spec.params)
    assert [(o.name, o.type) for o in spec.outputs] == [("out", "astro.Redshift")]
    assert spec.outputs[0].description == "A redshift estimate."
    assert spec.param_docs["snr"] == "Also estimate the signal-to-noise ratio."
    assert spec.module == "tests.sdk.sample_nodes"
    assert sample_nodes.measure.context_param == "ctx"
    assert sample_nodes.measure.quantity_units == {"wrest": "Angstrom"}
    assert repr(sample_nodes.measure) == "<node sample.spec.measure v1.2.0 (expensive)>"
    assert sample_nodes.measure.__doc__ is not None and sample_nodes.measure.__name__ == "measure"


def test_multi_output_shapes() -> None:
    assert [(o.name, o.type) for o in sample_nodes.split.spec.outputs] == [
        ("blue", "astro.Spectrum1D"),
        ("red", "astro.Spectrum1D"),
        ("pivot", "astro.Float"),
    ]
    assert sample_nodes.split.output_kind == "named"
    assert sample_nodes.split.spec.inputs[0].description == "The spectrum to split."
    assert [(o.name, o.type) for o in sample_nodes.describe.spec.outputs] == [
        ("mean", "astro.Float"),
        ("count", "astro.Int"),
        ("label", "astro.Str"),
    ]
    assert [(o.name, o.type) for o in sample_nodes.swap.spec.outputs] == [
        ("second", "astro.Float"),
        ("first", "astro.Float"),
    ]
    assert sample_nodes.swap.output_kind == "tuple"
    assert sample_nodes.echo.spec.is_async and sample_nodes.echo.spec.outputs[0].type == "astro.Str"

    @node(id="t.out.default", name="T", category="T")
    def unnamed(a: float) -> tuple[float, Spectrum1D | None]:
        """Doc."""
        return a, None

    assert [o.name for o in unnamed.spec.outputs] == ["out0", "out1"]
    assert unnamed.spec.outputs[1].type == "astro.Spectrum1D"

    @node(id="t.out.json", name="T", category="T", outputs=["table"])
    def jsonish() -> dict[str, float]:
        """Doc."""
        return {}

    assert [(o.name, o.type) for o in jsonish.spec.outputs] == [("table", "astro.Json")]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"id": "Bad Id"}, "invalid node id"),
        ({"version": "1"}, "semver"),
        ({"cost": "free"}, "cost must be"),
        ({"name": " "}, "non-empty"),
        ({"lazy": ("x",)}, "not an input port"),
        ({"outputs": ("a", "b")}, "single output but 2"),
    ],
)
def test_bad_meta_raises(kwargs: dict[str, object], message: str) -> None:
    meta = {"id": "t.bad.meta", "name": "T", "category": "T", **kwargs}
    with pytest.raises(NodeDefinitionError, match=message):

        @node(**meta)  # type: ignore[arg-type]
        def f(x: float) -> float:
            """Doc."""
            return x


def test_bad_signatures_raise() -> None:
    dec = node(id="t.bad.sig", name="T", category="T")
    with pytest.raises(NodeDefinitionError, match="type annotation"):
        dec(lambda x: x)  # type: ignore[misc]
    with pytest.raises(NodeDefinitionError, match="return annotation is required"):

        def no_return(x: float):  # type: ignore[no-untyped-def]  # noqa: ANN202
            return x

        dec(no_return)
    with pytest.raises(NodeDefinitionError, match=r"\*args"):

        def varargs(*xs: float) -> float:
            return 0.0

        dec(varargs)
    with pytest.raises(NodeDefinitionError, match="not a port type or JSON-native"):

        def bad_return(x: float) -> object:
            return x

        dec(bad_return)
    with pytest.raises(NodeDefinitionError, match="unsupported parameter annotation"):

        def bad_param(x: type) -> float:
            return 0.0

        dec(bad_param)
    with pytest.raises(NodeDefinitionError, match="outputs= given but"):

        def none_named() -> None:
            return None

        node(id="t.bad.none", name="T", category="T", outputs=["a"])(none_named)
    with pytest.raises(NodeDefinitionError, match="fixed element types"):

        def var_tuple() -> tuple[float, ...]:
            return ()

        dec(var_tuple)
    with pytest.raises(NodeDefinitionError, match="do not match"):
        node(id="t.bad.names", name="T", category="T", outputs=["a"])(sample_nodes.swap.func)
    with pytest.raises(NodeDefinitionError, match="needs a unit"):

        def bare_quantity(q: u.Quantity) -> float:
            return 0.0

        dec(bare_quantity)
    with pytest.raises(NodeDefinitionError, match="not callable"):
        dec(3)  # type: ignore[arg-type]


def test_validate_params_coerces_and_enforces() -> None:
    m = sample_nodes.measure
    out = m.validate_params({"vmin": -100, "wrest": 1000, "tag": "b"})
    assert out["vmin"] == -100.0 and isinstance(out["vmin"], float)
    assert out["vmax"] == 200.0 and out["method"] == "direct" and out["weights"] is None
    assert out["wrest"].unit == u.AA and out["wrest"].value == 1000.0
    assert out["smoothing"] == sample_nodes.Smoothing()
    assert validate_call(m, {})["wrest"].value == 1215.67
    for bad in (
        {"vmin": 10},  # above max
        {"vmax": "x"},
        {"method": "other"},
        {"tag": "c"},  # not in choices
        {"nope": 1},  # unknown param
        {"smoothing": {"width": "wide"}},
    ):
        with pytest.raises(ValidationError):
            m.validate_params(bad)


def test_call_injects_inputs_params_and_context() -> None:
    spec = Spectrum1D(wave=np.arange(3.0), flux=np.ones(3))
    ctx = NullContext()
    result = sample_nodes.measure.call({"spec": spec}, {"wrest": 2000}, ctx)
    assert isinstance(result, Redshift) and result.z == 2.0
    assert ctx.progress_events == [(1.0, "done")]
    with pytest.raises(TypeError, match="unknown inputs"):
        sample_nodes.measure.call({"spec": spec, "bogus": 1})
    # Plain calls still work exactly like the undecorated function.
    assert sample_nodes.swap(1.0, 2.0) == (2.0, 1.0)
    assert sample_nodes.swap.call(params={"a": 5}) == (1.0, 5.0)


def test_null_context_records_everything(tmp_path) -> None:  # type: ignore[no-untyped-def]
    ctx = NullContext(workspace=tmp_path, inputs={"ref": 42})
    ctx.progress(2.0, None)
    ctx.log("info", "hello", n=1)
    ctx.preview({"a": 1})
    assert ctx.progress_events == [(1.0, None)]
    assert ctx.logs == [("info", "hello", {"n": 1})]
    assert ctx.previews == [{"a": 1}] and not ctx.is_cancelled()
    assert ctx.needs("ref") == 42 and ctx.workspace == tmp_path
    with pytest.raises(KeyError):
        ctx.needs("missing")
    assert ctx.scratch_dir.is_dir() and ctx.scratch_dir == ctx.scratch_dir
    assert isinstance(ctx, NodeContext)


def test_optional_annotated_and_literal_forms() -> None:
    @node(id="t.forms.all", name="T", category="T")
    def forms(
        a: Annotated[float, Param(min=0)] | None = None,
        b: Annotated[int | None, Param(widget="slider")] = 3,
        c: Literal[1, 2] = 1,
        d: Literal["x", 2] = "x",
        e: Annotated[list[int], Param(help="ints")] = [],  # noqa: B006 - schema default
    ) -> None:
        """Doc."""

    params = {p.name: p for p in forms.spec.params}
    assert params["a"].json_schema["anyOf"] == [{"minimum": 0, "type": "number"}, {"type": "null"}]
    assert params["a"].link_type == "astro.Float" and params["a"].required is False
    assert params["b"].widget == "slider" and params["b"].json_schema["default"] == 3
    assert params["c"].link_type == "astro.Int" and params["d"].link_type == "astro.Json"
    assert params["e"].description == "ints" and params["e"].json_schema["items"] == {
        "type": "integer"
    }
    assert forms.validate_params({"a": 1, "b": None}) == {
        "a": 1.0,
        "b": None,
        "c": 1,
        "d": "x",
        "e": [],
    }


def test_parse_docstring_styles() -> None:
    google = parse_docstring(
        "Title.\n\nArgs:\n    x (float): The x.\n    *rest: Others.\n\nReturns:\n    Sum.\n"
    )
    assert google.description == "Title." and google.params == {"x": "The x.", "rest": "Others."}
    assert google.returns == ["Sum."]
    numpy = parse_docstring(
        "Title.\n\nMore.\n\nParameters\n----------\nx : float\n    The x\n    continued.\n\n"
        "Returns\n-------\nfloat\n    Sum.\n"
    )
    assert numpy.description == "Title.\n\nMore." and numpy.params == {"x": "The x continued."}
    assert numpy.returns == ["Sum."]
    assert parse_docstring(None) == parse_docstring("   ")
    assert isinstance(NodeDef, type)
