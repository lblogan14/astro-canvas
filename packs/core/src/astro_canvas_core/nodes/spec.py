"""``core.spec.*`` nodes: frame transforms and cropping of ``Spectrum1D``."""

from __future__ import annotations

from typing import Annotated

import numpy as np
import numpy.typing as npt
from astropy.constants import c as _c

from astro_canvas.sdk import Param, node
from astro_canvas_core.types import Continuum, Spectrum1D

C_KMS = float(_c.to_value("km/s"))


def _select(spec: Spectrum1D, keep: npt.NDArray[np.bool_]) -> Spectrum1D:
    update = {
        name: getattr(spec, name)[keep]
        for name in ("wave", "flux", "error", "continuum")
        if getattr(spec, name) is not None
    }
    return spec.model_copy(update=update)


@node(id="core.spec.crop", name="Crop Spectrum", category="Spectra/Transform", icon="scissors")
def crop(
    spec: Spectrum1D,
    lo: Annotated[float, Param(widget="wavelength", label="Lower bound")],
    hi: Annotated[float, Param(widget="wavelength", label="Upper bound")],
) -> Spectrum1D:
    """Keep only the pixels whose axis value lies in ``[lo, hi]``.

    Bounds are in the spectrum's own axis unit (wavelength, or km/s in the velocity frame).

    Args:
        spec: Input spectrum.
        lo: Lower bound (inclusive).
        hi: Upper bound (inclusive).

    Returns:
        The cropped spectrum; empty if the window misses the data.
    """
    if hi < lo:
        lo, hi = hi, lo
    return _select(spec, (spec.wave >= lo) & (spec.wave <= hi))


@node(
    id="core.spec.to_rest_frame",
    name="To Rest Frame",
    category="Spectra/Transform",
    icon="arrow-left-right",
)
def to_rest_frame(
    spec: Spectrum1D,
    z: Annotated[float, Param(widget="redshift", min=-0.1, max=20.0, step=1e-4)] = 0.0,
) -> Spectrum1D:
    """Divide the observed wavelength axis by ``1 + z``.

    Args:
        spec: Observed-frame spectrum.
        z: Redshift of the source.

    Returns:
        The rest-frame spectrum with ``frame='rest'`` and ``z`` recorded.
    """
    if spec.frame != "observed":
        raise ValueError(f"to_rest_frame expects an observed-frame spectrum, got {spec.frame!r}")
    return spec.model_copy(update={"wave": spec.wave / (1.0 + z), "frame": "rest", "z": z})


@node(id="core.spec.to_velocity", name="To Velocity", category="Spectra/Transform", icon="gauge")
def to_velocity(
    spec: Spectrum1D,
    wrest: Annotated[float, Param(unit="Angstrom", widget="wavelength", min=0.0)],
    z: Annotated[float, Param(widget="redshift", min=-0.1, max=20.0)] = 0.0,
) -> Spectrum1D:
    """Convert the wavelength axis to velocity (km/s) relative to a transition at redshift ``z``.

    Uses ``v = c (lambda / (wrest (1 + z)) - 1)`` like rbcodes' ``rb_spec``. Rest-frame input is
    handled by treating ``z`` as already applied.

    Args:
        spec: Observed- or rest-frame spectrum.
        wrest: Rest wavelength of the transition.
        z: Redshift of the absorber (ignored for rest-frame input).

    Returns:
        The spectrum on a velocity axis (``frame='velocity'``, ``wave_unit='km / s'``).
    """
    if spec.frame == "velocity":
        raise ValueError("spectrum is already in the velocity frame")
    z_applied = z if spec.frame == "observed" else 0.0
    center = wrest * (1.0 + z_applied)
    velocity = C_KMS * (spec.wave / center - 1.0)
    return spec.model_copy(
        update={
            "wave": velocity,
            "frame": "velocity",
            "wave_unit": "km / s",
            "z": z if spec.frame == "observed" else spec.z,
            "v0_wrest": wrest,
        }
    )


