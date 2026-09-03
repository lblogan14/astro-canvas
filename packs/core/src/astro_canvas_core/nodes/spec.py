"""``core.spec.*`` nodes: frame transforms and cropping of ``Spectrum1D``."""

from __future__ import annotations

from typing import Annotated

import numpy as np
import numpy.typing as npt
from astropy.constants import c as _c

from astro_canvas.sdk import Param, node
from astro_canvas_core.types import Spectrum1D

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
