"""``rbcodes.continuum.*`` nodes: masked polynomial continuum fits and the full-spectrum fitter."""

from __future__ import annotations

from typing import Annotated, Any, Literal

import numpy as np
from astro_canvas_core.types import Continuum, RangeMask, Spectrum1D

from astro_canvas.sdk import NodeContext, Param, node
from astro_canvas_rbcodes import _rb
from astro_canvas_rbcodes.kernels.contfit import calculate_confidence_bounds
from astro_canvas_rbcodes.kernels.fullspec import fit_quasar_continuum
from astro_canvas_rbcodes.nodes._common import (
    FloatArray,
    iter_contfit,
    optimal_polynomial,
    rb_meta,
    require_error,
    with_rb_meta,
)

Method = Literal["polynomial", "legendre", "spline", "flat", "ransac"]
MaskList = list[tuple[float, float]]


def mask_pixels(x: FloatArray, masks: MaskList) -> np.ndarray:
    """Boolean array of the pixels *excluded* by ``masks`` (inclusive ``[lo, hi]`` ranges)."""
    excluded = np.zeros(x.shape[0], dtype=bool)
    for lo, hi in masks:
        a, b = (lo, hi) if lo <= hi else (hi, lo)
        excluded |= (x >= a) & (x <= b)
    return excluded


def flatten_masks(masks: MaskList) -> list[float]:
    """``[lo1, hi1, lo2, hi2, ...]`` as ``rb_spec.continuum_masks`` stores them."""
    out: list[float] = []
    for lo, hi in masks:
        out.extend([float(lo), float(hi)])
    return out


