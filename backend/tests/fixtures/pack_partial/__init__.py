"""Fixture pack that registers one node and then blows up during registration."""

from __future__ import annotations

from astro_canvas.sdk import PackRegistry, node


@node(id="partial.math.one", name="One", category="Fixture")
def one() -> float:
    """Return one."""
    return 1.0


def register(registry: PackRegistry) -> None:
    registry.add(one)
    raise RuntimeError("partial registration failure")
