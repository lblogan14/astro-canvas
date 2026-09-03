"""Port of ``rbcodes.IGM.rb_iter_contfit`` and ``rb_spec.calculate_confidence_bounds``.

Legendre-polynomial continuum fits with iterative sigma clipping (astropy's
``FittingWithOutlierRemoval``) and the BIC scan over polynomial orders. Plotting and printing
are dropped; the numerics, including rbcodes' in-place sanitising of the flux and error arrays
inside the order scan, are kept so results match the upstream functions.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


def _sanitize(flux: FloatArray, error: FloatArray) -> FloatArray:
    """rbcodes' pre-fit cleaning (mutates ``flux``/``error``); returns the pixel mask (1 = use)."""
    mask = np.ones(flux.size)
    chip_gap = np.where(((error == 0) & (flux == 0)) | (error - flux == 0))
    if np.size(chip_gap) > 0:
        mask[chip_gap] = 0
    qq = np.where(error <= 0)
    if np.size(qq) > 0:
        error[qq] = np.median(error)
    q = np.where(flux <= 0)
    if np.size(q) > 0:
        flux[q] = error[q]
    outside = np.where(((error != 0) & (flux != 0)) | (error - flux != 0))
    med_err = np.median(error[outside])
    bd = np.where(flux < med_err)
    if len(bd[0]) > 0:
        mask[bd] = 0
    return mask


def rb_iter_contfit(
    wave: npt.ArrayLike,
    flux: npt.ArrayLike,
    error: npt.ArrayLike | None = None,
    *,
    maxiter: int = 25,
    order: int = 4,
    sigma: float = 3.0,
    use_weights: bool = False,
    _inplace: bool = False,
) -> dict[str, Any]:
    """Iterative Legendre continuum fit with sigma clipping (``rb_iter_contfit``).

    Returns ``continuum``, ``residuals`` (flux / continuum), ``fit_error`` (std of the residuals
    on the fitted pixels), ``wave``/``flux``/``error`` as used, the astropy ``model`` and
    ``fitter`` and ``param_errors`` when a covariance is available.
    """
    from astropy.modeling import fitting, models  # noqa: PLC0415 - lazy: heavy import
    from astropy.stats import sigma_clip  # noqa: PLC0415

    wave_arr = np.asarray(wave, dtype=np.float64)
    flux_arr = np.asarray(flux, dtype=np.float64)
    if not _inplace:
        flux_arr = flux_arr.copy()
    if error is None:
        from astropy.stats import mad_std  # noqa: PLC0415

        error_arr = np.ones_like(flux_arr) * float(mad_std(flux_arr))
    else:
        error_arr = np.asarray(error, dtype=np.float64)
        if not _inplace:
            error_arr = error_arr.copy()

    mask = _sanitize(flux_arr, error_arr)
    weights_all = 1.0 / error_arr**2 if use_weights else None
    qq = np.where(mask == 1)
    flux_new = flux_arr[qq]
    wave_new = wave_arr[qq]
    weights = weights_all[qq] if weights_all is not None else None

    g_init = models.Legendre1D(order)
    fit = fitting.LevMarLSQFitter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        if maxiter > 0:
            new_fit = fitting.FittingWithOutlierRemoval(fit, sigma_clip, niter=maxiter, sigma=sigma)
            if use_weights:
                filtered_fit, _ = new_fit(g_init, wave_new, flux_new, weights=weights)
            else:
                filtered_fit, _ = new_fit(g_init, wave_new, flux_new)
        elif use_weights:
            filtered_fit = fit(g_init, wave_new, flux_new, weights=weights)
        else:
            filtered_fit = fit(g_init, wave_new, flux_new)

    fit_final = np.asarray(filtered_fit(wave_arr), dtype=np.float64)
    with np.errstate(all="ignore"):
        resid_final = flux_arr / fit_final
    fit_error = float(np.std(resid_final[qq]))

    param_errors: FloatArray | None = None
    if use_weights and "param_cov" in getattr(fit, "fit_info", {}):
        param_cov = fit.fit_info["param_cov"]
        if param_cov is not None:
            param_errors = np.sqrt(np.diag(param_cov))

    result: dict[str, Any] = {
        "continuum": fit_final,
        "residuals": resid_final,
        "fit_error": fit_error,
        "wave": wave_arr,
        "flux": flux_arr,
        "error": error_arr,
        "model": filtered_fit,
        "fitter": fit,
    }
    if param_errors is not None:
        result["param_errors"] = param_errors
    return result


