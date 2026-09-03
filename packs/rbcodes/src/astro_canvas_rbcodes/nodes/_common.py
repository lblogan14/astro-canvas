"""Shared helpers for the ``rbcodes.*`` nodes: backend dispatch and spectrum-frame arithmetic.

Every numerical entry point below calls the installed ``rbcodes`` when it is importable and the
vendored kernel otherwise (see ``astro_canvas_rbcodes._rb``). Both give the same numbers; the
``provenance()`` block on outputs records which one ran.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from astro_canvas_core.types import Spectrum1D, Transition

from astro_canvas_rbcodes import _rb
from astro_canvas_rbcodes.kernels import contfit as _contfit
from astro_canvas_rbcodes.kernels import ew as _ew
from astro_canvas_rbcodes.kernels import setline as _setline

C_KMS = _ew.SPEED_OF_LIGHT_KMS
"""rbcodes' speed of light (km/s); velocities must use it to reproduce rbcodes' numbers."""

FloatArray = npt.NDArray[np.float64]
RB_META = "rb_spec"
"""``Spectrum1D.meta`` key under which the pipeline records rb_spec bookkeeping."""


# --- backend dispatch --------------------------------------------------------------------------


def setline(
    lambda_rest: float, method: str, linelist: str = "atom", target_name: str | None = None
) -> dict[str, Any]:
    """``rb_setline`` from rbcodes when installed, else the vendored port."""
    module = _rb.import_rbcodes("IGM.rb_setline")
    if module is not None:
        result: dict[str, Any] = module.rb_setline(
            lambda_rest, method, linelist=linelist, target_name=target_name
        )
        return result
    return _setline.rb_setline(lambda_rest, method, linelist=linelist, target_name=target_name)


def line_list_arrays(
    label: str,
) -> tuple[FloatArray, npt.NDArray[np.str_], FloatArray, FloatArray | None]:
    """``(wrest, name, fval, gamma | None)`` of a line list from rbcodes or the vendored copy."""
    module = _rb.import_rbcodes("IGM.rb_setline")
    if module is not None:
        rows = module.read_line_list(label)
        wrest = np.array([float(r["wrest"]) for r in rows], dtype=np.float64)
        name = np.array([str(r["ion"]) for r in rows], dtype=np.str_)
        fval = np.array([float(r["fval"]) for r in rows], dtype=np.float64)
        gamma = (
            np.array([float(r["gamma"]) for r in rows], dtype=np.float64)
            if label == "atom"
            else None
        )
        return wrest, name, fval, gamma
    return _setline.line_list_arrays(label)


def compute_ew(
    lam: FloatArray,
    flx: FloatArray,
    wrest: float,
    lmts: Sequence[float],
    flx_err: FloatArray,
    *,
    f0: float | None,
    sat_limit: float | str | None,
    snr: bool,
    binsize: int,
) -> dict[str, Any]:
    """``compute_EW`` from rbcodes when installed, else the vendored port."""
    module = _rb.import_rbcodes("IGM.compute_EW")
    if module is not None:
        result: dict[str, Any] = module.compute_EW(
            lam,
            flx,
            wrest,
            list(lmts),
            flx_err,
            plot=False,
            zabs=0.0,
            f0=f0,
            sat_limit=sat_limit,
            verbose=False,
            SNR=snr,
            _binsize=binsize,
        )
        return result
    return _ew.compute_ew(
        lam, flx, wrest, lmts, flx_err, f0=f0, sat_limit=sat_limit, snr=snr, binsize=binsize
    )


def iter_contfit(
    x: FloatArray,
    flux: FloatArray,
    error: FloatArray,
    *,
    order: int,
    sigma: float,
    use_weights: bool,
    maxiter: int,
) -> dict[str, Any]:
    """Fixed-order Legendre fit (``rb_iter_contfit``) with the model included."""
    module = _rb.import_rbcodes("IGM.rb_iter_contfit") if maxiter > 0 else None
    if module is not None:
        result: dict[str, Any] = module.rb_iter_contfit(
            x,
            flux.copy(),
            error=error.copy(),
            order=order,
            sigma=sigma,
            use_weights=use_weights,
            return_model=True,
            maxiter=maxiter,
            silent=True,
        )
        return result
    return _contfit.rb_iter_contfit(
        x, flux, error, order=order, sigma=sigma, use_weights=use_weights, maxiter=maxiter
    )


def optimal_polynomial(
    x: FloatArray,
    flux: FloatArray,
    error: FloatArray,
    *,
    min_order: int,
    max_order: int,
    sigma: float,
    use_weights: bool,
    maxiter: int,
) -> dict[str, Any]:
    """BIC scan over Legendre orders (``fit_optimal_polynomial``) with the model included."""
    module = _rb.import_rbcodes("IGM.rb_iter_contfit") if maxiter > 0 else None
    if module is not None:
        result: dict[str, Any] = module.fit_optimal_polynomial(
            x,
            flux.copy(),
            error=error.copy(),
            min_order=min_order,
            max_order=max_order,
            maxiter=maxiter,
            sigma=sigma,
            use_weights=use_weights,
            include_model=True,
            plot=False,
            silent=True,
        )
        return result
    return _contfit.fit_optimal_polynomial(
        x,
        flux,
        error,
        min_order=min_order,
        max_order=max_order,
        maxiter=maxiter,
        sigma=sigma,
        use_weights=use_weights,
    )


# --- spectrum frames ---------------------------------------------------------------------------


def rest_wavelength(spec: Spectrum1D) -> FloatArray:
    """Rest-frame wavelength of every pixel, whatever frame the spectrum is in.

    Velocity spectra need ``v0_wrest`` (set by ``rbcodes.absorption.slice``); observed spectra
    need ``z`` (set by ``rbcodes.absorption.set_redshift``).
    """
    if spec.frame == "velocity":
        if spec.v0_wrest is None:
            raise ValueError("velocity spectrum has no reference transition (v0_wrest)")
        return np.asarray(spec.v0_wrest * (1.0 + spec.wave / C_KMS), dtype=np.float64)
    if spec.frame == "rest":
        return np.asarray(spec.wave, dtype=np.float64)
    if spec.z is None:
        raise ValueError("observed-frame spectrum has no redshift; add Set Redshift first")
    return np.asarray(spec.wave / (1.0 + spec.z), dtype=np.float64)


def velocity_of(wave_rest: FloatArray, wrest: float) -> FloatArray:
    """rbcodes' ``(lambda_rest - wrest) * c / wrest`` in km/s."""
    return np.asarray((wave_rest - wrest) * C_KMS / wrest, dtype=np.float64)


