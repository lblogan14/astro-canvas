"""Synthetic spectra shared by the zfind tests (ports of rbcodes' ``test_zfind_engine_*``)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from astro_canvas_rbcodes.kernels.zfind_linelists import LineTable

Arrays = tuple[np.ndarray, np.ndarray, np.ndarray | None, np.ndarray | None]

# Common galaxy emission lines (rest wavelengths in A, vacuum), as in rbcodes' tests.
GAL_EM: dict[str, float] = {
    "Halpha": 6562.80,
    "Hbeta": 4861.33,
    "[OIII]5007": 5006.84,
    "[OIII]4959": 4958.91,
    "[OII]3727": 3727.09,
}
MGII: dict[str, float] = {"MgII2796": 2796.35, "MgII2803": 2803.53}
CIVA: dict[str, float] = {"CIV1548": 1548.20, "CIV1550": 1550.77}


def line_table(
    lines: Mapping[str, float], name: str = "Test", kind: str | None = None
) -> LineTable:
    return LineTable.build(list(lines.values()), list(lines.keys()), kind=kind, label=name)


def em_spectrum(
    true_z: float,
    lines: Mapping[str, float],
    *,
    n_pix: int = 3000,
    snr: float = 100.0,
    seed: int = 42,
    provide_error: bool = True,
    provide_continuum: bool = True,
) -> Arrays:
    """Flat unit continuum with 3-pixel emission spikes at ``lines`` shifted to ``true_z``."""
    wave = np.linspace(3000.0 * (1.0 + true_z), 9000.0 * (1.0 + true_z), n_pix)
    sigma = 1.0 / snr
    rng = np.random.default_rng(seed)
    flux = 1.0 + rng.normal(0, sigma, n_pix)
    for lam_rest in lines.values():
        idx = int(np.argmin(np.abs(wave - lam_rest * (1.0 + true_z))))
        flux[idx - 1 : idx + 2] += 5.0
    error = np.full_like(flux, sigma) if provide_error else None
    continuum = np.ones_like(flux) if provide_continuum else None
    return wave, flux, error, continuum


def abs_spectrum(
    absorbers: Sequence[dict[str, Any]],
    *,
    wave_min: float = 3000.0,
    wave_max: float = 12000.0,
    n_pix: int = 5000,
    continuum_level: float = 10.0,
    snr: float = 100.0,
    seed: int = 42,
    provide_error: bool = True,
    provide_continuum: bool = True,
) -> Arrays:
    """Flat QSO continuum with 3-pixel absorption dips for each ``{'z', 'lines', 'depth'?}``."""
    sigma = continuum_level / snr
    wave = np.linspace(wave_min, wave_max, n_pix)
    rng = np.random.default_rng(seed)
    flux = continuum_level * np.ones(n_pix) + rng.normal(0, sigma, n_pix)
    continuum = continuum_level * np.ones(n_pix)
    for ab in absorbers:
        depth = float(ab.get("depth", 5.0))
        for lam_rest in ab["lines"].values():
            lam_obs = lam_rest * (1.0 + ab["z"])
            if wave_min < lam_obs < wave_max:
                idx = int(np.argmin(np.abs(wave - lam_obs)))
                flux[idx - 1 : idx + 2] -= depth
    error = np.full_like(flux, sigma) if provide_error else None
    return wave, flux, error, continuum if provide_continuum else None


def gaussian_lines(
    wave: np.ndarray, flux: np.ndarray, lines: LineTable, z: float, amp_scale: float, sign: float
) -> np.ndarray:
    """Add Gaussian lines of FWHM 4 A (the picket-fence self-test's ``_inject``)."""
    sigma = 4.0 / 2.355
    out = flux.copy()
    for w_rest, weight in zip(lines.wave, lines.weight, strict=True):
        obs = w_rest * (1.0 + z)
        if wave[0] < obs < wave[-1]:
            out += sign * weight * amp_scale * np.exp(-0.5 * ((wave - obs) / sigma) ** 2)
    return out
