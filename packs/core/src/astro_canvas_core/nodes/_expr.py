"""A tiny, safe arithmetic evaluator for ``core.math.expr`` (AST whitelist, no builtins)."""

from __future__ import annotations

import ast
import math
import operator
from collections.abc import Callable, Mapping
from typing import Any

_BINARY: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[Any], Any]] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}
FUNCTIONS: dict[str, Callable[..., float]] = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "sqrt": math.sqrt,
    "exp": math.exp,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "atan2": math.atan2,
    "floor": math.floor,
    "ceil": math.ceil,
}
CONSTANTS: dict[str, float] = {"pi": math.pi, "e": math.e, "inf": math.inf}


class ExpressionError(ValueError):
    """The expression uses something outside the arithmetic whitelist."""


def evaluate(expression: str, variables: Mapping[str, float]) -> float:
    """Evaluate ``expression`` with ``variables`` and the whitelisted functions/constants."""
    try:
        tree = ast.parse(expression.strip() or "0", mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"invalid expression: {exc.msg}") from None
    return float(_eval(tree.body, variables))


def _eval(node: ast.AST, variables: Mapping[str, float]) -> Any:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, int | float)
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in variables:
            return variables[node.id]
        if node.id in CONSTANTS:
            return CONSTANTS[node.id]
        raise ExpressionError(f"unknown name {node.id!r}")
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        return _BINARY[type(node.op)](_eval(node.left, variables), _eval(node.right, variables))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, variables))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and not node.keywords:
        if node.func.id not in FUNCTIONS:
            raise ExpressionError(f"unknown function {node.func.id!r}")
        return FUNCTIONS[node.func.id](*(_eval(a, variables) for a in node.args))
    raise ExpressionError(f"unsupported syntax: {type(node).__name__}")
