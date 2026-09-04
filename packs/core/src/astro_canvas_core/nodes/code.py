"""``core.code.python``: run a user-written snippet as a node (design 5, 11).

The snippet is a normal Python function body executed with a restricted namespace: the declared
input ports arrive as local names, ``ctx`` is the usual ``NodeContext``, ``print`` goes to the
node log, and whatever the snippet assigns to the declared output names comes back as this node's
outputs. Imports are checked against a denylist unless the pack manager's security level is
``permissive``.

The sandbox is a speed bump, not a jail -- Python cannot be made safe against a determined
attacker in-process. The real protection is the **trust gate**: an imported workflow's code nodes
do not run at all until the user has read the snippet and trusted its hash
(``astro_canvas.manager.trust``). This module keeps honest snippets honest and makes the common
mistakes (``import os``, ``open(...)``) loud.
"""

from __future__ import annotations

import ast
import builtins
import io
import os
from contextlib import redirect_stdout
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from astro_canvas.sdk import (
    ANY_TYPE,
    DynamicPorts,
    NodeContext,
    Param,
    PortType,
    node,
    unwrap_scalar,
)

SECURITY_ENV_VAR = "ASTRO_CANVAS_CODE_SECURITY"
"""Set by the server from the manager's security level; workers inherit it."""

BLOCKED_MODULES: frozenset[str] = frozenset(
    {
        "ctypes",
        "http",
        "importlib",
        "multiprocessing",
        "os",
        "pathlib",
        "pickle",
        "requests",
        "shutil",
        "socket",
        "socketserver",
        "ssl",
        "subprocess",
        "sys",
        "urllib",
        "webbrowser",
        "httpx",
    }
)
"""Modules a snippet may not import outside ``permissive`` mode: process, filesystem, network."""

BLOCKED_BUILTINS: frozenset[str] = frozenset(
    {"breakpoint", "compile", "eval", "exec", "exit", "help", "input", "open", "quit"}
)

DEFAULT_SOURCE = '''"""Write Python here. Inputs arrive as names; assign the declared outputs."""

out = 0.0
'''

MAX_LOG_CHARS = 20_000


class CodeNodeError(RuntimeError):
    """The snippet was rejected before running, or failed while running."""


