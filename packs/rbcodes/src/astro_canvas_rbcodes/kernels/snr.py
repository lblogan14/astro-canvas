"""Ports of ``rbcodes.IGM.rb_specbin`` and ``rbcodes.utils.compute_SNR_1d.estimate_snr``."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt


def rb_specbin(
    flux: npt.ArrayLike,
    nbin: int,
    *,
    wave: npt.ArrayLike | None = None,
    var: npt.ArrayLike | None = None,
) -> dict[str, npt.NDArray[np.float64]]:
    """Bin ``nbin`` pixels together (mean flux/wave, variance averaged then divided by ``nbin``)."""
    flux_arr = np.asarray(flux, dtype=np.float64)
    if not isinstance(nbin, int) or nbin <= 0:
        raise ValueError("nbin must be a positive integer")
    if flux_arr.size == 0:
        raise ValueError("Input flux array is empty")
    if nbin > flux_arr.size:
        raise ValueError(
            f"nbin ({nbin}) cannot be larger than the length of flux array ({flux_arr.size})"
        )
    variance = np.asarray(var, dtype=np.float64) if var is not None else None
    wavelength = np.asarray(wave, dtype=np.float64) if wave is not None else None
    if variance is not None and variance.size != flux_arr.size:
        raise ValueError("Length of variance array must match length of flux array")
    if wavelength is not None and wavelength.size != flux_arr.size:
        raise ValueError("Length of wavelength array must match length of flux array")

    n = flux_arr.size
    if n % nbin != 0:
        num_pix = math.floor(n / nbin) + 1
        first = n % nbin
    else:
        num_pix = math.floor(n / nbin)
        first = nbin
    new_flux = np.zeros(num_pix)
    new_var = np.zeros(num_pix) if variance is not None else None
    new_wave = np.zeros(num_pix) if wavelength is not None else None
    for qq in range(num_pix):
        start = qq * nbin
        end = start + first if (qq == num_pix - 1 and first != nbin) else start + nbin
        end = min(end, n)
        if start >= n:
            break
        index = np.arange(start, end)
        new_flux[qq] = np.mean(flux_arr[index])
        if new_var is not None and variance is not None:
            new_var[qq] = np.mean(variance[index])
        if new_wave is not None and wavelength is not None:
            new_wave[qq] = np.mean(wavelength[index])
    output: dict[str, npt.NDArray[np.float64]] = {"flux": new_flux}
    if new_var is not None:
        output["error"] = np.sqrt(new_var / nbin)
    if new_wave is not None:
        output["wave"] = new_wave
    return output


def estimate_snr(
    wave: npt.ArrayLike,
    flux: npt.ArrayLike,
    error: npt.ArrayLike,
    *,
    binsize: int = 3,
    snr_range: Sequence[float] = (-1, -1),
    robust_median: bool = False,
    sigma_clip_threshold: float = 3.0,
) -> dict[str, Any]:
    """Per-pixel SNR after optional binning; ``robust_snr`` is the sigma-clipped median."""
    wave_arr = np.asarray(wave, dtype=np.float64)
    flux_arr = np.asarray(flux, dtype=np.float64)
    error_arr = np.asarray(error, dtype=np.float64)
    if binsize > 1:
        sp = rb_specbin(flux_arr, binsize, wave=wave_arr, var=error_arr**2)
    else:
        sp = {"wave": wave_arr, "flux": flux_arr, "error": error_arr}
    lo, hi = snr_range
    if list(snr_range) == [-1, -1]:
        lo, hi = float(np.min(sp["wave"])), float(np.max(sp["wave"]))
    mask = (sp["wave"] > lo) & (sp["wave"] < hi)
    with np.errstate(all="ignore"):
        snr = sp["flux"][mask] / sp["error"][mask]
    out: dict[str, Any] = {
        "wave": sp["wave"][mask],
        "snr": snr,
        "flux": sp["flux"][mask],
        "error": sp["error"][mask],
        "mean_snr": float(np.nanmean(snr)) if snr.size else float("nan"),
        "median_snr": float(np.nanmedian(snr)) if snr.size else float("nan"),
    }
    if robust_median:
        from astropy.stats import sigma_clip  # noqa: PLC0415 - lazy: heavy import

        clipped = sigma_clip(snr, sigma=sigma_clip_threshold, maxiters=5)
        kept = clipped.data[~clipped.mask]
        out["robust_snr"] = float(np.nanmedian(kept)) if kept.size else float("nan")
    return out


__all__ = ["estimate_snr", "rb_specbin"]