def require_error(spec: Spectrum1D) -> FloatArray:
    if spec.error is None:
        raise ValueError("the spectrum has no error array; rbcodes needs one for this step")
    return np.asarray(spec.error, dtype=np.float64)


def rb_meta(spec: Spectrum1D) -> dict[str, Any]:
    """The ``meta['rb_spec']`` bookkeeping block (empty when absent)."""
    block = spec.meta.get(RB_META)
    return dict(block) if isinstance(block, dict) else {}


def with_rb_meta(spec: Spectrum1D, **fields: Any) -> dict[str, Any]:
    """``meta`` with the rb_spec block updated and provenance refreshed."""
    block = rb_meta(spec)
    block.update(fields)
    return {**spec.meta, RB_META: block, "rbcodes": _rb.provenance()}


def transition_from_setline(match: dict[str, Any]) -> Transition:
    """A ``Transition`` from an ``rb_setline`` result (``closest`` scalars or single-row arrays)."""
    wave = np.atleast_1d(np.asarray(match["wave"], dtype=np.float64))
    if wave.size == 0:
        raise ValueError("no transition matched")
    fval = np.atleast_1d(np.asarray(match["fval"], dtype=np.float64))
    name = np.atleast_1d(np.asarray(match["name"]))
    gamma = match.get("gamma")
    gamma_value = (
        float(np.atleast_1d(np.asarray(gamma, dtype=np.float64))[0]) if gamma is not None else None
    )
    return Transition(
        name=str(name[0]), wrest=float(wave[0]), fval=float(fval[0]), gamma=gamma_value
    )


__all__ = [
    "C_KMS",
    "RB_META",
    "compute_ew",
    "iter_contfit",
    "line_list_arrays",
    "optimal_polynomial",
    "rb_meta",
    "require_error",
    "rest_wavelength",
    "setline",
    "transition_from_setline",
    "velocity_of",
    "with_rb_meta",
]