class CodePort(BaseModel):
    """One declared port of a code node. A half-filled row is valid so editing never errors."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="", description="Port name; must be a Python identifier.")
    type: str = Field(default=ANY_TYPE, description="Port type id.")


def _security_level() -> str:
    return os.environ.get(SECURITY_ENV_VAR, "standard").strip().lower()


def _guarded_import(permissive: bool) -> Any:
    real_import = builtins.__import__

    def guarded(name: str, *args: Any, **kwargs: Any) -> Any:
        root = name.split(".", 1)[0]
        if not permissive and root in BLOCKED_MODULES:
            raise CodeNodeError(
                f"importing {root!r} is not allowed at this security level; "
                "set Manager > Settings > Security to 'permissive' to allow it"
            )
        return real_import(name, *args, **kwargs)

    return guarded


def restricted_builtins(*, permissive: bool = False) -> dict[str, Any]:
    """A ``__builtins__`` mapping with the process- and filesystem-shaped names removed."""
    allowed = {
        name: getattr(builtins, name)
        for name in dir(builtins)
        if not name.startswith("_") and (permissive or name not in BLOCKED_BUILTINS)
    }
    allowed["__import__"] = _guarded_import(permissive)
    allowed["__name__"] = "astro_canvas_snippet"
    return allowed


def check_source(source: str, *, permissive: bool = False) -> ast.Module:
    """Parse the snippet and reject the syntax the sandbox cannot police.

    Raises:
        CodeNodeError: on a syntax error, or on an import of a blocked module. Import statements
            are checked statically as well as at runtime so the failure names the line.
    """
    try:
        tree = ast.parse(source or "", mode="exec")
    except SyntaxError as exc:
        raise CodeNodeError(f"line {exc.lineno}: {exc.msg}") from None
    if permissive:
        return tree
    for item in ast.walk(tree):
        names: list[str] = []
        if isinstance(item, ast.Import):
            names = [alias.name for alias in item.names]
        elif isinstance(item, ast.ImportFrom) and item.module and item.level == 0:
            names = [item.module]
        for name in names:
            root = name.split(".", 1)[0]
            if root in BLOCKED_MODULES:
                raise CodeNodeError(
                    f"line {getattr(item, 'lineno', 0)}: importing {root!r} is not allowed at "
                    "this security level"
                )
    return tree


@node(
    id="core.code.python",
    name="Python",
    category="Code",
    cost="auto",
    icon="code",
    editor="code",
    dynamic_ports=DynamicPorts(inputs="inputs", outputs="outputs", values="values"),
)
def python_code(
    ctx: NodeContext,
    values: dict[str, Any],
    source: Annotated[str, Param(widget="code", label="Source")] = DEFAULT_SOURCE,
    inputs: Annotated[list[CodePort], Param(widget="ports", label="Inputs")] = [],  # noqa: B006
    outputs: Annotated[list[CodePort], Param(widget="ports", label="Outputs")] = [],  # noqa: B006
) -> dict[str, Any]:
    """Run a Python snippet with typed input and output ports.

    Each entry of *Inputs* adds an input port whose value is bound to that name inside the
    snippet; each entry of *Outputs* adds an output port read back from the name of the same
    spelling after the snippet has run. ``ctx`` is available for ``ctx.progress(...)`` and
    ``ctx.log(...)``, and anything printed lands in the node's log.

    Args:
        source: The snippet. Runs top to bottom with the input names already bound.
        inputs: Input ports as ``[{"name": "spec", "type": "astro.Spectrum1D"}]``.
        outputs: Output ports in the same shape; the snippet must assign each name.

    Returns:
        One value per declared output port.
    """
    permissive = _security_level() == "permissive"
    tree = check_source(source, permissive=permissive)
    declared = [port.name for port in outputs if port.name]
    # Boxing types (``astro.Float``, ``astro.Any``, ...) arrive as wrappers; a snippet wants the
    # number or the object, while a real port type (``Spectrum1D``) is handed over as it is.
    bound = {
        name: unwrap_scalar(value) if isinstance(value, PortType) else value
        for name, value in values.items()
    }
    namespace: dict[str, Any] = {
        "__builtins__": restricted_builtins(permissive=permissive),
        "ctx": ctx,
        **bound,
    }
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            exec(compile(tree, filename="<astro-canvas code node>", mode="exec"), namespace)  # noqa: S102
    except CodeNodeError:
        raise
    except Exception as exc:
        line = _failing_line(exc)
        where = f"line {line}: " if line else ""
        raise CodeNodeError(f"{where}{type(exc).__name__}: {exc}") from exc
    finally:
        printed = buffer.getvalue()
        if printed.strip():
            ctx.log("info", printed[:MAX_LOG_CHARS].rstrip())
    missing = [name for name in declared if name not in namespace]
    if missing:
        raise CodeNodeError(f"the snippet did not assign {', '.join(missing)}")
    return {name: namespace[name] for name in declared}


def _failing_line(exc: BaseException) -> int | None:
    """The snippet line an exception came from, ignoring frames outside the snippet."""
    tb = exc.__traceback__
    line: int | None = None
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<astro-canvas code node>":
            line = tb.tb_lineno
        tb = tb.tb_next
    if line is None and isinstance(exc, SyntaxError):  # pragma: no cover - caught in check_source
        line = exc.lineno
    return line


__all__ = [
    "BLOCKED_BUILTINS",
    "BLOCKED_MODULES",
    "DEFAULT_SOURCE",
    "SECURITY_ENV_VAR",
    "CodeNodeError",
    "CodePort",
    "check_source",
    "python_code",
    "restricted_builtins",
]