def _spline(
    x: FloatArray,
    flux: FloatArray,
    error: FloatArray,
    *,
    knot_spacing: float,
    n_sigma: float,
    maxiter: int,
) -> tuple[FloatArray, float]:
    """Sigma-clipped least-squares cubic B-spline with knots every ``knot_spacing`` x-units."""
    from scipy.interpolate import LSQUnivariateSpline  # noqa: PLC0415 - lazy: heavy import

    order = np.argsort(x)
    xs, fs, es = x[order], flux[order], error[order]
    keep = np.isfinite(fs) & np.isfinite(es) & (es > 0)
    span = float(xs[-1] - xs[0])
    n_knots = max(0, int(span // max(knot_spacing, 1e-9)) - 1)
    inner = np.linspace(xs[0], xs[-1], n_knots + 2)[1:-1] if n_knots > 0 else np.array([])
    cont = np.full_like(flux, np.nan)
    for _ in range(max(1, maxiter)):
        good = np.where(keep)[0]
        if good.size < 4 + inner.size:
            raise ValueError("too few unmasked pixels for a spline continuum")
        knots = inner[(inner > xs[good][0]) & (inner < xs[good][-1])]
        spline = LSQUnivariateSpline(xs[good], fs[good], knots, k=3)
        model = np.asarray(spline(xs), dtype=np.float64)
        resid = (fs - model) / es
        clipped = keep & (np.abs(resid) <= n_sigma)
        if maxiter <= 0 or np.array_equal(clipped, keep):
            keep = clipped if maxiter > 0 else keep
            break
        keep = clipped
    cont[order] = model
    with np.errstate(all="ignore"):
        fit_error = float(np.std((flux / cont)[np.isfinite(cont)]))
    return cont, fit_error


def _ransac(
    x: FloatArray, flux: FloatArray, error: FloatArray, *, order: int, n_sigma: float, maxiter: int
) -> tuple[FloatArray, float]:
    """Seeded numpy RANSAC over ordinary polynomials (rbcodes' uses scikit-learn's estimator)."""
    rng = np.random.default_rng(0)
    n = x.shape[0]
    sample = max(order + 2, min(n, 2 * (order + 1)))
    threshold = max(float(np.median(error)) * n_sigma, 1e-12)
    scale = float(np.max(np.abs(x))) or 1.0
    xn = x / scale
    best_inliers: np.ndarray | None = None
    best_count = -1
    for _ in range(max(20, maxiter * 4)):
        idx = rng.choice(n, size=sample, replace=False)
        coeffs = np.polyfit(xn[idx], flux[idx], order)
        resid = np.abs(flux - np.polyval(coeffs, xn))
        inliers = resid <= threshold
        count = int(inliers.sum())
        if count > best_count:
            best_count, best_inliers = count, inliers
    assert best_inliers is not None
    coeffs = np.polyfit(xn[best_inliers], flux[best_inliers], order)
    cont = np.asarray(np.polyval(coeffs, xn), dtype=np.float64)
    with np.errstate(all="ignore"):
        fit_error = float(np.std((flux / cont)[best_inliers]))
    return cont, fit_error


@node(
    id="rbcodes.continuum.fit",
    name="Fit Continuum",
    category="rbcodes/Continuum",
    icon="spline",
    editor="continuum-mask",
    outputs=("continuum", "normalized"),
)
def fit(
    spec: Spectrum1D,
    method: Annotated[Method, Param(label="Method")] = "polynomial",
    order: Annotated[int, Param(min=0, max=15, label="Order")] = 3,
    masks: Annotated[
        MaskList,
        Param(label="Masks (km/s)", help="Velocity ranges excluded from the fit, [lo, hi] pairs"),
    ] = [],  # noqa: B006 - schema default; never mutated
    optimize_order: Annotated[bool, Param(label="Pick order by BIC")] = True,
    min_order: Annotated[int, Param(min=0, max=15, advanced=True)] = 0,
    max_order: Annotated[int, Param(min=0, max=15, advanced=True)] = 7,
    sigma_clip: Annotated[bool, Param(label="Sigma clip")] = True,
    n_sigma: Annotated[float, Param(min=0.5, max=10.0, step=0.5, label="Clip sigma")] = 3.0,
    use_weights: Annotated[bool, Param(label="Weight by 1/error^2")] = False,
    knot_spacing: Annotated[
        float, Param(min=1.0, unit="km / s", advanced=True, label="Spline knot spacing")
    ] = 300.0,
    extra_masks: RangeMask | None = None,
) -> tuple[Continuum, Spectrum1D]:
    """Fit a continuum to a velocity slice with masked regions (``rb_spec.fit_continuum``).

    ``polynomial``/``legendre`` run rbcodes' iterative Legendre fit with sigma clipping
    (``rb_iter_contfit``); with ``optimize_order`` the order is chosen by the Bayesian
    information criterion over ``min_order..max_order`` (``fit_optimal_polynomial``). ``spline``
    fits a sigma-clipped cubic B-spline, ``flat`` uses the median of the unmasked flux and
    ``ransac`` a robust polynomial. The BIC table is kept in ``Continuum.params['bic_results']``.

    Args:
        spec: The velocity slice (from ``Slice Spectrum``); any axis works, masks use its units.
        method: Fitting method.
        order: Polynomial order (used when ``optimize_order`` is off, and for ``ransac``).
        masks: ``[lo, hi]`` ranges to exclude, in the spectrum's axis unit (km/s for slices).
        optimize_order: Choose the polynomial order by BIC.
        min_order: Lowest order tried by the BIC scan.
        max_order: Highest order tried by the BIC scan.
        sigma_clip: Reject outliers iteratively while fitting.
        n_sigma: Clipping threshold in sigma.
        use_weights: Weight pixels by ``1/error^2`` and propagate the fit covariance into the
            normalised errors (``calculate_confidence_bounds``).
        knot_spacing: Distance between spline knots (spline method only).
        extra_masks: Optional ``RangeMask`` port merged with ``masks``.

    Returns:
        The fitted continuum (with masks, method, order, BIC table) and the normalised slice.
    """
    x = np.asarray(spec.wave, dtype=np.float64)
    # rb_spec divides the whole spectrum by its median flux when it loads a file; the iterative
    # Levenberg-Marquardt fit is only scale-invariant to ~1e-6, so fit in the same units and scale
    # the continuum back afterwards to reproduce rbcodes' numbers exactly.
    scale = float(rb_meta(spec).get("flux_scale", 1.0)) or 1.0
    flux = np.asarray(spec.flux, dtype=np.float64) / scale
    error = require_error(spec) / scale
    all_masks: MaskList = [(float(lo), float(hi)) for lo, hi in masks]
    if extra_masks is not None:
        all_masks.extend((float(lo), float(hi)) for lo, hi in extra_masks.ranges)
    excluded = mask_pixels(x, all_masks)
    good = ~excluded & np.isfinite(flux) & np.isfinite(error)
    if good.sum() < 3:
        raise ValueError("not enough unmasked pixels to fit a continuum")
    maxiter = 25 if sigma_clip else 0

    params: dict[str, Any] = {
        "n_sigma": float(n_sigma),
        "sigma_clip": bool(sigma_clip),
        "use_weights": bool(use_weights),
        "optimize_order": bool(optimize_order),
        "n_masked": int(excluded.sum()),
    }
    cont_err: FloatArray | None = None
    fitted_order: int | None = None
    bic: float | None = None
    if method in ("polynomial", "legendre"):
        if optimize_order:
            result = optimal_polynomial(
                x[good],
                flux[good].copy(),
                error[good].copy(),
                min_order=int(min_order),
                max_order=int(max_order),
                sigma=float(n_sigma),
                use_weights=bool(use_weights),
                maxiter=maxiter,
            )
            fitted_order = int(result["best_order"])
            params["bic_results"] = [[int(o), float(b)] for o, b in result["bic_results"]]
            bic = min(float(b) for _, b in result["bic_results"])
        else:
            result = iter_contfit(
                x[good],
                flux[good].copy(),
                error[good].copy(),
                order=int(order),
                sigma=float(n_sigma),
                use_weights=bool(use_weights),
                maxiter=maxiter,
            )
            fitted_order = int(order)
        model = result["model"]
        cont = np.asarray(model(x), dtype=np.float64)
        fit_error = float(result["fit_error"])
        fitter = result.get("fitter")
        if use_weights:
            cov = getattr(fitter, "fit_info", {}).get("param_cov") if fitter is not None else None
            if cov is not None:
                cont_err = calculate_confidence_bounds(x, model, cov)
            else:
                cont_err = np.full_like(x, fit_error)
    elif method == "spline":
        cont, fit_error = _spline(
            x[good],
            flux[good],
            error[good],
            knot_spacing=float(knot_spacing),
            n_sigma=float(n_sigma),
            maxiter=maxiter,
        )
        full = np.full_like(x, np.nan)
        full[good] = cont
        # Extend the spline over masked pixels by evaluating it on the full axis.
        cont = np.interp(x, x[good], cont) if excluded.any() else full
    elif method == "flat":
        level = float(np.median(flux[good]))
        cont = np.full_like(x, level)
        with np.errstate(all="ignore"):
            fit_error = float(np.std(flux[good] / level))
        fitted_order = 0
    else:
        cont, fit_error = _ransac(
            x[good],
            flux[good],
            error[good],
            order=int(order),
            n_sigma=float(n_sigma),
            maxiter=maxiter,
        )
        cont = np.interp(x, x[good], cont) if excluded.any() else cont
        fitted_order = int(order)
    params["fit_error"] = fit_error

    error_out = error
    if cont_err is not None:
        error_out = np.sqrt(error**2 + cont_err**2)
    with np.errstate(all="ignore"):
        safe = np.where(cont != 0, cont, np.nan)
        fnorm = flux / safe
        enorm = error_out / safe
    cont = cont * scale
    if cont_err is not None:
        cont_err = cont_err * scale
    continuum = Continuum(
        cont=cont,
        masks=all_masks,
        method=method,
        order=fitted_order,
        params={**params, "rbcodes": _rb.provenance()},
        bic=bic,
    )
    normalized = spec.model_copy(
        update={
            "flux": fnorm,
            "error": enorm,
            "continuum": np.ones_like(fnorm),
            "flux_unit": "normalized",
            "meta": with_rb_meta(
                spec,
                continuum_masks=flatten_masks(all_masks),
                continuum_fit_params={
                    "method": "polynomial" if method == "legendre" else method,
                    "legendre_order": fitted_order,
                    "use_weights": bool(use_weights),
                    "optimize_cont": bool(optimize_order),
                    "sigma_clip": bool(sigma_clip),
                    "n_sigma": float(n_sigma),
                    "fit_error": fit_error,
                },
                cont_err=float(np.nanmedian(cont_err)) if cont_err is not None else fit_error,
            ),
        }
    )
    return continuum, normalized


@node(
    id="rbcodes.continuum.full_spectrum",
    name="Full-Spectrum Continuum",
    category="rbcodes/Continuum",
    icon="chart-spline",
    cost="expensive",
)
def full_spectrum(
    spec: Spectrum1D,
    window_size: Annotated[float, Param(min=5.0, unit="Angstrom", label="Window")] = 100.0,
    overlap_fraction: Annotated[float, Param(min=0.0, max=0.9, step=0.05, label="Overlap")] = 0.3,
    chunking: Annotated[Literal["uniform", "features"], Param(label="Chunk placement")] = "uniform",
    min_order: Annotated[int, Param(min=0, max=15, advanced=True)] = 2,
    max_order: Annotated[int, Param(min=0, max=15, advanced=True)] = 6,
    n_sigma: Annotated[float, Param(min=0.5, max=10.0, step=0.5, label="Clip sigma")] = 3.0,
    use_weights: Annotated[bool, Param(label="Weight by 1/error^2")] = True,
    wmin: Annotated[float | None, Param(widget="wavelength", advanced=True)] = None,
    wmax: Annotated[float | None, Param(widget="wavelength", advanced=True)] = None,
    ctx: NodeContext | None = None,
) -> Continuum:
    """Continuum of a whole spectrum from blended chunk fits (``fit_quasar_continuum``).

    The spectrum is cut into overlapping windows, each fitted with the BIC-optimal Legendre
    polynomial, and the pieces are blended with cosine tapers. Slow for long spectra, so the node
    waits for an explicit Run and reports progress per chunk.

    Args:
        spec: Spectrum on a wavelength axis (observed or rest frame).
        window_size: Chunk width in Angstrom.
        overlap_fraction: Fraction of the window shared by neighbouring chunks.
        chunking: ``uniform`` spacing, or ``features`` to centre chunks on structured regions.
        min_order: Lowest polynomial order tried per chunk.
        max_order: Highest polynomial order tried per chunk.
        n_sigma: Sigma-clipping threshold.
        use_weights: Weight pixels by ``1/error^2``.
        wmin: Only fit above this wavelength (optional).
        wmax: Only fit below this wavelength (optional).

    Returns:
        The blended continuum on the spectrum's grid (NaN outside ``[wmin, wmax]``), with the
        per-chunk orders and BIC tables in ``params['chunks']``.
    """
    if spec.frame == "velocity":
        raise ValueError("the full-spectrum fitter needs a wavelength axis, not a velocity slice")
    error = spec.error if spec.error is not None else None
    result = fit_quasar_continuum(
        np.asarray(spec.wave, dtype=np.float64),
        np.asarray(spec.flux, dtype=np.float64),
        np.asarray(error, dtype=np.float64) if error is not None else None,
        window_size=float(window_size),
        overlap_fraction=float(overlap_fraction),
        method=chunking,
        wmin=wmin,
        wmax=wmax,
        min_order=int(min_order),
        max_order=int(max_order),
        sigma=float(n_sigma),
        use_weights=bool(use_weights),
        progress=ctx.progress if ctx is not None else None,
        cancelled=(ctx.is_cancelled) if ctx is not None else None,
    )
    chunks = [
        {
            "chunk_id": c["chunk_id"],
            "wavelength_range": [float(v) for v in c["wavelength_range"]],
            "best_order": int(c["best_order"]),
            "bic_results": [[int(o), float(b)] for o, b in c["bic_results"]],
            "std_error": float(c["std_error"]),
            "indices": [int(v) for v in c["indices"]],
        }
        for c in result["chunk_results"]
    ]
    return Continuum(
        cont=np.asarray(result["continuum"], dtype=np.float64),
        masks=[],
        method="full_spectrum",
        order=None,
        params={
            "window_size": float(window_size),
            "overlap_fraction": float(overlap_fraction),
            "chunking": chunking,
            "min_order": int(min_order),
            "max_order": int(max_order),
            "n_sigma": float(n_sigma),
            "use_weights": bool(use_weights),
            "chunks": chunks,
            "rbcodes": _rb.provenance(backend="vendored"),
        },
    )


__all__ = ["Method", "fit", "flatten_masks", "full_spectrum", "mask_pixels"]
