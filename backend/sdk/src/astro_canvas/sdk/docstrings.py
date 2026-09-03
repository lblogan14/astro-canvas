"""Docstring parsing (Google and NumPy styles) through griffe."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any

_NO_WARNINGS: dict[str, Any] = {"warnings": False}
_PER_STYLE: Any = {"google": _NO_WARNINGS, "numpy": _NO_WARNINGS, "sphinx": _NO_WARNINGS}


@dataclass(frozen=True)
class DocInfo:
    """Description text, per-parameter descriptions, and return descriptions."""

    description: str = ""
    params: dict[str, str] = field(default_factory=dict)
    returns: list[str] = field(default_factory=list)


def parse_docstring(text: str | None) -> DocInfo:
    """Parse ``text`` (Google or NumPy style, auto-detected) into a ``DocInfo``.

    Never raises: an empty or unparsable docstring yields an empty ``DocInfo``.
    """
    if not text or not text.strip():
        return DocInfo()
    import griffe  # noqa: PLC0415 - lazy: griffe is only needed at decoration time

    docstring = griffe.Docstring(inspect.cleandoc(text))
    sections = griffe.parse_auto(docstring, default="google", per_style_options=_PER_STYLE)
    description_parts: list[str] = []
    params: dict[str, str] = {}
    returns: list[str] = []
    for section in sections:
        kind = section.kind.value
        if kind == "text":
            description_parts.append(str(section.value).strip())
        elif kind in {"parameters", "other parameters"}:
            for item in section.value:
                params[str(item.name).lstrip("*")] = " ".join(str(item.description).split())
        elif kind == "returns":
            returns.extend(" ".join(str(item.description).split()) for item in section.value)
    return DocInfo(
        description="\n\n".join(p for p in description_parts if p), params=params, returns=returns
    )
