"""``core.list.*`` nodes."""

from __future__ import annotations

from astro_canvas.sdk import node
from astro_canvas_core.types import Spectrum1D, SpectrumCollection


@node(id="core.list.collect", name="Collect Spectra", category="Lists", icon="layers")
def collect(
    a: Spectrum1D,
    b: Spectrum1D | None = None,
    c: Spectrum1D | None = None,
    d: Spectrum1D | None = None,
) -> SpectrumCollection:
    """Gather up to four spectra into one collection (unconnected inputs are skipped).

    Args:
        a: First spectrum.
        b: Second spectrum.
        c: Third spectrum.
        d: Fourth spectrum.

    Returns:
        A collection in input order.
    """
    return SpectrumCollection(items=[s for s in (a, b, c, d) if s is not None])
