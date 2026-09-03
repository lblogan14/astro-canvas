"""Port of ``rbcodes.GUIs.zfind.engine``: the four redshift-search modes of ``rb_zfind``.

``line_search`` (chi-square-like line matching, emission or absorption), ``picket_fence_search``
(weighted matched filter, see :mod:`picket_fence`), ``template_search`` (MARZ 1-D templates) and
``pca_search`` (DESI redrock eigenvectors), plus the ``multi_*`` variants. Everything works on
plain arrays: ``preprocess`` replaces rbcodes' ``_preprocess(rb_spectrum)``. Results are the
small dataclasses at the top, which mirror ``rbcodes.GUIs.zfind.io`` attribute for attribute so
the nodes can convert either backend's output the same way.

The bundled template files live in ``zfind_templates/`` (MARZ, MIT; redrock templates, BSD-3).
Long scans accept ``progress``/``cancelled`` callbacks (rbcodes has none).
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
from scipy.stats import median_abs_deviation

from astro_canvas_rbcodes.kernels import contfit as _contfit
from astro_canvas_rbcodes.kernels.picket_fence import PicketFenceZ, to_fwhm_pix
from astro_canvas_rbcodes.kernels.zfind_linelists import LineTable

FloatArray = npt.NDArray[np.float64]
Progress = Callable[[float, str | None], None]
Cancelled = Callable[[], bool]
DataNorm = Literal["subtract", "normalize", "raw"]

TEMPLATE_DIR = Path(str(files("astro_canvas_rbcodes.kernels").joinpath("zfind_templates")))

TEMPLATE_FILES: dict[str, str] = {
    "EarlyType": "EarlyType.fits",
    "Intermediate": "Intermediate.fits",
    "LateTypeEmission": "LateTypeEmission.fits",
    "Composite": "Composite.fits",
    "QSO": "QSO.fits",
}
TEMPLATE_NAMES: tuple[str, ...] = tuple(TEMPLATE_FILES)
TemplateName = Literal["EarlyType", "Intermediate", "LateTypeEmission", "Composite", "QSO"]

TEMPLATE_Z_RANGE: dict[str, tuple[float, float]] = {
    "EarlyType": (0.0, 1.5),
    "Intermediate": (0.0, 1.5),
    "LateTypeEmission": (0.0, 7.0),
    "Composite": (0.0, 1.5),
    "QSO": (0.0, 5.5),
}

PCA_FILES: dict[str, str] = {
    "galaxy": "rrtemplate-GALAXY-None-v2.6.fits",
    "qso_loz": "rrtemplate-QSO-LOZ-v1.1.fits",
    "qso_hiz": "rrtemplate-QSO-HIZ-v1.1.fits",
}
PCA_NAMES: tuple[str, ...] = tuple(PCA_FILES)
PcaName = Literal["galaxy", "qso_loz", "qso_hiz"]

PCA_Z_RANGE: dict[str, tuple[float, float]] = {
    "galaxy": (0.0, 1.6),
    "qso_loz": (0.0, 2.5),
    "qso_hiz": (1.0, 6.0),
}


# --- result dataclasses (mirror rbcodes.GUIs.zfind.io) -----------------------------------------


@dataclass
class ZSolution:
    """One redshift solution (``io.ZSolution``)."""

    z: float
    z_err: float
    chi2_dof: float
    method: str
    template_type: str
    n_features: int


@dataclass
class ZFindResult:
    """Emission-mode output (``io.ZFindResult``); ``chi2_curves`` = ``[{label, chi2}]``."""

    z_array: FloatArray
    chi2_curves: list[dict[str, Any]]
    solutions: list[ZSolution]
    warnings: list[str] = field(default_factory=list)

    def best(self) -> ZSolution | None:
        return self.solutions[0] if self.solutions else None


@dataclass
class AbsorberCandidate:
    """One absorber candidate (``io.AbsorberCandidate``)."""

    z: float
    significance: float
    n_lines: int
    is_doublet: bool
    linelist_name: str
    lines_matched: list[str]


@dataclass
class AbsorberResult:
    """Absorption-mode output (``io.AbsorberResult``)."""

    z_array: FloatArray
    significance_curve: FloatArray
    candidates: list[AbsorberCandidate]
    warnings: list[str] = field(default_factory=list)


@dataclass
class Prepared:
    """``_preprocess`` output: vacuum wavelengths, cleaned flux, ivar, continuum, warnings."""

    wave: FloatArray
    flux: FloatArray
    ivar: FloatArray
    continuum: FloatArray
    warnings: list[str]


# --- shared preprocessing ----------------------------------------------------------------------


def air_to_vacuum(wave_air: FloatArray) -> FloatArray:
    """``rb_spectrum.air2vac``: the standard IAU conversion, identity below 2000 Angstrom."""
    sigma_sq = (1e4 / wave_air) ** 2
    factor = 1 + (5.792105e-2 / (238.0185 - sigma_sq)) + (1.67918e-3 / (57.362 - sigma_sq))
    factor = factor * (wave_air >= 2000.0) + 1.0 * (wave_air < 2000.0)
    return np.asarray(wave_air * factor, dtype=np.float64)


def mad_ivar(flux: FloatArray) -> FloatArray:
    """Uniform IVAR from MAD-STD (``_mad_ivar``)."""
    sigma = 1.4826 * float(median_abs_deviation(flux, nan_policy="omit"))
    if sigma == 0:
        sigma = float(np.std(flux[np.isfinite(flux)])) or 1.0
    return np.full_like(flux, 1.0 / sigma**2)


def preprocess(
    wave: npt.ArrayLike,
    flux: npt.ArrayLike,
    error: npt.ArrayLike | None = None,
    continuum: npt.ArrayLike | None = None,
    *,
    fit_continuum: bool = True,
    airvac: str = "vac",
) -> Prepared:
    """``_preprocess``: air-to-vacuum, IVAR (MAD-STD fallback), NaN cleaning, continuum.

    Without a continuum and with ``fit_continuum`` the BIC-optimal Legendre polynomial of
    ``fit_optimal_polynomial`` is used; otherwise the continuum is zero (fine for emission).
    """
    warn_list: list[str] = []
    w = np.asarray(wave, dtype=np.float64).copy()
    f = np.asarray(flux, dtype=np.float64).copy()
    if airvac == "air":
        w = air_to_vacuum(w)
        warn_list.append("Air wavelengths converted to vacuum.")

    if error is not None:
        sig = np.asarray(error, dtype=np.float64)
        ivar = np.where(sig > 0, 1.0 / sig**2, 0.0)
    else:
        sigma = 1.4826 * float(median_abs_deviation(f, nan_policy="omit"))
        if sigma == 0:
            sigma = float(np.std(f[np.isfinite(f)])) or 1.0
        ivar = np.full_like(f, 1.0 / sigma**2)
        warn_list.append(f"No error array — using MAD-STD IVAR (sigma={sigma:.4g}).")

    ivar[~np.isfinite(f)] = 0.0
    f = np.nan_to_num(f, nan=0.0)

    if continuum is not None:
        cont = np.asarray(continuum, dtype=np.float64)
    elif fit_continuum:
        try:
            err_arr = np.asarray(error, dtype=np.float64) if error is not None else None
            result = _contfit.fit_optimal_polynomial(w, f, error=err_arr, use_weights=False)
            cont = np.asarray(result["continuum"], dtype=np.float64)
        except Exception as exc:  # noqa: BLE001 - rbcodes falls back to a zero continuum too
            cont = np.zeros_like(f)
            warn_list.append(f"Continuum fit failed ({exc}); using zero continuum.")
    else:
        cont = np.zeros_like(f)
    return Prepared(wave=w, flux=f, ivar=ivar, continuum=cont, warnings=warn_list)


def find_top_minima(
    z_array: FloatArray, chi2_array: FloatArray, n: int = 3, min_dz: float = 0.02
) -> list[int]:
    """Top ``n`` minima separated by at least ``min_dz`` (``_find_top_minima``)."""
    if not np.any(np.isfinite(chi2_array)):
        return []
    working = chi2_array.copy()
    selected: list[int] = []
    while len(selected) < n:
        if not np.any(np.isfinite(working)):
            break
        idx = int(np.nanargmin(working))
        if not np.isfinite(working[idx]):
            break
        selected.append(idx)
        working[np.abs(z_array - z_array[idx]) <= min_dz] = np.nan
    return selected


def z_err_from_curvature(z_array: FloatArray, chi2_array: FloatArray, idx: int) -> float:
    """``sqrt(1 / |d2 chi2 / dz2|)`` at ``idx`` (``_z_err_from_curvature``), NaN when flat."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            d2 = np.gradient(np.gradient(chi2_array, z_array), z_array)
        curv = abs(float(d2[idx]))
        if curv > 0:
            return float(np.sqrt(1.0 / curv))
    except Exception:  # noqa: BLE001 - rbcodes swallows everything here
        pass
    return float("nan")


