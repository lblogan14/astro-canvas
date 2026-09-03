"""Port of ``rbcodes.GUIs.multispecviewer.LineFitter``: quick Gaussian / centre-of-mass fits.

Two anchor points ``(x1, y1)`` and ``(x2, y2)`` define both the fit window and a linear
continuum ``cont(l) = y1 + (y2 - y1) / (x2 - x1) * (l - x1)``, so a tilted continuum and a
half-profile are both supported. Absorption versus emission follows the sign of the integrated
residual. No error array is used: both fits are unweighted.

The upstream module is Qt-free, so the nodes call it directly when rbcodes is importable
(``nodes/_multispec_backend.py``); this port keeps the same numbers on Python 3.12.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt
from scipy.optimize import curve_fit

FitKind = Literal["gaussian", "com"]
"""``gaussian``: least-squares Gaussian; ``com``: flux-weighted centre of mass."""

C_KMS = 2.998e5
"""Speed of light as ``LineFitter`` writes it (not rbcodes' 2.9979e5 elsewhere)."""

FWHM_PER_SIGMA = 2.3548
"""``LineFitter``'s Gaussian FWHM factor."""

ASYMMETRY_FRACTION = 0.20
"""Centroid closer than this fraction of the window to an edge flags a truncated profile."""


@dataclass(frozen=True)
class LineFit:
    """One quick fit: centroid, width, amplitude and the model curve for the overlay."""

    kind: FitKind
    centroid: float
    fwhm_ang: float
    fwhm_kms: float
    amplitude: float
    direction: int
    asymmetric: bool
    sigma_ang: float
    sigma_kms: float
    n_pixels: int
    window: tuple[float, float]
    continuum: tuple[float, float]
    fit_wave: npt.NDArray[np.float64] = field(default_factory=lambda: np.empty(0))
    fit_flux: npt.NDArray[np.float64] = field(default_factory=lambda: np.empty(0))


def linear_continuum(
    wave: npt.NDArray[np.float64], x1: float, y1: float, x2: float, y2: float
) -> npt.NDArray[np.float64]:
    """The two-anchor continuum evaluated on ``wave``."""
    return np.asarray(y1 + (y2 - y1) / (x2 - x1) * (wave - x1), dtype=np.float64)


def order_anchors(x1: float, y1: float, x2: float, y2: float) -> tuple[float, float, float, float]:
    """``(x1, y1, x2, y2)`` with ``x1 < x2``."""
    if x1 > x2:
        return x2, y2, x1, y1
    return x1, y1, x2, y2


def _window(
    wave: npt.ArrayLike, flux: npt.ArrayLike, x1: float, x2: float, minimum: int
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    w = np.asarray(wave, dtype=np.float64)
    f = np.asarray(flux, dtype=np.float64)
    mask = (w >= x1) & (w <= x2) & np.isfinite(f)
    n_pix = int(mask.sum())
    if n_pix < minimum:
        raise ValueError(
            f"Only {n_pix} finite pixels in window [{x1:.1f}, {x2:.1f}] A - need >= {minimum}"
        )
    return w[mask], f[mask]


def _gauss(
    x: npt.NDArray[np.float64], amp: float, cen: float, sig: float
) -> npt.NDArray[np.float64]:
    return np.asarray(amp * np.exp(-0.5 * ((x - cen) / sig) ** 2), dtype=np.float64)


def fit_gaussian(
    wave: npt.ArrayLike, flux: npt.ArrayLike, x1: float, y1: float, x2: float, y2: float
) -> LineFit:
    """Fit one Gaussian to ``flux - continuum`` between the anchors (``LineFitter.fit_gaussian``).

    Raises:
        ValueError: fewer than five finite pixels inside the window.
        RuntimeError: ``scipy.optimize.curve_fit`` did not converge.
    """
    x1, y1, x2, y2 = order_anchors(x1, y1, x2, y2)
    w, f = _window(wave, flux, x1, x2, 5)
    residual = f - linear_continuum(w, x1, y1, x2, y2)
    direction = -1 if residual.sum() < 0 else 1
    data = direction * residual

    amp_guess = float(np.max(data))
    if amp_guess <= 0:
        amp_guess = float(np.abs(residual).max())
    cen_guess = float(w[int(np.argmax(data))])
    sig_guess = (x2 - x1) / 4.0
    try:
        popt, _ = curve_fit(
            _gauss,
            w,
            data,
            p0=[amp_guess, cen_guess, sig_guess],
            bounds=([0.0, x1, 1e-3], [np.inf, x2, (x2 - x1)]),
            maxfev=3000,
        )
    except Exception as exc:  # noqa: BLE001 - upstream re-raises every failure the same way
        raise RuntimeError(f"Gaussian curve_fit failed: {exc}") from exc

    amp, cen, sig = (float(v) for v in popt)
    sigma = abs(sig)
    fwhm_ang = FWHM_PER_SIGMA * sigma
    fit_wave = np.linspace(x1, x2, 300)
    fit_flux = linear_continuum(fit_wave, x1, y1, x2, y2) + direction * _gauss(
        fit_wave, amp, cen, sig
    )
    return LineFit(
        kind="gaussian",
        centroid=cen,
        fwhm_ang=fwhm_ang,
        fwhm_kms=fwhm_ang / cen * C_KMS if cen > 0 else 0.0,
        amplitude=direction * amp,
        direction=direction,
        asymmetric=_asymmetric(cen, x1, x2),
        sigma_ang=sigma,
        sigma_kms=sigma / cen * C_KMS if cen > 0 else 0.0,
        n_pixels=int(w.size),
        window=(x1, x2),
        continuum=(y1, y2),
        fit_wave=fit_wave,
        fit_flux=fit_flux,
    )


def fit_com(
    wave: npt.ArrayLike, flux: npt.ArrayLike, x1: float, y1: float, x2: float, y2: float
) -> LineFit:
    """Centre-of-mass centroid between the anchors (``LineFitter.fit_com``).

    Weights are the continuum-subtracted residuals clipped at zero, so noise pixels of the wrong
    sign do not pull the centroid. ``fwhm_ang`` is ``2.3548 sigma`` and assumes a Gaussian shape.

    Raises:
        ValueError: fewer than three finite pixels, or no signal above the continuum.
    """
    x1, y1, x2, y2 = order_anchors(x1, y1, x2, y2)
    w, f = _window(wave, flux, x1, x2, 3)
    residual = f - linear_continuum(w, x1, y1, x2, y2)
    direction = -1 if residual.sum() < 0 else 1
    weights = np.maximum(direction * residual, 0.0)
    total = float(weights.sum())
    if total == 0.0:
        raise ValueError("Sum of weights is zero - no signal above continuum in window")

    centroid = float(np.sum(weights * w) / total)
    sigma = float(np.sqrt(np.sum(weights * (w - centroid) ** 2) / total))
    fwhm_ang = FWHM_PER_SIGMA * sigma
    return LineFit(
        kind="com",
        centroid=centroid,
        fwhm_ang=fwhm_ang,
        fwhm_kms=fwhm_ang / centroid * C_KMS if centroid > 0 else 0.0,
        amplitude=direction * float(np.max(weights)),
        direction=direction,
        asymmetric=_asymmetric(centroid, x1, x2),
        sigma_ang=sigma,
        sigma_kms=sigma / centroid * C_KMS if centroid > 0 else 0.0,
        n_pixels=int(w.size),
        window=(x1, x2),
        continuum=(y1, y2),
    )


def _asymmetric(centroid: float, x1: float, x2: float) -> bool:
    window = x2 - x1
    return (centroid - x1) < ASYMMETRY_FRACTION * window or (
        x2 - centroid
    ) < ASYMMETRY_FRACTION * window


__all__ = [
    "ASYMMETRY_FRACTION",
    "C_KMS",
    "FWHM_PER_SIGMA",
    "FitKind",
    "LineFit",
    "fit_com",
    "fit_gaussian",
    "linear_continuum",
    "order_anchors",
]
