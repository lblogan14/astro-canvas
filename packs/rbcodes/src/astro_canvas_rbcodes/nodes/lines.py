"""``rbcodes.lines.*`` nodes: atomic line lists and transition lookup (``rb_setline``)."""

from __future__ import annotations

from typing import Annotated, Literal

import numpy as np
from astro_canvas_core.types import LineList, Transition

from astro_canvas.sdk import Param, node
from astro_canvas_rbcodes.kernels.setline import LineListName
from astro_canvas_rbcodes.nodes._common import (
    line_list_arrays,
    setline,
    transition_from_setline,
)

LineListParam = Annotated[
    LineListName,
    Param(label="Line list", help="One of the 16 lists bundled with rbcodes (IGM/lines)."),
]


@node(id="rbcodes.lines.line_list", name="Line List", category="rbcodes/Lines", icon="list")
def line_list(name: LineListParam = "atom") -> LineList:
    """Load one of rbcodes' atomic line lists (``rb_setline.read_line_list``).

    ``atom`` is the full atomic table with oscillator strengths and damping constants; the others
    are curated subsets (LLS, DLA, LBG, galaxy emission/absorption, AGN, HI recombination, EUV).

    Args:
        name: Which list to load.

    Returns:
        The transitions as parallel ``wrest``/``name``/``fval`` arrays (``gamma`` for ``atom``).
    """
    wrest, names, fval, gamma = line_list_arrays(name)
    return LineList(wrest=wrest, name=names, fval=fval, gamma=gamma, source=name)


@node(
    id="rbcodes.lines.find_transition",
    name="Find Transition",
    category="rbcodes/Lines",
    icon="search",
)
def find_transition(
    linelist: LineList,
    wrest: Annotated[float, Param(unit="Angstrom", widget="wavelength", min=0.0)] = 2796.35,
    method: Annotated[
        Literal["closest", "Exact", "Name"], Param(label="Match", help="rb_setline method")
    ] = "closest",
    name: Annotated[
        str, Param(label="Name", help="Species name for method=Name, e.g. HI 1215")
    ] = "",
) -> Transition:
    """Pick one transition from a line list by wavelength or name (``rb_setline``).

    Args:
        linelist: The list to search (from ``Line List``).
        wrest: Rest wavelength to match (Angstrom).
        method: ``closest`` takes the nearest line, ``Exact`` needs a match within 0.001 A,
            ``Name`` matches the species label.
        name: Species label used by ``method=Name``.

    Returns:
        The matched transition (rest wavelength, oscillator strength, damping constant).
    """
    names = linelist.name
    if method == "Name":
        if not name.strip():
            raise ValueError("method=Name needs a species name, e.g. 'HI 1215'")
        hits = np.where(names == name.strip())[0]
        if hits.size == 0:
            raise ValueError(f"no line named {name!r} in the {linelist.source or 'given'} list")
        idx = int(hits[0])
    elif method == "Exact":
        hits = np.where(np.abs(linelist.wrest - wrest) < 1e-3)[0]
        if hits.size == 0:
            raise ValueError(f"no line within 0.001 A of {wrest} in the list; try method=closest")
        idx = int(hits[0])
    else:
        idx = int(np.abs(linelist.wrest - wrest).argmin())
    gamma = float(linelist.gamma[idx]) if linelist.gamma is not None else None
    return Transition(
        name=str(names[idx]),
        wrest=float(linelist.wrest[idx]),
        fval=float(linelist.fval[idx]),
        gamma=gamma,
    )


def lookup(wrest: float, method: str, linelist: str) -> Transition:
    """Transition lookup through rbcodes' ``rb_setline`` (shared by the absorption nodes)."""
    return transition_from_setline(setline(wrest, method, linelist=linelist))


__all__ = ["LineListParam", "find_transition", "line_list", "lookup"]