def _mask_range(
    ivar: FloatArray, wave: FloatArray, wave_min: float | None, wave_max: float | None
) -> None:
    if wave_min is not None:
        ivar[wave < wave_min] = 0.0
    if wave_max is not None:
        ivar[wave > wave_max] = 0.0


def _boxcar(values: FloatArray, width: int) -> FloatArray:
    from astropy.convolution import Box1DKernel, convolve  # noqa: PLC0415 - lazy astropy

    return np.asarray(convolve(values, Box1DKernel(width)), dtype=np.float64)


def _flux_work(
    flux: FloatArray, continuum: FloatArray, data_norm: str, offset: float
) -> FloatArray:
    """``flux - cont`` / ``flux / cont - offset`` / ``flux`` (``offset`` is 1 for line modes)."""
    cont_safe = np.where(np.abs(continuum) > 1e-10, continuum, 1.0)
    if data_norm == "normalize":
        return np.asarray(flux / cont_safe - offset, dtype=np.float64)
    if data_norm == "raw":
        return np.asarray(flux, dtype=np.float64)
    return np.asarray(flux - continuum, dtype=np.float64)


def _tick(
    i: int, n: int, every: int, progress: Progress | None, cancelled: Cancelled | None, what: str
) -> None:
    if i % every:
        return
    if cancelled is not None and cancelled():
        raise InterruptedError(f"{what} cancelled")
    if progress is not None:
        progress(i / n, None)


