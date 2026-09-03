"""Port of ``rbcodes.IGM.compute_EW.compute_EW`` (v2.1.0) without plotting or printing."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

SPEED_OF_LIGHT_KMS = 2.9979e5
"""rbcodes uses this rounded value everywhere; keep it for identical velocities."""
AOD_CONSTANT = 2.654e-15


def compute_ew(
    lam: npt.ArrayLike,
    flx: npt.ArrayLike,
    wrest: float,
    lmts: Sequence[float],
    flx_err: npt.ArrayLike,
    *,
    zabs: float = 0.0,
    f0: float | None = None,
    sat_limit: float | str | None = "auto",
    normalization: str = "none",
    snr: bool = False,
    binsize: int = 1,
) -> dict[str, Any]:
    """Rest-frame equivalent width, AOD column density and velocity centroid in ``[vmin, vmax]``.

    Same inputs, outputs and numerics as rbcodes' ``compute_EW`` (keys ``ew_tot``, ``err_ew_tot``,
    ``vel_disp``, ``vel50_err``, ``line_saturation``, ``saturation_fraction``, plus ``col``,
    ``colerr``, ``Tau_a`` and ``med_vel`` when ``f0`` is given, and ``SNR`` when requested).
    """
    lam_arr = np.asarray(lam, dtype=np.float64)
    flux = np.asarray(flx, dtype=np.float64)
    flux_err = np.asarray(flx_err, dtype=np.float64)
    if not (len(lam_arr) == len(flux) == len(flux_err)):
        raise ValueError("Input arrays (lam, flx, flx_err) must have equal lengths")
    if len(lam_arr) == 0:
        raise ValueError("Input arrays cannot be empty")
    if not np.all(np.diff(lam_arr) > 0):
        raise ValueError("Wavelength array must be monotonically increasing")
    if len(lmts) != 2 or lmts[0] >= lmts[1]:
        raise ValueError("Invalid velocity limits. Must be [vmin, vmax] with vmin < vmax")

    if normalization == "median":
        norm_factor = float(np.nanmedian(flux))
    elif normalization == "mean":
        norm_factor = float(np.nanmean(flux))
    else:
        norm_factor = 1.0

    with np.errstate(invalid="ignore", divide="ignore"):
        med_flx = float(np.nanmedian(flux))
        med_err = float(np.nanmedian(flux_err))
        flux = np.nan_to_num(flux, nan=med_flx, posinf=med_flx, neginf=med_flx)
        flux_err = np.nan_to_num(flux_err, nan=med_err, posinf=med_err, neginf=med_err)

    norm_flx: npt.NDArray[np.float64] = flux / norm_factor
    norm_flx_err: npt.NDArray[np.float64] = flux_err / norm_factor

    eps = np.finfo(float).eps
    center = wrest * (1.0 + zabs)
    vel = (lam_arr - center) * SPEED_OF_LIGHT_KMS / (center + eps)
    lambda_r = lam_arr / (1.0 + zabs)

    pix = np.where((vel >= lmts[0]) & (vel <= lmts[1]))
    if len(pix[0]) == 0:
        out: dict[str, Any] = {
            "ew_tot": np.nan,
            "err_ew_tot": np.nan,
            "vel_disp": np.nan,
            "vel50_err": np.nan,
            "line_saturation": False,
            "saturation_fraction": 0.0,
        }
        if f0 is not None:
            out.update({"col": np.nan, "colerr": np.nan, "Tau_a": np.nan, "med_vel": np.nan})
        return out

    if isinstance(sat_limit, str):
        if sat_limit != "auto":
            raise ValueError(f"sat_limit must be 'auto', a number or None, got {sat_limit!r}")
        sat_threshold = float(np.nanmedian(norm_flx_err[pix]))
    elif sat_limit is None:
        sat_threshold = 0.0
    else:
        sat_threshold = float(sat_limit)

    saturated_mask = norm_flx[pix] <= sat_threshold
    is_saturated = bool(np.any(saturated_mask))
    saturation_fraction = float(np.sum(saturated_mask) / len(pix[0]))

    with np.errstate(invalid="ignore", divide="ignore"):
        norm_flx = np.clip(norm_flx, eps, None)
        if sat_threshold > 0:
            q_saturated = norm_flx <= sat_threshold
            norm_flx[q_saturated] = norm_flx_err[q_saturated] + eps

    del_lam_j = np.pad(np.diff(lambda_r), (1, 0), mode="edge")
    dj = 1.0 - norm_flx
    ew = del_lam_j[pix] * dj[pix]
    err_ew = del_lam_j[pix] * np.sqrt(norm_flx_err[pix] ** 2.0)
    err_ew_tot = float(np.sqrt(np.sum(err_ew**2.0)))
    ew_tot = float(np.sum(ew))

    ew_safe = np.maximum(ew, eps)
    ew50 = np.cumsum(ew_safe) / np.sum(ew_safe)
    vel50 = float(np.interp(0.5, ew50, vel[pix]))
    vel16 = float(np.interp(0.16, ew50, vel[pix]))
    vel_disp = abs(vel50 - vel16)
    vel50_err = vel_disp / np.sqrt(len(ew))

    output: dict[str, Any] = {
        "ew_tot": ew_tot,
        "err_ew_tot": err_ew_tot,
        "vel_disp": vel_disp,
        "vel50_err": float(vel50_err),
        "line_saturation": is_saturated,
        "saturation_fraction": saturation_fraction,
    }

    if f0 is not None:
        tau_a = -np.log(np.clip(norm_flx, eps, None))
        del_vel_j = np.pad(np.diff(vel), (1, 0), mode="edge")
        nv = tau_a / (AOD_CONSTANT * f0 * lambda_r + eps)
        n = nv * del_vel_j
        tauerr = norm_flx_err / (norm_flx + eps)
        nerr = (tauerr / (AOD_CONSTANT * f0 * lambda_r + eps)) * del_vel_j
        output.update(
            {
                "col": float(np.sum(n[pix])),
                "colerr": float(np.sqrt(np.sum(nerr[pix] ** 2.0))),
                "Tau_a": tau_a,
                "med_vel": vel50,
            }
        )

    if snr:
        from astro_canvas_rbcodes.kernels.snr import estimate_snr  # noqa: PLC0415

        result = estimate_snr(
            lambda_r,
            norm_flx,
            norm_flx_err,
            binsize=binsize,
            robust_median=True,
            sigma_clip_threshold=2.0,
        )
        output["SNR"] = result["robust_snr"]
    return output


__all__ = ["AOD_CONSTANT", "SPEED_OF_LIGHT_KMS", "compute_ew"]
