"""Documented sample nodes used by the decorator and golden-schema tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, NamedTuple

import astropy.units as u
from astro_canvas_core.types import Redshift, Spectrum1D
from pydantic import BaseModel

from astro_canvas.sdk import NodeContext, Param, node


class Smoothing(BaseModel):
    """Kernel settings."""

    kernel: Literal["boxcar", "gaussian"] = "boxcar"
    width: int = 3


@node(
    id="sample.spec.measure",
    name="Measure Sample",
    category="Samples/Measure",
    cost="expensive",
    version="1.2.0",
    icon="ruler",
    preview="ew-summary",
    editor="range-editor",
    lazy=("reference",),
    experimental=True,
)
def measure(  # noqa: PLR0917 - node signatures are wide by design
    spec: Spectrum1D,
    reference: Spectrum1D | None = None,
    vmin: Annotated[float, Param(unit="km/s", min=-5000, max=0, widget="slider", step=10)] = -200.0,
    vmax: Annotated[float, Param(unit="km/s", min=0, max=5000, label="Upper limit")] = 200.0,
    method: Literal["direct", "aod"] = "direct",
    weights: list[float] | None = None,
    snr: bool = False,
    tag: Annotated[str, Param(choices=["a", "b"], help="Custom help wins.", advanced=True)] = "a",
    smoothing: Smoothing = Smoothing(),  # noqa: B008 - pydantic default is copied per call
    wrest: u.Quantity[u.AA] = 1215.67 * u.AA,
    ctx: NodeContext | None = None,
) -> Redshift:
    """Measure a sample quantity on a spectrum.

    The long description survives in ``NodeSpec.description``.

    Args:
        spec: Continuum-normalized spectrum slice in velocity space.
        reference: Optional reference spectrum, only fetched when needed.
        vmin: Lower integration limit.
        vmax: Upper integration limit.
        method: Integration method.
        weights: Optional per-pixel weights.
        snr: Also estimate the signal-to-noise ratio.
        tag: Ignored because ``Param.help`` is set.
        smoothing: Kernel applied before measuring.
        wrest: Rest wavelength of the line.

    Returns:
        A redshift estimate.
    """
    if ctx is not None:
        ctx.progress(1.0, "done")
    return Redshift(z=float(wrest.to_value(u.AA)) / 1000.0 + vmin * 0 + vmax * 0)


class Split(NamedTuple):
    blue: Spectrum1D
    red: Spectrum1D
    pivot: float


@node(id="sample.spec.split", name="Split", category="Samples/Transform")
def split(spec: Spectrum1D, pivot: float) -> Split:
    """Split a spectrum at ``pivot``.

    Parameters
    ----------
    spec : Spectrum1D
        The spectrum to split.
    pivot : float
        Split wavelength.
    """
    keep = spec.wave < pivot
    return Split(
        spec.model_copy(update={"wave": spec.wave[keep], "flux": spec.flux[keep]}),
        spec.model_copy(update={"wave": spec.wave[~keep], "flux": spec.flux[~keep]}),
        pivot,
    )


@dataclass
class Stats:
    mean: float
    count: int
    label: str


@node(id="sample.stats.describe", name="Describe", category="Samples/Stats")
def describe(spec: Spectrum1D) -> Stats:
    """Basic statistics of the flux."""
    return Stats(float(spec.flux.mean()), int(spec.flux.size), "flux")


@node(id="sample.pair.swap", name="Swap", category="Samples/Transform", outputs=("second", "first"))
def swap(a: float, b: float = 1.0) -> tuple[float, float]:
    """Swap two numbers.

    Returns:
        b: The second input.
        a: The first input.
    """
    return b, a


@node(id="sample.async.echo", name="Echo", category="Samples/Async")
async def echo(text: str = "") -> str:
    """Return the text asynchronously."""
    return text