def _sub_progress(progress: Progress | None, k: int, n: int, label: str) -> Progress | None:
    """Map the progress of the ``k``-th of ``n`` sub-scans onto ``[k/n, (k+1)/n]``."""
    if progress is None:
        return None
    base, span = k / n, 1.0 / n

    def report(fraction: float, message: str | None) -> None:
        progress(base + span * fraction, message or label)

    return report


# --- mode 1: line search -----------------------------------------------------------------------


def line_search(
    prep: Prepared,
    lines: LineTable,
    *,
    z_min: float = 0.0,
    z_max: float = 6.0,
    n_steps: int = 10000,
    mode: str = "emission",
    window_pixels: int = 5,
    smooth_pixels: int = 3,
    data_norm: str = "subtract",
    wave_min: float | None = None,
    wave_max: float | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> ZFindResult | AbsorberResult:
    """``engine.line_search`` on preprocessed arrays.

    Returns a ``ZFindResult`` for ``mode="emission"`` and an ``AbsorberResult`` for
    ``mode="absorption"`` (significance curve + ranked candidates).
    """
    wave, flux, continuum = prep.wave, prep.flux.copy(), prep.continuum.copy()
    ivar = prep.ivar.copy()
    warn_list = list(prep.warnings)
    _mask_range(ivar, wave, wave_min, wave_max)
    if smooth_pixels > 1:
        flux = _boxcar(flux, smooth_pixels)
        continuum = _boxcar(continuum, smooth_pixels)
    flux_work = _flux_work(flux, continuum, data_norm, 1.0)

    rest_waves = lines.wave.astype(np.float64)
    line_names = lines.name
    z_array = np.linspace(z_min, z_max, n_steps)
    chi2_array = np.full(n_steps, np.nan)
    wmin, wmax = float(wave.min()), float(wave.max())
    dwave = float(np.median(np.diff(wave)))
    every = max(1, n_steps // 50)

    for i, z in enumerate(z_array):
        _tick(i, n_steps, every, progress, cancelled, "line search")
        obs_waves = rest_waves * (1.0 + z)
        in_range = (obs_waves > wmin + window_pixels * dwave) & (
            obs_waves < wmax - window_pixels * dwave
        )
        if not np.any(in_range):
            continue
        accum = 0.0
        n_used = 0
        for obs_w in obs_waves[in_range]:
            pix = int(np.argmin(np.abs(wave - obs_w)))
            lo = max(0, pix - window_pixels)
            hi = min(len(wave), pix + window_pixels + 1)
            fw = flux_work[lo:hi]
            iv = ivar[lo:hi]
            if np.sum(iv > 0) < 2:
                continue
            iv_sum = float(np.sum(iv))
            if iv_sum <= 0:
                continue
            s = float(np.sum(fw * iv)) if mode == "emission" else float(np.sum(-fw * iv))
            if s > 0:
                accum -= (s**2) / iv_sum
                n_used += 1
        if n_used > 0:
            chi2_array[i] = accum / np.sqrt(n_used)
    if progress is not None:
        progress(1.0, None)

    method_label = f"LineSearch:{lines.label}"
    if mode == "emission":
        solutions = [
            ZSolution(
                z=float(z_array[idx]),
                z_err=z_err_from_curvature(z_array, chi2_array, idx),
                chi2_dof=float(chi2_array[idx]),
                method=method_label,
                template_type="Unknown",
                n_features=int(np.sum(_in_range(rest_waves, z_array[idx], wmin, wmax))),
            )
            for idx in find_top_minima(z_array, chi2_array, n=10)
        ]
        return ZFindResult(
            z_array=z_array,
            chi2_curves=[{"label": method_label, "chi2": chi2_array.copy()}],
            solutions=solutions,
            warnings=warn_list,
        )

    finite = chi2_array[np.isfinite(chi2_array)]
    significance = np.zeros_like(z_array)
    candidates: list[AbsorberCandidate] = []
    if len(finite) > 0:
        noise = float(np.std(finite))
        baseline = float(np.median(finite))
        significance = (baseline - chi2_array) / (noise + 1e-10)
        for idx in find_top_minima(z_array, chi2_array, n=20):
            matched = _in_range(rest_waves, z_array[idx], wmin, wmax)
            sig = float(significance[idx]) if np.isfinite(significance[idx]) else 0.0
            candidates.append(
                AbsorberCandidate(
                    z=float(z_array[idx]),
                    significance=sig,
                    n_lines=int(np.sum(matched)),
                    is_doublet=False,
                    linelist_name=lines.label,
                    lines_matched=[str(v) for v in line_names[matched].tolist()],
                )
            )
        candidates.sort(key=lambda c: c.significance, reverse=True)
    return AbsorberResult(
        z_array=z_array, significance_curve=significance, candidates=candidates, warnings=warn_list
    )


def _in_range(rest: FloatArray, z: float, wmin: float, wmax: float) -> npt.NDArray[np.bool_]:
    obs = rest * (1.0 + z)
    return np.asarray((obs > wmin) & (obs < wmax))


# --- mode 1b: picket fence ---------------------------------------------------------------------


def picket_fence_search(
    prep: Prepared,
    lines: LineTable,
    *,
    z_min: float = 0.0,
    z_max: float = 6.0,
    n_steps: int = 10000,
    fwhm_ang: float = 0.0,
    smooth_fwhm_pix: float | None = None,
    window_pixels: int = 5,
    window_fwhm: float = 1.5,
    use_error: bool | str = "auto",
    data_norm: str = "subtract",
    wave_min: float | None = None,
    wave_max: float | None = None,
    resolution: Mapping[str, float] | None = None,
    pf_mode: str = "direct",
    prominence_sigma: float = 3.0,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> ZFindResult:
    """``engine.picket_fence_search``: the weighted scan (Mode A) or detect-then-match (Mode B)."""
    wave = prep.wave
    ivar = prep.ivar.copy()
    warn_list = list(prep.warnings)
    _mask_range(ivar, wave, wave_min, wave_max)
    flux_work = _flux_work(prep.flux, prep.continuum, data_norm, 1.0)

    res: Mapping[str, float] | None = None
    if resolution:
        res = resolution
    elif fwhm_ang > 0.0:
        res = {"fwhm_ang": fwhm_ang}

    pf = PicketFenceZ(
        wave,
        flux_work,
        ivar,
        lines,
        smooth_fwhm_pix=smooth_fwhm_pix,
        window_fwhm=window_fwhm,
        window_pixels=window_pixels,
        use_error=use_error,
        prominence_sigma=prominence_sigma,
        resolution=res,
    )
    warn_list.extend(pf.warnings)

    method_label = f"PicketFence:{lines.label}"
    wmin, wmax = float(wave.min()), float(wave.max())
    rest_waves = lines.wave.astype(np.float64)
    z_array = np.linspace(z_min, z_max, n_steps)
    score = pf.run(z_array, progress=progress, cancelled=cancelled)

    solutions: list[ZSolution] = []
    if pf_mode == "detect_match":
        cands = pf.match_peaks()
        for cand in cands[:10]:
            zc = float(cand["z"])
            nearest = int(np.argmin(np.abs(z_array - zc)))
            score_at = float(score[nearest]) if np.isfinite(score[nearest]) else 0.0
            solutions.append(
                ZSolution(
                    z=zc,
                    z_err=z_err_from_curvature(z_array, score, nearest),
                    chi2_dof=score_at,
                    method=method_label + ":ModeB",
                    template_type="Unknown",
                    n_features=int(cand["n_matches"]),
                )
            )
        warn_list.append(f"Mode B: {len(cands)} peak-match candidates found.")
    else:
        for idx in find_top_minima(z_array, score, n=10):
            solutions.append(
                ZSolution(
                    z=float(z_array[idx]),
                    z_err=z_err_from_curvature(z_array, score, idx),
                    chi2_dof=float(score[idx]),
                    method=method_label,
                    template_type="Unknown",
                    n_features=int(np.sum(_in_range(rest_waves, z_array[idx], wmin, wmax))),
                )
            )
    return ZFindResult(
        z_array=z_array,
        chi2_curves=[{"label": method_label, "chi2": score.copy()}],
        solutions=solutions,
        warnings=warn_list,
    )


# --- mode 2: template search -------------------------------------------------------------------


def template_path(template_name: str) -> Path:
    fname = TEMPLATE_FILES.get(template_name)
    if fname is None:
        raise ValueError(f"Unknown template '{template_name}'. Available: {list(TEMPLATE_NAMES)}")
    path = TEMPLATE_DIR / "marz" / fname
    if not path.exists():
        raise FileNotFoundError(f"Template file not found: {path}")
    return path


def load_template(template_name: str) -> tuple[FloatArray, FloatArray, FloatArray]:
    """``_load_template``: ``(wave, flux, pseudo_continuum)`` of a bundled MARZ template."""
    from astropy.convolution import Box1DKernel, convolve  # noqa: PLC0415 - lazy astropy
    from astropy.io import fits  # noqa: PLC0415 - lazy astropy

    with fits.open(template_path(template_name)) as hdul:
        wave = np.asarray(hdul["WAVE"].data, dtype=np.float64)
        flux = np.asarray(hdul["FLUX"].data, dtype=np.float64)
    smooth_width = max(51, len(flux) // 15)
    pseudo = np.asarray(convolve(flux, Box1DKernel(smooth_width)), dtype=np.float64)
    median_abs = float(np.median(np.abs(flux[flux != 0]))) if np.any(flux != 0) else 1.0
    pseudo = np.where(np.abs(pseudo) > 0.01 * median_abs, pseudo, median_abs)
    return wave, flux, np.asarray(pseudo, dtype=np.float64)


def _model_work(values: FloatArray, pseudo: FloatArray, model_norm: str) -> FloatArray:
    if model_norm == "normalize":
        return np.asarray(values / pseudo, dtype=np.float64)
    if model_norm == "subtract":
        return np.asarray(values - pseudo, dtype=np.float64)
    return values


def _degrade(
    t_wave: FloatArray, values: FloatArray, res_kwargs: Mapping[str, float] | None
) -> FloatArray:
    """Convolve a template to the instrument LSF (``template_res_kwargs`` / ``pca_res_kwargs``)."""
    if not res_kwargs:
        return values
    try:
        from scipy.ndimage import gaussian_filter1d  # noqa: PLC0415

        fwhm_pix = to_fwhm_pix(t_wave, res_kwargs)
        if fwhm_pix and fwhm_pix > 0.5:
            sigma = fwhm_pix / 2.3548
            if values.ndim == 1:
                return np.asarray(gaussian_filter1d(values, sigma), dtype=np.float64)
            return np.array([gaussian_filter1d(ev, sigma) for ev in values], dtype=np.float64)
    except Exception:  # noqa: BLE001 - rbcodes ignores resolution errors silently
        pass
    return values


def template_search(
    prep: Prepared,
    template_name: str = "LateTypeEmission",
    *,
    z_min: float | None = None,
    z_max: float | None = None,
    n_steps: int = 5000,
    data_norm: str = "normalize",
    model_norm: str = "normalize",
    smooth_pixels: int = 1,
    wave_min: float | None = None,
    wave_max: float | None = None,
    template_res_kwargs: Mapping[str, float] | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> ZFindResult:
    """``engine.template_search``: chi-square scan against one bundled MARZ template."""
    wave = prep.wave
    ivar = prep.ivar.copy()
    warn_list = list(prep.warnings)
    _mask_range(ivar, wave, wave_min, wave_max)
    t_wave, t_flux, t_pseudo = load_template(template_name)
    flux_work = _flux_work(prep.flux, prep.continuum, data_norm, 0.0)
    t_work = _model_work(t_flux, t_pseudo, model_norm)
    if smooth_pixels > 1:
        flux_work = _boxcar(flux_work, smooth_pixels)
    t_work = _degrade(t_wave, t_work, template_res_kwargs)

    z_lo, z_hi = TEMPLATE_Z_RANGE.get(template_name, (0.0, 6.0))
    z_min = z_lo if z_min is None else z_min
    z_max = z_hi if z_max is None else z_max
    z_array = np.linspace(z_min, z_max, n_steps)
    chi2_array = np.full(n_steps, np.nan)
    wmin, wmax = float(wave.min()), float(wave.max())
    every = max(1, n_steps // 50)

    for i, z in enumerate(z_array):
        _tick(i, n_steps, every, progress, cancelled, "template search")
        t_obs = t_wave * (1.0 + z)
        overlap_lo = max(wmin, float(t_obs.min()))
        overlap_hi = min(wmax, float(t_obs.max()))
        if (overlap_hi - overlap_lo) < 0.2 * (wmax - wmin):
            continue
        model = np.interp(wave, t_obs, t_work, left=0.0, right=0.0)
        good = (ivar > 0) & (model != 0.0)
        if good.sum() < 50:
            continue
        f, tg, iv = flux_work[good], model[good], ivar[good]
        denom = float(np.sum(tg**2 * iv))
        if denom == 0:
            continue
        amp = float(np.sum(f * tg * iv)) / denom
        resid = f - amp * tg
        chi2_array[i] = float(np.sum(resid**2 * iv) / good.sum())
    if progress is not None:
        progress(1.0, None)

    method_label = f"Template:{template_name}"
    solutions: list[ZSolution] = []
    for idx in find_top_minima(z_array, chi2_array, n=10, min_dz=0.02):
        model = np.interp(wave, t_wave * (1.0 + z_array[idx]), t_work, left=0.0, right=0.0)
        solutions.append(
            ZSolution(
                z=float(z_array[idx]),
                z_err=z_err_from_curvature(z_array, chi2_array, idx),
                chi2_dof=float(chi2_array[idx]),
                method=method_label,
                template_type=template_name,
                n_features=int(np.sum((ivar > 0) & (model != 0.0))),
            )
        )
    return ZFindResult(
        z_array=z_array,
        chi2_curves=[{"label": method_label, "chi2": chi2_array.copy()}],
        solutions=solutions,
        warnings=warn_list,
    )


def multi_template_search(
    prep: Prepared,
    templates: Sequence[str] | None = None,
    *,
    z_min: float | None = None,
    z_max: float | None = None,
    n_steps: int = 5000,
    data_norm: str = "normalize",
    model_norm: str = "normalize",
    smooth_pixels: int = 1,
    wave_min: float | None = None,
    wave_max: float | None = None,
    template_res_kwargs: Mapping[str, float] | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> ZFindResult:
    """``engine.multi_template_search``: one chi2 curve per template, solutions from the best."""
    names = list(templates) if templates else list(TEMPLATE_NAMES)
    results: dict[str, ZFindResult] = {}
    warn_all: list[str] = []
    for k, tname in enumerate(names):
        sub_progress = _sub_progress(progress, k, len(names), tname)
        try:
            r = template_search(
                prep,
                tname,
                z_min=z_min,
                z_max=z_max,
                n_steps=n_steps,
                data_norm=data_norm,
                model_norm=model_norm,
                smooth_pixels=smooth_pixels,
                wave_min=wave_min,
                wave_max=wave_max,
                template_res_kwargs=template_res_kwargs,
                progress=sub_progress,
                cancelled=cancelled,
            )
            results[tname] = r
            warn_all.extend(r.warnings)
        except InterruptedError:
            raise
        except Exception as exc:  # noqa: BLE001 - one failing template must not stop the others
            warn_all.append(f"{tname} failed: {exc}")
    if not results:
        raise RuntimeError("All templates failed.")
    first = next(iter(results.values()))
    curves = [{"label": t, "chi2": r.chi2_curves[0]["chi2"]} for t, r in results.items()]
    best = min(
        results, key=lambda t: results[t].solutions[0].chi2_dof if results[t].solutions else np.inf
    )
    return ZFindResult(
        z_array=first.z_array,
        chi2_curves=curves,
        solutions=results[best].solutions,
        warnings=list(dict.fromkeys(warn_all)),
    )


# --- mode 3: PCA search ------------------------------------------------------------------------


def pca_path(template_set: str) -> Path:
    fname = PCA_FILES.get(template_set)
    if fname is None:
        raise ValueError(f"Unknown PCA template set '{template_set}'. Available: {list(PCA_NAMES)}")
    path = TEMPLATE_DIR / "pca" / fname
    if not path.exists():
        raise FileNotFoundError(f"PCA template not found: {path}")
    return path


def load_pca(template_set: str) -> tuple[FloatArray, FloatArray]:
    """``_load_pca``: ``(rest wave, eigenvectors[n_comp, n_pix])``, downsampled to <= ~10k px.

    The bundled galaxy file already holds every 9th pixel of the redrock template (the stride
    rbcodes picks for 97 720 pixels), so both loaders return identical arrays.
    """
    from astropy.io import fits  # noqa: PLC0415 - lazy astropy

    with fits.open(pca_path(template_set)) as hdul:
        data = None
        hdr = None
        for h in hdul:
            if h.data is not None and np.ndim(h.data) == 2:
                data = np.asarray(h.data, dtype=np.float64)
                hdr = h.header
                break
        if data is None or hdr is None:
            raise ValueError(f"Cannot find 2-D eigenvector data in {pca_path(template_set)}")
        crval1 = float(hdr["CRVAL1"])
        cdelt1 = float(hdr["CDELT1"])
        naxis1 = int(hdr["NAXIS1"])
        ctype1 = str(hdr.get("CTYPE1", "")).lower()
    pix = np.arange(naxis1, dtype=np.float64)
    if "log" in ctype1 or crval1 < 10.0:
        wave = 10.0 ** (crval1 + cdelt1 * pix)
    else:
        wave = crval1 + cdelt1 * pix
    if data.ndim == 1:
        data = data[np.newaxis, :]
    max_pix = 10_000
    n_pix = data.shape[1]
    if n_pix > max_pix:
        step = n_pix // max_pix
        data = data[:, ::step]
        wave = wave[::step]
    return np.asarray(wave, dtype=np.float64), np.asarray(data, dtype=np.float64)


def pca_search(
    prep: Prepared,
    template_set: str = "galaxy",
    *,
    z_min: float | None = None,
    z_max: float | None = None,
    n_steps: int = 5000,
    data_norm: str = "normalize",
    model_norm: str = "normalize",
    smooth_pixels: int = 1,
    wave_min: float | None = None,
    wave_max: float | None = None,
    pca_res_kwargs: Mapping[str, float] | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> ZFindResult:
    """``engine.pca_search``: weighted least-squares fit of redrock eigenvectors at every z."""
    wave = prep.wave
    ivar = prep.ivar.copy()
    warn_list = list(prep.warnings)
    _mask_range(ivar, wave, wave_min, wave_max)
    flux_work = _flux_work(prep.flux, prep.continuum, data_norm, 0.0)
    if smooth_pixels > 1:
        flux_work = _boxcar(flux_work, smooth_pixels)

    t_wave, eigenvecs = load_pca(template_set)
    n_comp = eigenvecs.shape[0]
    if model_norm == "normalize":
        norms = np.sqrt(np.sum(eigenvecs**2, axis=1, keepdims=True))
        eigenvecs = eigenvecs / np.where(norms > 0, norms, 1.0)
    elif model_norm == "subtract":
        eigenvecs = eigenvecs - eigenvecs.mean(axis=1, keepdims=True)
    eigenvecs = _degrade(t_wave, eigenvecs, pca_res_kwargs)

    z_lo, z_hi = PCA_Z_RANGE.get(template_set, (0.0, 6.0))
    z_min = z_lo if z_min is None else z_min
    z_max = z_hi if z_max is None else z_max
    z_array = np.linspace(z_min, z_max, n_steps)
    chi2_array = np.full(n_steps, np.nan)
    wmin, wmax = float(wave.min()), float(wave.max())
    good = ivar > 0
    every = max(1, n_steps // 50)

    for i, z in enumerate(z_array):
        _tick(i, n_steps, every, progress, cancelled, "PCA search")
        t_obs = t_wave * (1.0 + z)
        overlap_lo = max(wmin, float(t_obs.min()))
        overlap_hi = min(wmax, float(t_obs.max()))
        if (overlap_hi - overlap_lo) < 0.2 * (wmax - wmin):
            continue
        basis = np.zeros((len(wave), n_comp), dtype=np.float64)
        for j in range(n_comp):
            basis[:, j] = np.interp(wave, t_obs, eigenvecs[j], left=0.0, right=0.0)
        if good.sum() < 50:
            continue
        mg, fg, ivg = basis[good], flux_work[good], ivar[good]
        wmg = mg * ivg[:, np.newaxis]
        a = wmg.T @ mg
        b = wmg.T @ fg
        try:
            c, _, _, _ = np.linalg.lstsq(a, b, rcond=None)
        except np.linalg.LinAlgError:
            continue
        resid = fg - mg @ c
        chi2_array[i] = float(np.sum(resid**2 * ivg) / good.sum())
    if progress is not None:
        progress(1.0, None)

    method_label = f"PCA:{template_set}"
    solutions = [
        ZSolution(
            z=float(z_array[idx]),
            z_err=z_err_from_curvature(z_array, chi2_array, idx),
            chi2_dof=float(chi2_array[idx]),
            method=method_label,
            template_type=template_set,
            n_features=n_comp,
        )
        for idx in find_top_minima(z_array, chi2_array, n=10, min_dz=0.02)
    ]
    return ZFindResult(
        z_array=z_array,
        chi2_curves=[{"label": method_label, "chi2": chi2_array.copy()}],
        solutions=solutions,
        warnings=warn_list,
    )


def multi_pca_search(
    prep: Prepared,
    template_sets: Sequence[str] | None = None,
    *,
    z_min: float | None = None,
    z_max: float | None = None,
    n_steps: int = 5000,
    data_norm: str = "normalize",
    model_norm: str = "normalize",
    smooth_pixels: int = 1,
    wave_min: float | None = None,
    wave_max: float | None = None,
    pca_res_kwargs: Mapping[str, float] | None = None,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
) -> ZFindResult:
    """``engine.multi_pca_search``: every set on its own z range, curves on a common grid."""
    names = list(template_sets) if template_sets else list(PCA_NAMES)
    results: dict[str, ZFindResult] = {}
    warn_all: list[str] = []
    for k, tset in enumerate(names):
        sub_progress = _sub_progress(progress, k, len(names), tset)
        try:
            r = pca_search(
                prep,
                tset,
                z_min=z_min,
                z_max=z_max,
                n_steps=n_steps,
                data_norm=data_norm,
                model_norm=model_norm,
                smooth_pixels=smooth_pixels,
                wave_min=wave_min,
                wave_max=wave_max,
                pca_res_kwargs=pca_res_kwargs,
                progress=sub_progress,
                cancelled=cancelled,
            )
            results[tset] = r
            warn_all.extend(r.warnings)
        except InterruptedError:
            raise
        except Exception as exc:  # noqa: BLE001 - one failing set must not stop the others
            warn_all.append(f"PCA:{tset} failed: {exc}")
    if not results:
        raise RuntimeError("All PCA template sets failed.")
    z_lo = min(float(r.z_array[0]) for r in results.values())
    z_hi = max(float(r.z_array[-1]) for r in results.values())
    z_array = np.linspace(z_lo, z_hi, n_steps)
    curves = [
        {
            "label": f"PCA:{tset}",
            "chi2": np.interp(
                z_array, r.z_array, r.chi2_curves[0]["chi2"], left=np.nan, right=np.nan
            ),
        }
        for tset, r in results.items()
    ]
    best = min(
        results, key=lambda t: results[t].solutions[0].chi2_dof if results[t].solutions else np.inf
    )
    return ZFindResult(
        z_array=z_array,
        chi2_curves=curves,
        solutions=results[best].solutions,
        warnings=list(dict.fromkeys(warn_all)),
    )


# --- adapters (rbcodes.GUIs.zfind.adapters) ----------------------------------------------------


def absorbers_to_multispec(
    result: AbsorberResult, accepted_indices: Sequence[int]
) -> list[dict[str, Any]]:
    """``adapters.absorbers_to_multispec``: ``[{zabs, name, label}]`` of the accepted candidates."""
    output: list[dict[str, Any]] = []
    for i, candidate in enumerate(result.candidates):
        if i in accepted_indices:
            output.append(
                {
                    "zabs": candidate.z,
                    "name": candidate.linelist_name,
                    "label": f"z={candidate.z:.4f} ({candidate.linelist_name})",
                }
            )
    return output


__all__ = [
    "PCA_NAMES",
    "PCA_Z_RANGE",
    "TEMPLATE_DIR",
    "TEMPLATE_NAMES",
    "TEMPLATE_Z_RANGE",
    "AbsorberCandidate",
    "AbsorberResult",
    "DataNorm",
    "PcaName",
    "Prepared",
    "TemplateName",
    "ZFindResult",
    "ZSolution",
    "absorbers_to_multispec",
    "air_to_vacuum",
    "find_top_minima",
    "line_search",
    "load_pca",
    "load_template",
    "mad_ivar",
    "multi_pca_search",
    "multi_template_search",
    "pca_search",
    "picket_fence_search",
    "preprocess",
    "template_search",
    "z_err_from_curvature",
]