def calculate_bic(
    residuals: npt.ArrayLike,
    n_params: int,
    n_points: int,
    error: npt.ArrayLike | None = None,
) -> float:
    """``k ln n + n ln(RSS / n)`` (weighted by ``1/error**2`` when ``error`` is given)."""
    res = np.asarray(residuals, dtype=np.float64)
    if error is None:
        rss = float(np.sum(res**2))
    else:
        rss = float(np.sum((res / np.asarray(error, dtype=np.float64)) ** 2))
    with np.errstate(divide="ignore"):
        return float(n_params * np.log(n_points) + n_points * np.log(rss / n_points))


def fit_optimal_polynomial(
    wave: npt.ArrayLike,
    flux: npt.ArrayLike,
    error: npt.ArrayLike | None = None,
    *,
    min_order: int = 1,
    max_order: int = 6,
    maxiter: int = 20,
    sigma: float = 3.0,
    use_weights: bool = False,
) -> dict[str, Any]:
    """Scan polynomial orders and keep the one with the lowest BIC (``fit_optimal_polynomial``).

    Returns ``continuum``, ``normalized_flux``, ``residuals``, ``best_order``, ``fit_error``,
    ``bic_results`` (list of ``(order, bic)``), ``model``, ``fitter`` and the arrays used.
    """
    wave_arr = np.asarray(wave, dtype=np.float64)
    flux_arr = np.array(flux, dtype=np.float64, copy=True)
    if wave_arr.size != flux_arr.size:
        raise ValueError("Wavelength and flux arrays must have the same length")
    if error is None:
        error_arr = np.ones_like(flux_arr) * 0.1 * float(np.median(flux_arr))
    else:
        error_arr = np.array(error, dtype=np.float64, copy=True)
    n_points = int(wave_arr.size)
    if n_points < max_order + 2:
        max_order = n_points - 2
    if max_order < min_order:
        raise ValueError(f"Too few points ({n_points}) to fit a polynomial of order {min_order}")

    all_fits: list[dict[str, Any]] = []
    bic_values: list[tuple[int, float]] = []
    for order in range(min_order, max_order + 1):
        # rbcodes hands the same arrays to every order, so the first call's sanitising sticks.
        result = rb_iter_contfit(
            wave_arr,
            flux_arr,
            error=error_arr,
            order=order,
            maxiter=maxiter,
            sigma=sigma,
            use_weights=use_weights,
            _inplace=True,
        )
        raw_residuals = flux_arr - result["continuum"]
        bic = calculate_bic(
            raw_residuals, order + 1, n_points, error=error_arr if use_weights else None
        )
        all_fits.append({**result, "order": order, "bic": bic})
        bic_values.append((order, bic))

    best = all_fits[int(np.argmin([b for _, b in bic_values]))]
    with np.errstate(all="ignore"):
        normalized = flux_arr / best["continuum"]
    out: dict[str, Any] = {
        "wave": wave_arr,
        "flux": flux_arr,
        "error": error_arr,
        "continuum": best["continuum"],
        "normalized_flux": normalized,
        "residuals": best["residuals"],
        "best_order": best["order"],
        "fit_error": best["fit_error"],
        "bic_results": bic_values,
        "model": best["model"],
        "fitter": best["fitter"],
    }
    if use_weights and "param_cov" in getattr(best["fitter"], "fit_info", {}):
        cov = best["fitter"].fit_info["param_cov"]
        if cov is not None:
            out["param_errors"] = np.sqrt(np.diag(cov))
    return out


def calculate_confidence_bounds(
    x: npt.ArrayLike, model: Any, cov_matrix: npt.ArrayLike
) -> FloatArray:
    """1-sigma uncertainty of a Legendre model at ``x`` from its parameter covariance."""
    basis = np.polynomial.legendre.legvander(np.asarray(x, dtype=np.float64), model.degree)
    cov = np.asarray(cov_matrix, dtype=np.float64)
    return np.sqrt(np.sum((basis @ cov) * basis, axis=1))


__all__ = [
    "calculate_bic",
    "calculate_confidence_bounds",
    "fit_optimal_polynomial",
    "rb_iter_contfit",
]
