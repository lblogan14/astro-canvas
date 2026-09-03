"""``rbcodes.zfind.*`` nodes: the ``rb_zfind`` redshift finder as nodes.

Four search methods (line search, picket fence, MARZ templates, redrock PCA), the curated line
lists, a ``rank`` node with the ``z-accept`` editor that turns the candidates into a ``Redshift``
(the natural input of ``rbcodes.absorption.set_redshift``), and the absorber catalogue adapter.
Searches call rbcodes' engine when it is importable and the vendored kernels otherwise
(``_zfind_backend``); ``pca_search`` always uses the kernels so it can report progress and be
cancelled inside the process pool.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

import numpy as np
from astro_canvas_core.types import LineList, Redshift, Spectrum1D, Table

from astro_canvas.sdk import NodeContext, Param, node
from astro_canvas_rbcodes import _rb
from astro_canvas_rbcodes.kernels import zfind as Z
from astro_canvas_rbcodes.kernels.zfind_linelists import CuratedName, curated
from astro_canvas_rbcodes.nodes import _zfind_backend as B
from astro_canvas_rbcodes.types import (
    AbsorberCandidate,
    AbsorberResult,
    Statistic,
    ZCandidateRow,
    ZCandidates,
    ZCurve,
    ZFindResult,
    ZSolution,
)

CATEGORY = "rbcodes/Redshift"

ZMinParam = Annotated[float, Param(widget="redshift", min=-0.1, max=20.0, step=1e-3, label="z min")]
ZMaxParam = Annotated[float, Param(widget="redshift", min=-0.1, max=20.0, step=1e-3, label="z max")]
ZOptParam = Annotated[
    float | None,
    Param(
        widget="redshift",
        min=-0.1,
        max=20.0,
        step=1e-3,
        help="Leave empty to use the template's default redshift range.",
    ),
]
StepsParam = Annotated[int, Param(min=10, max=200000, label="Grid steps")]
DataNormParam = Annotated[
    Literal["subtract", "normalize", "raw"],
    Param(
        label="Data normalisation",
        help="subtract: flux - continuum; normalize: flux / continuum; raw: flux as is",
    ),
]
ModelNormParam = Annotated[
    Literal["normalize", "subtract", "raw"],
    Param(label="Model normalisation", help="How the template or eigenvectors are prepared"),
]
ContinuumParam = Annotated[
    B.ContinuumSource,
    Param(
        label="Continuum",
        help=(
            "fit: BIC-optimal Legendre polynomial (fit_optimal_polynomial); spectrum: the "
            "spectrum's own continuum array (SDSS 'model' columns are not continua); none: zero"
        ),
    ),
]
WaveLimitParam = Annotated[float | None, Param(widget="wavelength", advanced=True)]
WindowParam = Annotated[int, Param(min=1, max=100, label="Window half-width (px)")]
SmoothParam = Annotated[int, Param(min=1, max=101, label="Boxcar smoothing (px)", help="1 = off")]
FwhmParam = Annotated[
    float, Param(min=0.0, unit="Angstrom", label="Instrument FWHM", help="0 = not specified")
]


def _progress(ctx: NodeContext | None) -> Z.Progress | None:
    return ctx.progress if ctx is not None else None


def _cancelled(ctx: NodeContext | None) -> Z.Cancelled | None:
    return ctx.is_cancelled if ctx is not None else None


def _input_spec(spec: Spectrum1D, prep: Z.Prepared) -> Spectrum1D:
    """The searched spectrum as stored on the result: observed vacuum grid, fitted continuum."""
    continuum = prep.continuum if np.any(prep.continuum != 0.0) else None
    meta = {k: v for k, v in spec.meta.items() if k != "rbcodes"}
    meta["airvac"] = "vac"
    return Spectrum1D(
        wave=prep.wave,
        flux=prep.flux,
        error=spec.error,
        continuum=continuum,
        wave_unit="Angstrom",
        flux_unit=spec.flux_unit,
        frame="observed",
        z=None,
        meta=meta,
    )


def _solution(s: Z.ZSolution) -> ZSolution:
    return ZSolution(
        z=float(s.z),
        z_err=None if not math.isfinite(s.z_err) else float(s.z_err),
        chi2_dof=float(s.chi2_dof),
        method=s.method,
        template_type=s.template_type,
        n_features=int(s.n_features),
    )


def _zfind_port(
    result: Z.ZFindResult,
    *,
    input_spec: Spectrum1D,
    statistic: Statistic,
    linelist: str | None,
    backend: str | None = None,
    **params: Any,
) -> ZFindResult:
    provenance = _rb.provenance()
    if backend is not None:
        provenance["backend"] = backend
    return ZFindResult(
        z_array=result.z_array,
        curves=[ZCurve(label=str(c["label"]), values=c["chi2"]) for c in result.chi2_curves],
        solutions=[_solution(s) for s in result.solutions],
        input_spec=input_spec,
        warnings=list(result.warnings),
        statistic=statistic,
        linelist=linelist,
        meta={"rbcodes": provenance, "params": params},
    )


# --- line lists --------------------------------------------------------------------------------


@node(
    id="rbcodes.zfind.curated_linelist",
    name="Curated Line List",
    category=CATEGORY,
    icon="list-checks",
)
def curated_linelist(
    name: Annotated[CuratedName, Param(label="Preset")] = "zfind_galaxy",
) -> LineList:
    """One of ``rb_zfind``'s five curated presets (``zfind.linelists.get_curated_df``).

    ``zfind_em`` (nebular emission), ``zfind_stellar`` (stellar absorption), ``zfind_igm``
    (intervening absorbers), ``zfind_galaxy`` (emission + stellar absorption) and ``zfind_qso``
    (broad QSO lines). Each line carries a relative weight (oscillator strength for absorption,
    rbcodes' empirical 1-3 scale for emission) and a kind, both used by the picket fence.

    Args:
        name: Which preset to load.

    Returns:
        The lines with ``weight`` and ``kind`` columns (``fval`` repeats the weight).
    """
    table = curated(name)
    return LineList(
        wrest=table.wave,
        name=table.name,
        fval=table.weight,
        weight=table.weight,
        kind=table.kind,
        source=name,
    )


# --- searches ----------------------------------------------------------------------------------


@node(
    id="rbcodes.zfind.line_search",
    name="Line Search",
    category=CATEGORY,
    icon="scan-search",
    cost="auto",
)
def line_search(
    spec: Spectrum1D,
    linelist: LineList,
    z_min: ZMinParam = 0.0,
    z_max: ZMaxParam = 2.0,
    n_steps: StepsParam = 5000,
    continuum: ContinuumParam = "fit",
    window_pixels: WindowParam = 5,
    smooth_pixels: SmoothParam = 3,
    data_norm: DataNormParam = "subtract",
    wave_min: WaveLimitParam = None,
    wave_max: WaveLimitParam = None,
    ctx: NodeContext | None = None,
) -> ZFindResult:
    """Emission-line redshift scan (``zfind.engine.line_search`` in emission mode).

    For every trial redshift the continuum-subtracted flux is summed in a window around each
    line of the list; lines genuinely in emission lower the score, so the minima of the curve are
    the candidate redshifts (an SNR-like statistic, not a formal chi-square).

    Args:
        spec: Observed-frame spectrum (rest-frame input is shifted back with its ``z``).
        linelist: Rest wavelengths to match (a curated preset or any ``LineList``).
        z_min: Lower edge of the redshift grid.
        z_max: Upper edge of the redshift grid.
        n_steps: Number of grid points.
        continuum: Fit a polynomial continuum, use the spectrum's, or none.
        window_pixels: Half-width of the window around each line.
        smooth_pixels: Boxcar smoothing applied before the scan (1 = off).
        data_norm: How the flux is prepared before matching.
        wave_min: Ignore pixels below this observed wavelength.
        wave_max: Ignore pixels above this observed wavelength.

    Returns:
        The score curve, up to ten ranked solutions and the searched spectrum.
    """
    lines = B.line_table(linelist)
    prep = B.prepare(spec, continuum=continuum)
    result = B.line_search(
        spec,
        prep,
        lines,
        mode="emission",
        continuum=continuum,
        z_min=z_min,
        z_max=z_max,
        n_steps=n_steps,
        window_pixels=window_pixels,
        smooth_pixels=smooth_pixels,
        data_norm=data_norm,
        wave_min=wave_min,
        wave_max=wave_max,
        progress=_progress(ctx),
        cancelled=_cancelled(ctx),
    )
    assert isinstance(result, Z.ZFindResult)
    return _zfind_port(
        result,
        input_spec=_input_spec(spec, prep),
        statistic="score",
        linelist=lines.label,
        z_min=z_min,
        z_max=z_max,
        n_steps=n_steps,
        data_norm=data_norm,
    )


@node(
    id="rbcodes.zfind.absorber_search",
    name="Absorber Search",
    category=CATEGORY,
    icon="scan-line",
    cost="auto",
)
def absorber_search(
    spec: Spectrum1D,
    linelist: LineList,
    z_min: ZMinParam = 0.0,
    z_max: ZMaxParam = 2.0,
    n_steps: StepsParam = 5000,
    continuum: ContinuumParam = "fit",
    window_pixels: WindowParam = 5,
    smooth_pixels: SmoothParam = 3,
    data_norm: DataNormParam = "subtract",
    wave_min: WaveLimitParam = None,
    wave_max: WaveLimitParam = None,
    ctx: NodeContext | None = None,
) -> AbsorberResult:
    """Intervening-absorber scan (``zfind.engine.line_search`` in absorption mode).

    Same matched-filter scan as ``Line Search`` but counting lines in absorption; the score is
    turned into a significance curve (sigma above the noise floor) and up to twenty candidates
    are ranked by significance, since a QSO sightline holds several absorbers at different z.

    Args:
        spec: Observed-frame spectrum (the continuum is fitted unless ``continuum`` says otherwise).
        linelist: Absorption lines to match (``zfind_igm``, ``zfind_stellar`` or a custom list).
        z_min: Lower edge of the redshift grid.
        z_max: Upper edge of the redshift grid.
        n_steps: Number of grid points.
        continuum: Fit a polynomial continuum, use the spectrum's, or none.
        window_pixels: Half-width of the window around each line.
        smooth_pixels: Boxcar smoothing applied before the scan (1 = off).
        data_norm: How the flux is prepared before matching.
        wave_min: Ignore pixels below this observed wavelength.
        wave_max: Ignore pixels above this observed wavelength.

    Returns:
        The significance curve and the ranked absorber candidates.
    """
    lines = B.line_table(linelist, default_kind="absorption")
    prep = B.prepare(spec, continuum=continuum)
    result = B.line_search(
        spec,
        prep,
        lines,
        mode="absorption",
        continuum=continuum,
        z_min=z_min,
        z_max=z_max,
        n_steps=n_steps,
        window_pixels=window_pixels,
        smooth_pixels=smooth_pixels,
        data_norm=data_norm,
        wave_min=wave_min,
        wave_max=wave_max,
        progress=_progress(ctx),
        cancelled=_cancelled(ctx),
    )
    assert isinstance(result, Z.AbsorberResult)
    return AbsorberResult(
        z_array=result.z_array,
        significance_curve=result.significance_curve,
        candidates=[
            AbsorberCandidate(
                z=c.z,
                significance=c.significance,
                n_lines=c.n_lines,
                is_doublet=c.is_doublet,
                linelist_name=c.linelist_name,
                lines_matched=list(c.lines_matched),
            )
            for c in result.candidates
        ],
        input_spec=_input_spec(spec, prep),
        warnings=list(result.warnings),
        linelist=lines.label,
        meta={
            "rbcodes": _rb.provenance(),
            "params": {"z_min": z_min, "z_max": z_max, "n_steps": n_steps, "data_norm": data_norm},
        },
    )


@node(
    id="rbcodes.zfind.picket_fence_search",
    name="Picket Fence Search",
    category=CATEGORY,
    icon="fence",
    cost="auto",
)
def picket_fence_search(
    spec: Spectrum1D,
    linelist: LineList,
    z_min: ZMinParam = 0.0,
    z_max: ZMaxParam = 2.0,
    n_steps: StepsParam = 5000,
    line_type: Annotated[
        Literal["auto", "emission", "absorption"],
        Param(
            label="Line type",
            help="auto: the list's kind column (emission when absent); or force one type",
        ),
    ] = "auto",
    fwhm_ang: FwhmParam = 0.0,
    smooth_fwhm_pix: Annotated[
        float, Param(min=0.0, label="Gaussian smoothing FWHM (px)", help="0 = off")
    ] = 0.0,
    window_pixels: WindowParam = 5,
    window_fwhm: Annotated[
        float, Param(min=0.5, max=10.0, step=0.5, advanced=True, label="Window (x FWHM)")
    ] = 1.5,
    use_error: Annotated[
        Literal["auto", "always", "never"],
        Param(
            label="Use error array",
            help="auto: only when it looks like a real error spectrum, else MAD-STD",
        ),
    ] = "auto",
    continuum: ContinuumParam = "fit",
    data_norm: DataNormParam = "subtract",
    wave_min: WaveLimitParam = None,
    wave_max: WaveLimitParam = None,
    pf_mode: Annotated[
        Literal["direct", "detect_match"],
        Param(label="Mode", help="direct: weighted scan; detect_match: find peaks, then match"),
    ] = "direct",
    prominence_sigma: Annotated[
        float, Param(min=0.5, max=20.0, step=0.5, advanced=True, label="Peak prominence (sigma)")
    ] = 3.0,
    ctx: NodeContext | None = None,
) -> ZFindResult:
    """Weighted picket-fence redshift scan (``zfind.engine.picket_fence_search``, ``PicketFenceZ``).

    The method behind the ``rb_zfind`` dialog: each line contributes its matched-filter SNR
    weighted by the list's line strength, with a per-line sign check (emission above, absorption
    below the continuum), normalised by the square root of the total weight in range. Mode B
    detects peaks first and pairs them with the list.

    Args:
        spec: Observed-frame spectrum.
        linelist: Lines with weights and kinds (``Curated Line List``) or any ``LineList``.
        z_min: Lower edge of the redshift grid.
        z_max: Upper edge of the redshift grid.
        n_steps: Number of grid points.
        line_type: Treat every line as emission/absorption, or trust the list.
        fwhm_ang: Instrument resolution; sets the window to ``window_fwhm`` x FWHM.
        smooth_fwhm_pix: Gaussian pre-smoothing FWHM in pixels.
        window_pixels: Fallback half-window when no resolution is given.
        window_fwhm: Window half-width in FWHM units when ``fwhm_ang`` is set.
        use_error: Whether to trust the spectrum's error array.
        continuum: Fit a polynomial continuum, use the spectrum's, or none.
        data_norm: How the flux is prepared before matching.
        wave_min: Ignore pixels below this observed wavelength.
        wave_max: Ignore pixels above this observed wavelength.
        pf_mode: Direct scan or detect-then-match.
        prominence_sigma: Peak detection threshold for detect-then-match.

    Returns:
        The score curve, ranked solutions and the searched spectrum.
    """
    lines = B.line_table(linelist, default_kind=None if line_type == "auto" else line_type)
    if line_type != "auto":
        lines = lines.__class__(
            wave=lines.wave,
            name=lines.name,
            weight=lines.weight,
            kind=np.array([line_type] * len(lines), dtype=np.str_),
            label=lines.label,
        )
    use_error_map: dict[str, bool | str] = {"auto": "auto", "always": True, "never": False}
    use_error_value = use_error_map[use_error]
    prep = B.prepare(spec, continuum=continuum)
    result = B.picket_fence_search(
        spec,
        prep,
        lines,
        continuum=continuum,
        z_min=z_min,
        z_max=z_max,
        n_steps=n_steps,
        fwhm_ang=fwhm_ang,
        smooth_fwhm_pix=smooth_fwhm_pix if smooth_fwhm_pix > 0 else None,
        window_pixels=window_pixels,
        window_fwhm=window_fwhm,
        use_error=use_error_value,
        data_norm=data_norm,
        wave_min=wave_min,
        wave_max=wave_max,
        pf_mode=pf_mode,
        prominence_sigma=prominence_sigma,
        progress=_progress(ctx),
        cancelled=_cancelled(ctx),
    )
    return _zfind_port(
        result,
        input_spec=_input_spec(spec, prep),
        statistic="score",
        linelist=lines.label,
        z_min=z_min,
        z_max=z_max,
        n_steps=n_steps,
        pf_mode=pf_mode,
        fwhm_ang=fwhm_ang,
    )


@node(
    id="rbcodes.zfind.template_search",
    name="Template Search",
    category=CATEGORY,
    icon="file-search",
    cost="auto",
)
def template_search(
    spec: Spectrum1D,
    template_name: Annotated[Z.TemplateName, Param(label="Template")] = "LateTypeEmission",
    z_min: ZOptParam = None,
    z_max: ZOptParam = None,
    n_steps: StepsParam = 5000,
    continuum: ContinuumParam = "fit",
    data_norm: DataNormParam = "normalize",
    model_norm: ModelNormParam = "normalize",
    smooth_pixels: SmoothParam = 1,
    wave_min: WaveLimitParam = None,
    wave_max: WaveLimitParam = None,
    fwhm_ang: FwhmParam = 0.0,
    ctx: NodeContext | None = None,
) -> ZFindResult:
    """Chi-square scan against a bundled MARZ template (``zfind.engine.template_search``).

    At every trial redshift the template is interpolated onto the spectrum, scaled to the
    least-squares amplitude, and the reduced chi-square of the residual is recorded.

    Args:
        spec: Observed-frame spectrum.
        template_name: One of the five bundled MARZ templates.
        z_min: Lower edge of the grid (default: the template's range).
        z_max: Upper edge of the grid (default: the template's range).
        n_steps: Number of grid points.
        continuum: Fit a polynomial continuum, use the spectrum's, or none.
        data_norm: How the flux is prepared (``normalize`` suits the MARZ templates).
        model_norm: How the template is prepared (pseudo-continuum division by default).
        smooth_pixels: Boxcar smoothing of the data before the scan (1 = off).
        wave_min: Ignore pixels below this observed wavelength.
        wave_max: Ignore pixels above this observed wavelength.
        fwhm_ang: Degrade the template to this instrument FWHM before comparing.

    Returns:
        The chi-square curve, ranked solutions and the searched spectrum.
    """
    prep = B.prepare(spec, continuum=continuum)
    res_kwargs = {"fwhm_ang": fwhm_ang} if fwhm_ang > 0 else None
    result = B.template_search(
        spec,
        prep,
        template_name,
        continuum=continuum,
        z_min=z_min,
        z_max=z_max,
        n_steps=n_steps,
        data_norm=data_norm,
        model_norm=model_norm,
        smooth_pixels=smooth_pixels,
        wave_min=wave_min,
        wave_max=wave_max,
        template_res_kwargs=res_kwargs,
        progress=_progress(ctx),
        cancelled=_cancelled(ctx),
    )
    return _zfind_port(
        result,
        input_spec=_input_spec(spec, prep),
        statistic="chi2",
        linelist=None,
        template=template_name,
        n_steps=n_steps,
    )


@node(
    id="rbcodes.zfind.multi_template_search",
    name="Multi-Template Search",
    category=CATEGORY,
    icon="files",
    cost="auto",
)
def multi_template_search(
    spec: Spectrum1D,
    templates: Annotated[
        list[Z.TemplateName], Param(label="Templates", help="Empty: all five templates")
    ] = [],  # noqa: B006 - pydantic copies the default
    z_min: ZOptParam = None,
    z_max: ZOptParam = None,
    n_steps: StepsParam = 3000,
    continuum: ContinuumParam = "fit",
    data_norm: DataNormParam = "normalize",
    model_norm: ModelNormParam = "normalize",
    smooth_pixels: SmoothParam = 1,
    wave_min: WaveLimitParam = None,
    wave_max: WaveLimitParam = None,
    fwhm_ang: FwhmParam = 0.0,
    ctx: NodeContext | None = None,
) -> ZFindResult:
    """``Template Search`` over several templates (``zfind.engine.multi_template_search``).

    One chi-square curve per template on a common grid; the solutions come from the template
    with the lowest chi-square.

    Args:
        spec: Observed-frame spectrum.
        templates: Templates to try (empty = all).
        z_min: Lower edge of the grid (default: each template's range).
        z_max: Upper edge of the grid.
        n_steps: Number of grid points.
        continuum: Fit a polynomial continuum, use the spectrum's, or none.
        data_norm: How the flux is prepared.
        model_norm: How the templates are prepared.
        smooth_pixels: Boxcar smoothing of the data (1 = off).
        wave_min: Ignore pixels below this observed wavelength.
        wave_max: Ignore pixels above this observed wavelength.
        fwhm_ang: Degrade the templates to this instrument FWHM.

    Returns:
        All curves plus the best template's solutions.
    """
    prep = B.prepare(spec, continuum=continuum)
    names: list[str] = list(templates) or list(Z.TEMPLATE_NAMES)
    result = Z.multi_template_search(
        prep,
        names,
        z_min=z_min,
        z_max=z_max,
        n_steps=n_steps,
        data_norm=data_norm,
        model_norm=model_norm,
        smooth_pixels=smooth_pixels,
        wave_min=wave_min,
        wave_max=wave_max,
        template_res_kwargs={"fwhm_ang": fwhm_ang} if fwhm_ang > 0 else None,
        progress=_progress(ctx),
        cancelled=_cancelled(ctx),
    )
    return _zfind_port(
        result,
        input_spec=_input_spec(spec, prep),
        statistic="chi2",
        linelist=None,
        backend="vendored",
        templates=names,
        n_steps=n_steps,
    )


@node(
    id="rbcodes.zfind.pca_search",
    name="PCA Search",
    category=CATEGORY,
    icon="cpu",
    cost="expensive",
)
def pca_search(
    spec: Spectrum1D,
    template_set: Annotated[Z.PcaName, Param(label="Eigenvector set")] = "galaxy",
    z_min: ZOptParam = None,
    z_max: ZOptParam = None,
    n_steps: StepsParam = 5000,
    continuum: ContinuumParam = "fit",
    data_norm: DataNormParam = "normalize",
    model_norm: ModelNormParam = "normalize",
    smooth_pixels: SmoothParam = 1,
    wave_min: WaveLimitParam = None,
    wave_max: WaveLimitParam = None,
    resolving_power: Annotated[
        float, Param(min=0.0, label="Resolving power R", help="0 = no convolution")
    ] = 0.0,
    ctx: NodeContext | None = None,
) -> ZFindResult:
    """Redrock-style PCA redshift scan (``zfind.engine.pca_search``), run in the process pool.

    At each trial redshift the DESI redrock eigenvectors are shifted, interpolated onto the
    spectrum and fitted by weighted least squares; the reduced chi-square of the best linear
    combination is the curve. Expensive: press Run; progress is reported and Cancel stops it.

    Args:
        spec: Observed-frame spectrum.
        template_set: ``galaxy`` (10 components), ``qso_loz`` or ``qso_hiz`` (4 each).
        z_min: Lower edge of the grid (default: the set's range).
        z_max: Upper edge of the grid.
        n_steps: Number of grid points.
        continuum: Fit a polynomial continuum, use the spectrum's, or none.
        data_norm: How the flux is prepared.
        model_norm: ``normalize`` (L2), ``subtract`` (mean-centre) or ``raw`` eigenvectors.
        smooth_pixels: Boxcar smoothing of the data (1 = off).
        wave_min: Ignore pixels below this observed wavelength.
        wave_max: Ignore pixels above this observed wavelength.
        resolving_power: Convolve the eigenvectors to this R before the scan.

    Returns:
        The chi-square curve, ranked solutions and the searched spectrum.
    """
    prep = B.prepare(spec, continuum=continuum)
    result = Z.pca_search(
        prep,
        template_set,
        z_min=z_min,
        z_max=z_max,
        n_steps=n_steps,
        data_norm=data_norm,
        model_norm=model_norm,
        smooth_pixels=smooth_pixels,
        wave_min=wave_min,
        wave_max=wave_max,
        pca_res_kwargs={"R": resolving_power} if resolving_power > 0 else None,
        progress=_progress(ctx),
        cancelled=_cancelled(ctx),
    )
    return _zfind_port(
        result,
        input_spec=_input_spec(spec, prep),
        statistic="chi2",
        linelist=None,
        backend="vendored",
        template_set=template_set,
        n_steps=n_steps,
    )


@node(
    id="rbcodes.zfind.multi_pca_search",
    name="Multi-PCA Search",
    category=CATEGORY,
    icon="cpu",
    cost="expensive",
)
def multi_pca_search(
    spec: Spectrum1D,
    template_sets: Annotated[
        list[Z.PcaName], Param(label="Eigenvector sets", help="Empty: galaxy, qso_loz, qso_hiz")
    ] = [],  # noqa: B006 - pydantic copies the default
    z_min: ZOptParam = None,
    z_max: ZOptParam = None,
    n_steps: StepsParam = 3000,
    continuum: ContinuumParam = "fit",
    data_norm: DataNormParam = "normalize",
    model_norm: ModelNormParam = "normalize",
    smooth_pixels: SmoothParam = 1,
    wave_min: WaveLimitParam = None,
    wave_max: WaveLimitParam = None,
    resolving_power: Annotated[
        float, Param(min=0.0, label="Resolving power R", help="0 = no convolution")
    ] = 0.0,
    ctx: NodeContext | None = None,
) -> ZFindResult:
    """``PCA Search`` over several eigenvector sets (``zfind.engine.multi_pca_search``).

    Each set runs on its own default redshift range unless limits are given; the curves are
    interpolated onto the union grid and the solutions come from the best set.

    Args:
        spec: Observed-frame spectrum.
        template_sets: Sets to try (empty = all three).
        z_min: Lower edge of the grid (default: per set).
        z_max: Upper edge of the grid.
        n_steps: Number of grid points.
        continuum: Fit a polynomial continuum, use the spectrum's, or none.
        data_norm: How the flux is prepared.
        model_norm: How the eigenvectors are prepared.
        smooth_pixels: Boxcar smoothing of the data (1 = off).
        wave_min: Ignore pixels below this observed wavelength.
        wave_max: Ignore pixels above this observed wavelength.
        resolving_power: Convolve the eigenvectors to this R before the scan.

    Returns:
        One curve per set plus the best set's solutions.
    """
    prep = B.prepare(spec, continuum=continuum)
    names: list[str] = list(template_sets) or list(Z.PCA_NAMES)
    result = Z.multi_pca_search(
        prep,
        names,
        z_min=z_min,
        z_max=z_max,
        n_steps=n_steps,
        data_norm=data_norm,
        model_norm=model_norm,
        smooth_pixels=smooth_pixels,
        wave_min=wave_min,
        wave_max=wave_max,
        pca_res_kwargs={"R": resolving_power} if resolving_power > 0 else None,
        progress=_progress(ctx),
        cancelled=_cancelled(ctx),
    )
    return _zfind_port(
        result,
        input_spec=_input_spec(spec, prep),
        statistic="chi2",
        linelist=None,
        backend="vendored",
        template_sets=names,
        n_steps=n_steps,
    )


# --- ranking and acceptance --------------------------------------------------------------------


def combine_candidates(results: list[ZFindResult]) -> tuple[list[ZCandidateRow], list[Statistic]]:
    """The candidate table of ``rank``: every source's solutions in order, sources in input order.

    Statistics differ between methods (a picket-fence score is not a chi-square), so candidates
    are never re-sorted across sources; ``index`` is the position in this table and what
    ``accepted`` refers to.
    """
    rows: list[ZCandidateRow] = []
    statistics: list[Statistic] = []
    for source, result in enumerate(results):
        statistics.append(result.statistic)
        for rank_in_source, solution in enumerate(result.solutions):
            rows.append(
                ZCandidateRow(
                    index=len(rows),
                    source=source,
                    rank=rank_in_source,
                    z=solution.z,
                    z_err=solution.z_err,
                    score=solution.chi2_dof,
                    method=solution.method,
                    template_type=solution.template_type,
                    n_features=solution.n_features,
                )
            )
    return rows, statistics


@node(
    id="rbcodes.zfind.rank",
    name="Rank and Accept",
    category=CATEGORY,
    icon="check-check",
    outputs=("redshift", "candidates"),
    editor="z-accept",
)
def rank(
    results: ZFindResult,
    results_2: ZFindResult | None = None,
    results_3: ZFindResult | None = None,
    results_4: ZFindResult | None = None,
    accepted: Annotated[
        int | None,
        Param(
            min=0, label="Accepted candidate", help="Row index in the candidate table; empty = best"
        ),
    ] = None,
) -> tuple[Redshift, ZCandidates]:
    """Collect the candidates of up to four scans and accept one as the redshift.

    Open the **z-accept** editor to click a candidate on the curve, see the line list overlaid
    on the spectrum at that redshift and Apply; the chosen row index is stored in ``accepted``.
    Without a choice the best solution of the first scan is used. Feed the ``redshift`` output
    to ``rbcodes.absorption.set_redshift``.

    Args:
        results: Primary scan.
        results_2: Optional second scan (another method or line list).
        results_3: Optional third scan.
        results_4: Optional fourth scan.
        accepted: Index of the accepted row in the candidate table.

    Returns:
        The accepted redshift (with the curvature error and the method) and the candidate table.
    """
    sources = [r for r in (results, results_2, results_3, results_4) if r is not None]
    rows, statistics = combine_candidates(sources)
    if not rows:
        raise ValueError("no redshift candidates: every connected scan came back empty")
    index = 0 if accepted is None else int(accepted)
    if not 0 <= index < len(rows):
        raise ValueError(f"accepted candidate {index} is out of range (0..{len(rows) - 1})")
    row = rows[index]
    redshift = Redshift(z=row.z, z_err=row.z_err, method=row.method, source="rbcodes.zfind.rank")
    return redshift, ZCandidates(rows=rows, accepted=index, statistics=statistics)


@node(
    id="rbcodes.zfind.absorbers_to_catalog",
    name="Absorber Catalog",
    category=CATEGORY,
    icon="table",
)
def absorbers_to_catalog(
    result: AbsorberResult,
    accepted: Annotated[
        list[int],
        Param(
            label="Accepted candidates", help="Row indices of the ranked candidates; empty = all"
        ),
    ] = [],  # noqa: B006 - pydantic copies the default
) -> Table:
    """Accepted absorber candidates as a catalogue (``zfind.adapters.absorbers_to_multispec``).

    The ``zabs``/``name``/``label`` columns are the dictionary rb_multispec's absorber manager
    expects; ``significance``, ``n_lines`` and ``lines_matched`` are added for convenience.

    Args:
        result: The absorber scan.
        accepted: Which candidates to keep (indices into the ranked list; empty = all).

    Returns:
        One row per accepted candidate, in ranked order.
    """
    indices = list(range(len(result.candidates))) if not accepted else [int(i) for i in accepted]
    kernel_result = Z.AbsorberResult(
        z_array=result.z_array,
        significance_curve=result.significance_curve,
        candidates=[
            Z.AbsorberCandidate(
                z=c.z,
                significance=c.significance,
                n_lines=c.n_lines,
                is_doublet=c.is_doublet,
                linelist_name=c.linelist_name,
                lines_matched=list(c.lines_matched),
            )
            for c in result.candidates
        ],
    )
    rows = Z.absorbers_to_multispec(kernel_result, indices)
    kept = [c for i, c in enumerate(result.candidates) if i in indices]
    return Table(
        columns={
            "zabs": np.array([r["zabs"] for r in rows], dtype=np.float64),
            "name": np.array([r["name"] for r in rows], dtype=np.str_),
            "label": np.array([r["label"] for r in rows], dtype=np.str_),
            "significance": np.array([c.significance for c in kept], dtype=np.float64),
            "n_lines": np.array([c.n_lines for c in kept], dtype=np.int64),
            "lines_matched": np.array([", ".join(c.lines_matched) for c in kept], dtype=np.str_),
        },
        meta={"rbcodes": _rb.provenance(), "source": "rbcodes.zfind.absorbers_to_catalog"},
    )


__all__ = [
    "absorber_search",
    "absorbers_to_catalog",
    "combine_candidates",
    "curated_linelist",
    "line_search",
    "multi_pca_search",
    "multi_template_search",
    "pca_search",
    "picket_fence_search",
    "rank",
    "template_search",
]
