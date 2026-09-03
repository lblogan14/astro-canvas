"""``core.math.*`` nodes."""

from __future__ import annotations

from typing import Annotated

from astro_canvas.sdk import Param, node
from astro_canvas_core.nodes._expr import evaluate


@node(id="core.math.constant", name="Constant", category="Math", icon="hash", version="1.0.0")
def constant(value: Annotated[float, Param(widget="number")] = 0.0) -> float:
    """Emit a constant number.

    Args:
        value: The number to output.

    Returns:
        The same number, available as a Float port.
    """
    return value


@node(id="core.math.expr", name="Expression", category="Math", icon="function-square")
def expr(
    expression: Annotated[str, Param(widget="code", label="Expression")] = "x",
    x: float = 0.0,
    y: float = 0.0,
    z: float = 0.0,
) -> float:
    """Evaluate an arithmetic expression of ``x``, ``y`` and ``z``.

    Supports ``+ - * / // % **``, parentheses, the constants ``pi`` and ``e``, and the functions
    ``abs, min, max, round, sqrt, exp, log, log10, sin, cos, tan, atan2, floor, ceil``.

    Args:
        expression: The expression, for example ``sqrt(x**2 + y**2)``.
        x: Value bound to ``x``.
        y: Value bound to ``y``.
        z: Value bound to ``z``.

    Returns:
        The evaluated number.
    """
    return evaluate(expression, {"x": x, "y": y, "z": z})
