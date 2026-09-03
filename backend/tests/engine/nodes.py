"""Nodes used by the engine tests (also importable inside worker processes)."""

from __future__ import annotations

import time
from typing import Annotated

import numpy as np
from astro_canvas_core import types as T
from astro_canvas_core.types import Any as AnyValue

from astro_canvas.sdk import (
    ExpandNode,
    Expansion,
    NodeContext,
    NodeRegistry,
    Param,
    discover,
    node,
)


@node(id="test.spec.make", name="Make Spectrum", category="Test")
def make_spectrum(n: int = 100, scale: float = 1.0) -> T.Spectrum1D:
    """A synthetic spectrum with ``n`` points."""
    wave = np.linspace(1000.0, 2000.0, n)
    return T.Spectrum1D(wave=wave, flux=np.sin(wave / 50.0) * scale)


@node(id="test.sleep", name="Sleep", category="Test", cost="expensive")
def sleep(x: float = 0.0, seconds: float = 30.0, ctx: NodeContext | None = None) -> float:
    """Block for ``seconds`` (cooperatively when a context is given) and return ``x``."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if ctx is not None and ctx.is_cancelled():
            return x
        time.sleep(0.05)
    return x


@node(id="test.sleep.hard", name="Hard Sleep", category="Test", cost="expensive")
def sleep_hard(x: float = 0.0, seconds: float = 30.0) -> float:
    """Block for ``seconds`` without ever checking for cancellation."""
    time.sleep(seconds)
    return x


@node(id="test.slow.auto", name="Slow Auto", category="Test", cost="auto")
def slow_auto(x: float = 0.0, seconds: float = 0.0) -> float:
    """Sleep ``seconds`` then return ``x`` (used to test auto cost promotion)."""
    time.sleep(seconds)
    return x


@node(id="test.fail", name="Fail", category="Test")
def fail(x: float = 0.0, message: str = "boom") -> float:
    """Always raise ``RuntimeError(message)``."""
    raise RuntimeError(message)


@node(id="test.switch", name="Switch", category="Test", lazy=("a", "b"))
def switch(
    a: T.Float,
    b: T.Float,
    pick: Annotated[str, Param(choices=["a", "b"])] = "a",
    ctx: NodeContext | None = None,
) -> float:
    """Return input ``a`` or ``b``; only the picked branch is computed."""
    assert ctx is not None
    value: T.Float = ctx.needs(pick)
    return value.value


@node(id="test.any.make", name="Make Any", category="Test")
def make_any(text: str = "x") -> AnyValue:
    """An unserialisable in-process value."""
    return AnyValue(value={"text": text, "obj": object()})


@node(id="test.any.read", name="Read Any", category="Test")
def read_any(value: AnyValue) -> str:
    """Read back the text from an ``astro.Any``."""
    return str(value.value["text"])


@node(id="test.any.read.expensive", name="Read Any Expensive", category="Test", cost="expensive")
def read_any_expensive(value: AnyValue) -> str:
    """An expensive consumer of ``astro.Any`` (must fall back to the thread executor)."""
    return str(value.value["text"])


@node(id="test.expand.sum3", name="Expand Sum", category="Test", expand=True)
def expand_sum(x: float = 1.0, k: int = 3) -> float:
    """Expand into ``k`` chained ``core.math.expr`` nodes adding ``x`` each."""
    nodes: dict[str, ExpandNode] = {}
    prev: tuple[str, str] | None = None
    for i in range(k):
        inputs = {"y": prev} if prev else {}
        nodes[f"s{i}"] = ExpandNode(
            type="core.math.expr",
            params={"expression": "x + y", "x": x, **({} if prev else {"y": 0.0})},
            inputs=inputs,
        )
        prev = (f"s{i}", "out")
    assert prev is not None
    return Expansion(nodes=nodes, outputs={"out": prev})  # type: ignore[return-value]


@node(id="test.progress", name="Progress", category="Test", cost="expensive")
def progress(steps: int = 3, ctx: NodeContext | None = None) -> int:
    """Report progress and a log line from wherever it runs."""
    for i in range(steps):
        if ctx is not None:
            ctx.progress((i + 1) / steps, f"step {i + 1}")
    if ctx is not None:
        ctx.log("info", "done", steps=steps)
        (ctx.scratch_dir / "note.txt").write_text("hi", encoding="utf-8")
    return steps


_COUNTER = {"n": 0}


@node(
    id="test.fingerprint",
    name="Fingerprint",
    category="Test",
    fingerprint=lambda **_: _COUNTER["n"],
)
def fingerprinted(x: float = 0.0) -> float:
    """Its cache key changes whenever ``_COUNTER['n']`` changes."""
    return x


def bump_fingerprint() -> None:
    _COUNTER["n"] += 1


def build_registry() -> NodeRegistry:
    """Core packs plus these test nodes (used as ``registry_factory`` in worker processes)."""
    import sys

    registry = discover().registry
    registry.add_module(sys.modules[__name__], pack="test")
    return registry