def _bin_mean(values: npt.NDArray[np.float64], factor: int) -> npt.NDArray[np.float64]:
    n = (values.shape[0] // factor) * factor
    return np.nanmean(values[:n].reshape(-1, factor), axis=1)


@node(id="core.spec.rebin", name="Rebin Spectrum", category="Spectra/Transform", icon="rows-3")
def rebin(
    spec: Spectrum1D,
    factor: Annotated[int, Param(min=1, max=1000, label="Bin factor")] = 2,
) -> Spectrum1D:
    """Bin ``factor`` adjacent pixels together (mean flux, errors added in quadrature / n).

    Args:
        spec: Input spectrum.
        factor: Number of pixels per output bin; trailing pixels that do not fill a bin are dropped.

    Returns:
        The rebinned spectrum (``wave`` is the bin centre).
    """
    if factor <= 1 or len(spec) < factor:
        return spec
    update: dict[str, npt.NDArray[np.float64]] = {
        "wave": _bin_mean(spec.wave, factor),
        "flux": _bin_mean(spec.flux, factor),
    }
    if spec.error is not None:
        n = (spec.error.shape[0] // factor) * factor
        with np.errstate(all="ignore"):
            update["error"] = (
                np.sqrt(np.nansum(spec.error[:n].reshape(-1, factor) ** 2, axis=1)) / factor
            )
    if spec.continuum is not None:
        update["continuum"] = _bin_mean(spec.continuum, factor)
    return spec.model_copy(update=update)


@node(id="core.spec.smooth", name="Smooth Spectrum", category="Spectra/Transform", icon="waves")
def smooth(
    spec: Spectrum1D,
    width: Annotated[float, Param(min=0.1, max=1000.0, unit="pixel", label="Width")] = 3.0,
    kernel: Annotated[str, Param(choices=["boxcar", "gaussian"], label="Kernel")] = "boxcar",
) -> Spectrum1D:
    """Convolve the flux with a boxcar (``width`` pixels) or Gaussian (sigma ``width`` pixels).

    NaNs are ignored by normalising with the kernel's coverage; errors are smoothed in quadrature.

    Args:
        spec: Input spectrum.
        width: Boxcar width or Gaussian sigma, in pixels.
        kernel: Kernel shape.

    Returns:
        The smoothed spectrum on the same grid.
    """
    if kernel == "gaussian":
        half = int(max(1.0, np.ceil(4.0 * width)))
        x = np.arange(-half, half + 1, dtype=np.float64)
        k = np.exp(-0.5 * (x / width) ** 2)
    else:
        size = max(1, int(round(width)))
        k = np.ones(size, dtype=np.float64)
    k = k / k.sum()

    def convolve(values: npt.NDArray[np.float64], squared: bool = False) -> npt.NDArray[np.float64]:
        finite = np.isfinite(values)
        filled = np.where(finite, values, 0.0)
        if squared:
            filled = filled**2
        weight = np.convolve(finite.astype(np.float64), k, mode="same")
        total = np.convolve(filled, k if not squared else k**2, mode="same")
        with np.errstate(all="ignore"):
            out = np.where(weight > 0, total / (weight if not squared else weight**2), np.nan)
        return np.sqrt(out) if squared else out

    update: dict[str, npt.NDArray[np.float64]] = {"flux": convolve(spec.flux)}
    if spec.error is not None:
        update["error"] = convolve(spec.error, squared=True)
    return spec.model_copy(update=update)


def _air_vac_factor(wave_aa: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
    with np.errstate(all="ignore"):
        sigma_sq = (1e4 / wave_aa) ** 2
        factor = 1.0 + 5.792105e-2 / (238.0185 - sigma_sq) + 1.67918e-3 / (57.362 - sigma_sq)
    return np.where(wave_aa >= 2000.0, factor, 1.0)


@node(id="core.spec.air_to_vac", name="Air to Vacuum", category="Spectra/Transform", icon="wind")
def air_to_vac(
    spec: Spectrum1D,
    direction: Annotated[str, Param(choices=["air_to_vac", "vac_to_air"], label="Direction")] = (
        "air_to_vac"
    ),
) -> Spectrum1D:
    """Convert air wavelengths to vacuum (or back) with the rbcodes ``rb_spectrum`` formula.

    The Ciddor-style refractive index is applied above 2000 Angstrom; ``meta['airvac']`` records
    the result and a spectrum already in the target convention is returned unchanged.

    Args:
        spec: Input spectrum with wavelengths in Angstrom.
        direction: Which way to convert.

    Returns:
        The spectrum with converted wavelengths.
    """
    if spec.frame == "velocity":
        raise ValueError("air/vacuum conversion needs a wavelength axis, not velocity")
    target = "vac" if direction == "air_to_vac" else "air"
    if spec.meta.get("airvac") == target:
        return spec
    factor = _air_vac_factor(spec.wave)
    wave = spec.wave * factor if target == "vac" else spec.wave / factor
    return spec.model_copy(update={"wave": wave, "meta": {**spec.meta, "airvac": target}})


@node(
    id="core.spec.normalize", name="Normalize Spectrum", category="Spectra/Transform", icon="divide"
)
def normalize(
    spec: Spectrum1D,
    continuum: Continuum | None = None,
) -> Spectrum1D:
    """Divide flux (and error) by a continuum: the input port, else the spectrum's own.

    Args:
        spec: Input spectrum.
        continuum: A fitted continuum on the same grid (optional when ``spec.continuum`` is set).

    Returns:
        The normalised spectrum (``flux_unit='normalized'``, continuum set to one).
    """
    cont = continuum.cont if continuum is not None else spec.continuum
    if cont is None:
        raise ValueError("no continuum: connect one or load a spectrum that carries one")
    if cont.shape != spec.flux.shape:
        raise ValueError("continuum and spectrum have different lengths")
    with np.errstate(all="ignore"):
        safe = np.where(cont != 0, cont, np.nan)
        update: dict[str, object] = {
            "flux": spec.flux / safe,
            "continuum": np.ones_like(spec.flux),
            "flux_unit": "normalized",
        }
        if spec.error is not None:
            update["error"] = spec.error / safe
    return spec.model_copy(update=update)


@node(id="core.spec.snr", name="Signal-to-Noise", category="Spectra/Measure", icon="activity")
def snr(
    spec: Spectrum1D,
    lo: Annotated[float | None, Param(widget="wavelength", label="Lower bound")] = None,
    hi: Annotated[float | None, Param(widget="wavelength", label="Upper bound")] = None,
) -> float:
    """Median flux over error inside ``[lo, hi]`` (the whole spectrum when bounds are empty).

    Args:
        spec: Input spectrum with an error array.
        lo: Lower bound in the spectrum's axis unit.
        hi: Upper bound in the spectrum's axis unit.

    Returns:
        The median signal-to-noise ratio per pixel.
    """
    if spec.error is None:
        raise ValueError("the spectrum has no error array")
    keep = np.isfinite(spec.flux) & np.isfinite(spec.error) & (spec.error > 0)
    if lo is not None:
        keep &= spec.wave >= lo
    if hi is not None:
        keep &= spec.wave <= hi
    if not keep.any():
        raise ValueError("no valid pixels in the requested range")
    return float(np.median(spec.flux[keep] / spec.error[keep]))
