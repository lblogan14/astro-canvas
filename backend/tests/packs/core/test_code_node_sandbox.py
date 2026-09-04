"""``core.code.python``: dynamic ports, the restricted namespace, logs and error reporting."""

from __future__ import annotations

from typing import Any

import pytest
from astro_canvas_core.nodes.code import (
    BLOCKED_MODULES,
    SECURITY_ENV_VAR,
    CodeNodeError,
    check_source,
    python_code,
    restricted_builtins,
)
from astro_canvas_core.types import Spectrum1D

from astro_canvas.sdk import NullContext, effective_ports


def run(
    source: str,
    inputs: dict[str, Any] | None = None,
    outputs: list[dict[str, str]] | None = None,
    ctx: NullContext | None = None,
) -> dict[str, Any]:
    values = inputs or {}
    params = {
        "source": source,
        "inputs": [{"name": name} for name in values],
        "outputs": outputs if outputs is not None else [{"name": "out"}],
    }
    return dict(python_code.call(values, params, ctx or NullContext()))


def test_a_snippet_reads_its_inputs_and_assigns_its_outputs() -> None:
    assert run("out = a + b", {"a": 2.0, "b": 3.0}) == {"out": 5.0}


def test_two_outputs_come_back_by_name() -> None:
    result = run(
        "lo = min(xs)\nhi = max(xs)",
        {"xs": [3, 1, 2]},
        outputs=[{"name": "lo"}, {"name": "hi"}],
    )
    assert result == {"lo": 1, "hi": 3}


def test_a_port_type_input_arrives_unwrapped_but_intact() -> None:
    spec = Spectrum1D(wave=[1.0, 2.0, 3.0], flux=[1.0, 1.0, 1.0])
    result = run("n = len(spec.wave)", {"spec": spec}, outputs=[{"name": "n"}])
    assert result == {"n": 3}


def test_the_declared_ports_are_what_the_engine_sees() -> None:
    params = {
        "inputs": [{"name": "spec", "type": "astro.Spectrum1D"}],
        "outputs": [{"name": "ew", "type": "astro.Float"}],
    }
    inputs, outputs = effective_ports(python_code.spec, params)
    assert [(p.name, p.type) for p in inputs] == [("spec", "astro.Spectrum1D")]
    assert [(p.name, p.type) for p in outputs] == [("ew", "astro.Float")]


def test_print_goes_to_the_node_log() -> None:
    ctx = NullContext()
    run("print('hello from the snippet')\nout = 1", ctx=ctx)
    assert any("hello from the snippet" in message for _level, message, _f in ctx.logs)


def test_ctx_is_available_to_the_snippet() -> None:
    ctx = NullContext()
    run("ctx.progress(0.5, 'halfway')\nout = 1", ctx=ctx)
    assert ctx.progress_events == [(0.5, "halfway")]


@pytest.mark.parametrize("module", ["os", "subprocess", "socket", "pathlib", "pickle"])
def test_dangerous_imports_are_refused(module: str) -> None:
    assert module in BLOCKED_MODULES
    with pytest.raises(CodeNodeError, match="not allowed"):
        run(f"import {module}\nout = 1")


def test_from_imports_are_refused_too() -> None:
    with pytest.raises(CodeNodeError, match="not allowed"):
        run("from os import getcwd\nout = 1")


def test_a_dynamic_import_is_refused_at_runtime() -> None:
    """The static check cannot see ``__import__('os')``; the guarded import can."""
    with pytest.raises(CodeNodeError, match="not allowed"):
        run("m = __import__('os')\nout = 1")


def test_science_imports_still_work() -> None:
    assert run("import numpy as np\nout = float(np.sum([1, 2, 3]))") == {"out": 6.0}


def test_open_is_not_in_the_namespace() -> None:
    with pytest.raises(CodeNodeError, match="open"):
        run("out = open('secrets.txt').read()")


def test_permissive_lets_a_snippet_import_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECURITY_ENV_VAR, "permissive")
    assert run("import os\nout = isinstance(os.sep, str)") == {"out": True}


def test_restricted_builtins_keep_the_useful_ones() -> None:
    allowed = restricted_builtins()
    assert {"len", "sum", "range", "float", "ValueError"} <= set(allowed)
    assert "open" not in allowed and "eval" not in allowed


def test_a_syntax_error_names_the_line() -> None:
    with pytest.raises(CodeNodeError, match="line 2"):
        check_source("out = 1\nout = = 2")


def test_a_runtime_error_names_the_snippet_line() -> None:
    with pytest.raises(CodeNodeError, match="line 3"):
        run("a = 1\nb = 2\nout = a / 0")


def test_an_unassigned_output_is_reported() -> None:
    with pytest.raises(CodeNodeError, match="did not assign missing"):
        run("out = 1", outputs=[{"name": "missing"}])
