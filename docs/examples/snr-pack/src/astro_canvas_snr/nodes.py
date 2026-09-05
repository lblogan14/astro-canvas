"""``snr.*`` nodes: signal-to-noise of a spectrum, from ``rbcodes.utils.compute_SNR_1d``."""

from __future__ import annotations

import os
from typing import Annotated, Any

import numpy as np
from astro_canvas_core.types import Spectrum1D

from astro_canvas.sdk import NodeContext, Param, node


@node(
    id="snr.spectrum.estimate",
    name="Estimate SNR",
    category="Spectra/Measure",
    icon="activity",
    cost="cheap",
    preview="spectrum-thumb",
    outputs=("snr", "median"),
)
def estimate_snr(
    spec: Spectrum1D,
    # `Param` carries what the docstring cannot: the widget, the label, the limits. The *text*
    # comes from the Args section below -- a `help=` here would override it.
    binsize: Annotated[int, Param(min=1, max=64, label="Bin size")] = 3,
    wave_min: Annotated[float | None, Param(widget="wavelength", label="Lower bound")] = None,
    wave_max: Annotated[float | None, Param(widget="wavelength", label="Upper bound")] = None,
    robust: Annotated[bool, Param(label="Sigma-clipped median")] = False,
    sigma: Annotated[float, Param(min=1.0, max=10.0, step=0.5, label="Clip threshold")] = 3.0,
    ctx: NodeContext | None = None,
) -> tuple[Spectrum1D, float]:
    """Signal-to-noise per pixel of a rebinned spectrum.

    The spectrum is binned by ``binsize`` pixels, the ratio of flux to error is taken pixel by
    pixel, and the curve is reduced to one number: the median, or a sigma-clipped median when
    ``robust`` is set.

    Args:
        spec: Spectrum with an error array.
        binsize: Pixels combined before the ratio is taken (1 leaves the grid alone).
        wave_min: Lower bound of the range to measure; empty means the first pixel.
        wave_max: Upper bound of the range to measure; empty means the last pixel.
        robust: Reduce with a sigma-clipped median rather than a plain one.
        sigma: Clip threshold, in standard deviations, when ``robust`` is set.

    Returns:
        The SNR curve as a spectrum (its flux *is* the ratio), and the reduced value.
    """
    if spec.error is None:
        raise ValueError("the spectrum has no error array, and SNR needs one")

    # rbcodes' module imports `matplotlib.pyplot` when it loads, so the backend has to be
    # headless *before* the import: a node runs in a server process with no display.
    os.environ.setdefault("MPLBACKEND", "Agg")
    from rbcodes.utils.compute_SNR_1d import estimate_snr as rb_estimate_snr  # noqa: PLC0415

    lo, hi = _range(spec, wave_min, wave_max)
    if ctx is not None:
        ctx.log("info", "estimating SNR", binsize=binsize, lo=lo, hi=hi)

    result: dict[str, Any] = rb_estimate_snr(
        np.asarray(spec.wave, dtype=float),
        np.asarray(spec.flux, dtype=float),
        np.asarray(spec.error, dtype=float),
        binsize=int(binsize),
        snr_range=[lo, hi],
        verbose=False,
        plot=False,
        robust_median=bool(robust),
        sigma_clip_threshold=float(sigma),
    )

    curve = Spectrum1D(
        wave=np.asarray(result["wave"], dtype=float),
        flux=np.asarray(result["snr"], dtype=float),
        wave_unit=spec.wave_unit,
        flux_unit="SNR / pixel",
        frame=spec.frame,
        z=spec.z,
        meta={
            "binsize": int(binsize),
            "mean_snr": float(result["mean_snr"]),
            "median_snr": float(result["median_snr"]),
            "source": "rbcodes.utils.compute_SNR_1d.estimate_snr",
        },
    )
    reduced = float(result["robust_snr"] if robust else result["median_snr"])
    return curve, reduced


def _range(spec: Spectrum1D, lo: float | None, hi: float | None) -> tuple[float, float]:
    """rbcodes takes ``[-1, -1]`` for "the whole spectrum" and an exclusive range otherwise."""
    if lo is None and hi is None:
        return -1.0, -1.0
    first, last = float(np.min(spec.wave)), float(np.max(spec.wave))
    return (
        float(lo) if lo is not None else first - 1.0,
        float(hi) if hi is not None else last + 1.0,
    )
