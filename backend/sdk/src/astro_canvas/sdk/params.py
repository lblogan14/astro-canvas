"""``Param``: widget metadata attached to node parameters through ``Annotated``."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

Widget = Literal[
    "slider",
    "select",
    "file",
    "color",
    "range",
    "wavelength",
    "redshift",
    "text",
    "markdown",
    "code",
    "number",
    "checkbox",
]
"""Widget hints understood by the frontend. Unknown widgets fall back to a schema-driven default."""


@dataclass(frozen=True)
class Param:
    """Presentation and validation hints for a node parameter.

    Use inside ``Annotated``::

        vmin: Annotated[float, Param(unit="km/s", min=-5000, max=0)] = -200.0

    ``min``/``max`` become JSON Schema ``minimum``/``maximum`` and are enforced when the node is
    called; ``choices`` becomes ``enum``; ``unit`` is emitted as ``x-unit``; ``help`` overrides the
    docstring description and ``label`` overrides the generated title.
    """

    unit: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: Sequence[object] | None = None
    widget: Widget | str | None = None
    advanced: bool = False
    label: str | None = None
    help: str | None = None
    _choices: tuple[object, ...] | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.choices is not None:
            object.__setattr__(self, "_choices", tuple(self.choices))
            object.__setattr__(self, "choices", self._choices)
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"Param.min ({self.min}) must not exceed Param.max ({self.max})")
        if self.step is not None and self.step <= 0:
            raise ValueError("Param.step must be positive")
