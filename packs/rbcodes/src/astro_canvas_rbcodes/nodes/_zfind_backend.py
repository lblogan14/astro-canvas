"""rbcodes-first dispatch for the zfind searches (``rbcodes.GUIs.zfind.engine`` or the kernels).

When rbcodes is importable the observed spectrum is wrapped in an ``rb_spectrum`` and the line
list in a DataFrame, and rbcodes' own engine runs; otherwise the vendored kernels do. Both return
the kernel dataclasses (rbcodes' ``io`` dataclasses are copied attribute for attribute), so the
node code is backend-agnostic. ``pca_search`` always uses the kernels: it runs in the process pool
and needs the progress/cancel hooks rbcodes does not have (same choice as ``full_spectrum``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

import numpy as np
from astro_canvas_core.types import LineList, Spectrum1D

from astro_canvas_rbcodes import _rb
from astro_canvas_rbcodes.kernels import zfind as Z
from astro_canvas_rbcodes.kernels.zfind_linelists import LineTable
from astro_canvas_rbcodes.nodes._common import FloatArray

Progress = Callable[[float, str | None], None]
Cancelled = Callable[[], bool]


ContinuumSource = Literal["fit", "spectrum", "none"]
"""Where the continuum comes from: a fresh BIC polynomial fit (rbcodes' behaviour for files
without one; SDSS ``model`` columns are *not* continua), the spectrum's own ``continuum`` array
(fitted when absent), or none at all (zero continuum, rbcodes' ``fit_continuum=False``)."""


def observed_arrays(
    spec: Spectrum1D, continuum: ContinuumSource = "spectrum"
) -> tuple[FloatArray, FloatArray, FloatArray | None, FloatArray | None]:
    """``(wave, flux, error, continuum)`` in the observed frame (rest input is shifted back)."""
    if spec.frame == "velocity":
        raise ValueError("the redshift finder needs a wavelength spectrum, not a velocity slice")
    wave = np.asarray(spec.wave, dtype=np.float64)
    if spec.frame == "rest" and spec.z is not None:
        wave = wave * (1.0 + spec.z)
    flux = np.asarray(spec.flux, dtype=np.float64)
    error = np.asarray(spec.error, dtype=np.float64) if spec.error is not None else None
    cont = None
    if continuum == "spectrum" and spec.continuum is not None:
        cont = np.asarray(spec.continuum, dtype=np.float64)
    return wave, flux, error, cont


def fit_flag(continuum: ContinuumSource) -> bool:
    """rbcodes' ``fit_continuum`` argument for a continuum source."""
    return continuum != "none"


def airvac_of(spec: Spectrum1D) -> str:
    value = spec.meta.get("airvac", "vac")
    return "air" if str(value).lower() == "air" else "vac"


def line_table(linelist: LineList, default_kind: str | None = None) -> LineTable:
    """A kernel ``LineTable`` from a core ``LineList`` (missing weights = 1, kinds = emission)."""
    kind: Any = linelist.kind if linelist.kind is not None else default_kind
    return LineTable.build(
        linelist.wrest,
        linelist.name,
        weight=linelist.weight,
        kind=kind,
        label=linelist.source or "custom",
    )


def _rb_spectrum(
    wave: FloatArray,
    flux: FloatArray,
    error: FloatArray | None,
    cont: FloatArray | None,
    airvac: str,
) -> Any:
    import astropy.units as u  # noqa: PLC0415 - only with rbcodes installed
    from rbcodes.utils.rb_spectrum import rb_spectrum  # noqa: PLC0415

    unit = u.dimensionless_unscaled
    return rb_spectrum(
        wave * u.AA,
        flux * unit,
        error=error * unit if error is not None else None,
        continuum=cont * unit if cont is not None else None,
        meta={"airvac": airvac},
    )


def _dataframe(lines: LineTable) -> Any:
    import pandas as pd  # noqa: PLC0415 - rbcodes depends on pandas

    df = pd.DataFrame(
        {"wave": lines.wave, "name": lines.name, "weight": lines.weight, "type": lines.kind}
    )
    df.attrs["name"] = lines.label
    return df


def _copy_zfind(result: Any) -> Z.ZFindResult:
    return Z.ZFindResult(
        z_array=np.asarray(result.z_array, dtype=np.float64),
        chi2_curves=[
            {"label": str(c["label"]), "chi2": np.asarray(c["chi2"], dtype=np.float64)}
            for c in result.chi2_curves
        ],
        solutions=[
            Z.ZSolution(
                z=float(s.z),
                z_err=float(s.z_err),
                chi2_dof=float(s.chi2_dof),
                method=str(s.method),
                template_type=str(s.template_type),
                n_features=int(s.n_features),
            )
            for s in result.solutions
        ],
        warnings=[str(w) for w in result.warnings],
    )


def _copy_absorbers(result: Any) -> Z.AbsorberResult:
    return Z.AbsorberResult(
        z_array=np.asarray(result.z_array, dtype=np.float64),
        significance_curve=np.asarray(result.significance_curve, dtype=np.float64),
        candidates=[
            Z.AbsorberCandidate(
                z=float(c.z),
                significance=float(c.significance),
                n_lines=int(c.n_lines),
                is_doublet=bool(c.is_doublet),
                linelist_name=str(c.linelist_name),
                lines_matched=[str(v) for v in c.lines_matched],
            )
            for c in result.candidates
        ],
        warnings=[str(w) for w in result.warnings],
    )


def prepare(spec: Spectrum1D, *, continuum: ContinuumSource) -> Z.Prepared:
    wave, flux, error, cont = observed_arrays(spec, continuum)
    return Z.preprocess(
        wave, flux, error, cont, fit_continuum=fit_flag(continuum), airvac=airvac_of(spec)
    )


def line_search(
    spec: Spectrum1D,
    prep: Z.Prepared,
    lines: LineTable,
    *,
    mode: str,
    continuum: ContinuumSource,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
    **kwargs: Any,
) -> Z.ZFindResult | Z.AbsorberResult:
    engine = _rb.import_rbcodes("GUIs.zfind.engine")
    if engine is not None:
        wave, flux, error, cont = observed_arrays(spec, continuum)
        result = engine.line_search(
            _rb_spectrum(wave, flux, error, cont, airvac_of(spec)),
            _dataframe(lines),
            mode=mode,
            fit_continuum=fit_flag(continuum),
            **kwargs,
        )
        return _copy_zfind(result) if mode == "emission" else _copy_absorbers(result)
    return Z.line_search(prep, lines, mode=mode, progress=progress, cancelled=cancelled, **kwargs)


def picket_fence_search(
    spec: Spectrum1D,
    prep: Z.Prepared,
    lines: LineTable,
    *,
    continuum: ContinuumSource,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
    **kwargs: Any,
) -> Z.ZFindResult:
    engine = _rb.import_rbcodes("GUIs.zfind.engine")
    if engine is not None:
        wave, flux, error, cont = observed_arrays(spec, continuum)
        rb_kwargs = dict(kwargs)
        if "resolution" in rb_kwargs:
            rb_kwargs["res_kwargs"] = rb_kwargs.pop("resolution")
        result = engine.picket_fence_search(
            _rb_spectrum(wave, flux, error, cont, airvac_of(spec)),
            _dataframe(lines),
            fit_continuum=fit_flag(continuum),
            **rb_kwargs,
        )
        return _copy_zfind(result)
    return Z.picket_fence_search(prep, lines, progress=progress, cancelled=cancelled, **kwargs)


def template_search(
    spec: Spectrum1D,
    prep: Z.Prepared,
    template_name: str,
    *,
    continuum: ContinuumSource,
    progress: Progress | None = None,
    cancelled: Cancelled | None = None,
    **kwargs: Any,
) -> Z.ZFindResult:
    engine = _rb.import_rbcodes("GUIs.zfind.engine")
    if engine is not None:
        wave, flux, error, cont = observed_arrays(spec, continuum)
        result = engine.template_search(
            _rb_spectrum(wave, flux, error, cont, airvac_of(spec)),
            template_name=template_name,
            fit_continuum=fit_flag(continuum),
            **kwargs,
        )
        return _copy_zfind(result)
    return Z.template_search(prep, template_name, progress=progress, cancelled=cancelled, **kwargs)


__all__ = [
    "ContinuumSource",
    "airvac_of",
    "fit_flag",
    "line_search",
    "line_table",
    "observed_arrays",
    "picket_fence_search",
    "prepare",
    "template_search",
]
