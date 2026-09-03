"""``rbcodes.absorption.*`` nodes: the ``rb_spec`` pipeline (shift, slice, measure) as nodes."""

from __future__ import annotations

from typing import Annotated, Any, Literal

import numpy as np
from astro_canvas_core.types import EWMeasurement, Figure, Redshift, Spectrum1D, Transition

from astro_canvas.sdk import Param, node
from astro_canvas_rbcodes.nodes._common import (
    C_KMS,
    rb_meta,
    require_error,
    rest_wavelength,
    velocity_of,
    with_rb_meta,
)
from astro_canvas_rbcodes.nodes._common import (
    compute_ew as _compute_ew,
)
from astro_canvas_rbcodes.nodes.lines import LineListParam, lookup

ZParam = Annotated[float, Param(widget="redshift", min=-0.1, max=20.0, step=1e-4)]
VelParam = Annotated[float, Param(unit="km / s", step=10.0)]
MethodParam = Annotated[
    Literal["closest", "Exact"],
    Param(label="Match", help="closest: nearest line in the list; Exact: within 0.001 A"),
]


@node(
    id="rbcodes.absorption.set_redshift",
    name="Set Redshift",
    category="rbcodes/Absorption",
    icon="move-horizontal",
)
def set_redshift(
    spec: Spectrum1D,
    z: ZParam = 0.0,
    redshift: Redshift | None = None,
) -> Spectrum1D:
    """Shift the spectrum to the absorber rest frame (``rb_spec.shift_spec``).

    Divides the observed wavelengths by ``1 + z``. A connected ``Redshift`` (for example from the
    redshift finder) overrides the ``z`` parameter. Rest-frame input is re-shifted from its own
    redshift, so changing ``z`` never compounds.

    Args:
        spec: Observed-frame spectrum (or a rest-frame one to re-shift).
        z: Absorber redshift.
        redshift: Optional redshift port; wins over ``z`` when connected.

    Returns:
        The rest-frame spectrum with ``frame='rest'`` and ``z`` recorded.
    """
    if spec.frame == "velocity":
        raise ValueError("Set Redshift needs a wavelength spectrum, not a velocity slice")
    z_value = float(redshift.z) if redshift is not None else float(z)
    observed = (
        spec.wave * (1.0 + spec.z) if spec.frame == "rest" and spec.z is not None else spec.wave
    )
    meta = with_rb_meta(spec, zabs=z_value)
    return spec.model_copy(
        update={"wave": observed / (1.0 + z_value), "frame": "rest", "z": z_value, "meta": meta}
    )


@node(
    id="rbcodes.absorption.set_transition",
    name="Set Transition",
    category="rbcodes/Absorption",
    icon="crosshair",
    editor="line-picker",
)
def set_transition(
    spec: Spectrum1D | None = None,
    wrest: Annotated[float, Param(unit="Angstrom", widget="wavelength", min=0.0)] = 2796.35,
    linelist: LineListParam = "atom",
    method: MethodParam = "closest",
    transition: Transition | None = None,
) -> Transition:
    """Choose the transition to measure (``rb_setline``), with a line-picker editor.

    The editor shows the rest-frame spectrum and lists the transitions of ``linelist`` nearest to
    a clicked feature, with doublet partners marked. Connecting a ``Transition`` port bypasses
    the lookup.

    Args:
        spec: Rest-frame spectrum, only used by the editor to display candidate lines.
        wrest: Approximate rest wavelength of the line (Angstrom).
        linelist: rbcodes line list to search.
        method: ``closest`` or ``Exact`` matching.
        transition: Optional transition port; wins over the lookup when connected.

    Returns:
        The selected transition.
    """
    if transition is not None:
        return transition
    return lookup(wrest, method, linelist)


@node(
    id="rbcodes.absorption.slice",
    name="Slice Spectrum",
    category="rbcodes/Absorption",
    icon="scissors-line-dashed",
    editor="range-select",
)
def slice_spectrum(
    spec: Spectrum1D,
    transition: Transition,
    vmin: VelParam = -1500.0,
    vmax: VelParam = 1500.0,
    use_vel: Annotated[bool, Param(label="Limits in km/s", advanced=True)] = True,
) -> Spectrum1D:
    """Cut a window around the transition and convert it to velocity (``rb_spec.slice_spec``).

    Velocities follow rbcodes: ``v = (lambda_rest - wrest) c / wrest`` with ``c = 2.9979e5``.
    With ``use_vel`` off the limits are rest wavelengths in Angstrom instead.

    Args:
        spec: Rest-frame spectrum (from ``Set Redshift``).
        transition: The transition the window is centred on.
        vmin: Lower limit (km/s, or Angstrom when ``use_vel`` is off).
        vmax: Upper limit.
        use_vel: Interpret the limits as velocities.

    Returns:
        The slice on a velocity axis (``frame='velocity'``, ``v0_wrest`` = the transition).
    """
    wave_rest = rest_wavelength(spec)
    vel = velocity_of(wave_rest, transition.wrest)
    axis = vel if use_vel else wave_rest
    keep = (axis >= vmin) & (axis <= vmax)
    if not keep.any():
        unit = "km/s" if use_vel else "A"
        raise ValueError(
            f"No data points found in range [{vmin}, {vmax}] {unit}. "
            f"Available range: [{axis.min():.1f}, {axis.max():.1f}] {unit}"
        )
    update: dict[str, Any] = {
        name: getattr(spec, name)[keep]
        for name in ("flux", "error", "continuum")
        if getattr(spec, name) is not None
    }
    scale = float(np.nanmedian(spec.flux))
    if not np.isfinite(scale) or scale == 0:
        scale = 1.0
    update.update(
        {
            "wave": vel[keep],
            "frame": "velocity",
            "wave_unit": "km / s",
            "v0_wrest": float(transition.wrest),
            "z": spec.z,
            "meta": with_rb_meta(
                spec,
                transition=float(transition.wrest),
                transition_name=transition.name,
                slice_spec_lam_min=float(vmin),
                slice_spec_lam_max=float(vmax),
                slice_spec_method=bool(use_vel),
                flux_scale=scale,
            ),
        }
    )
    return spec.model_copy(update=update)


@node(
    id="rbcodes.absorption.compute_ew",
    name="Equivalent Width",
    category="rbcodes/Absorption",
    icon="ruler",
)
def compute_ew(
    spec: Spectrum1D,
    transition: Transition,
    vmin: VelParam = -200.0,
    vmax: VelParam = 200.0,
    snr: Annotated[bool, Param(label="Estimate SNR")] = False,
    binsize: Annotated[int, Param(min=1, max=50, advanced=True, label="SNR bin size")] = 1,
    saturation: Annotated[
        Literal["auto", "custom", "off"],
        Param(
            label="Saturation limit",
            help="auto: median error in the window; custom: the threshold below; off: disabled",
        ),
    ] = "auto",
    sat_threshold: Annotated[float, Param(min=0.0, advanced=True, label="Custom threshold")] = 0.0,
) -> EWMeasurement:
    """Rest-frame equivalent width and AOD column density (``IGM.compute_EW``).

    Integrates the normalised flux between ``vmin`` and ``vmax``; the apparent optical depth
    gives ``N`` and ``logN`` (``logN = 0`` with ``logN_e`` as the 1-sigma limit for
    non-detections, like ``rb_spec.compute_EW``). Saturated pixels are replaced by their error
    when they fall below the saturation limit.

    Args:
        spec: Continuum-normalised velocity slice (from ``Fit Continuum``).
        transition: The measured transition (rest wavelength and oscillator strength).
        vmin: Lower integration limit (km/s).
        vmax: Upper integration limit (km/s).
        snr: Also estimate the signal-to-noise ratio of the slice.
        binsize: Pixels per bin for the SNR estimate.
        saturation: How the saturation threshold is chosen.
        sat_threshold: Threshold used when ``saturation='custom'``.

    Returns:
        ``W``, ``W_e``, ``N``, ``N_e``, ``logN``, ``logN_e``, velocity centroid and dispersion.
    """
    wave_rest = rest_wavelength(spec)
    error = require_error(spec)
    sat_limit: float | str | None
    if saturation == "auto":
        sat_limit = "auto"
    elif saturation == "off":
        sat_limit = None
    else:
        sat_limit = float(sat_threshold)
    out = _compute_ew(
        wave_rest,
        np.asarray(spec.flux, dtype=np.float64),
        float(transition.wrest),
        [float(vmin), float(vmax)],
        error,
        f0=float(transition.fval),
        sat_limit=sat_limit,
        snr=snr,
        binsize=int(binsize),
    )
    n_col = float(out["col"])
    n_err = float(out["colerr"])
    if n_col > 0:
        log_n = float(np.log10(n_col))
        log_n_e = 0.434 * n_err / n_col
    else:
        log_n = 0.0
        log_n_e = float(np.log10(n_err)) if n_err > 0 else 0.0
    return EWMeasurement(
        W=float(out["ew_tot"]),
        W_e=float(out["err_ew_tot"]),
        N=n_col,
        N_e=n_err,
        logN=log_n,
        logN_e=float(log_n_e),
        vel_centroid=float(out["med_vel"]),
        vel_disp=float(out["vel_disp"]),
        vel50_err=float(out["vel50_err"]),
        SNR=float(out["SNR"]) if snr else None,
        saturated=bool(out["line_saturation"]),
        flag=1 if out["line_saturation"] else 0,
        vmin=float(vmin),
        vmax=float(vmax),
        transition=transition,
    )


@node(
    id="rbcodes.absorption.doublet_check",
    name="Doublet Check",
    category="rbcodes/Absorption",
    icon="columns-2",
)
def doublet_check(
    spec: Spectrum1D,
    lam1: Annotated[float, Param(unit="Angstrom", widget="wavelength", min=0.0)] = 2796.35,
    lam2: Annotated[float, Param(unit="Angstrom", widget="wavelength", min=0.0)] = 2803.53,
    vmin: VelParam = -600.0,
    vmax: VelParam = 600.0,
    linelist: LineListParam = "atom",
    method: MethodParam = "closest",
) -> Figure:
    """Stack the normalised flux in velocity around two transitions (``rb_spec.plot_doublet``).

    A real doublet shows the same velocity structure in both panels with the expected strength
    ratio; a coincidence does not.

    Args:
        spec: Normalised slice (or any rest-frame / velocity spectrum with a reference line).
        lam1: First member of the doublet (Angstrom).
        lam2: Second member (Angstrom).
        vmin: Lower velocity limit of the panels.
        vmax: Upper velocity limit.
        linelist: rbcodes line list used to resolve ``lam1``/``lam2``.
        method: ``closest`` or ``Exact`` matching.

    Returns:
        A two-panel Plotly figure (flux and error versus velocity for each line).
    """
    wave_rest = rest_wavelength(spec)
    t1 = lookup(lam1, method, linelist)
    t2 = lookup(lam2, method, linelist)
    error = spec.error
    traces: list[dict[str, Any]] = []
    for row, tr in enumerate((t1, t2), start=1):
        vel = velocity_of(wave_rest, tr.wrest)
        keep = (vel >= vmin - 50) & (vel <= vmax + 50)
        axis = "" if row == 1 else "2"
        traces.append(
            {
                "type": "scatter",
                "mode": "lines",
                "line": {"shape": "hv", "width": 1, "color": "#5B8DEF"},
                "name": tr.name,
                "x": vel[keep].tolist(),
                "y": np.asarray(spec.flux)[keep].tolist(),
                "xaxis": f"x{axis}",
                "yaxis": f"y{axis}",
            }
        )
        if error is not None:
            traces.append(
                {
                    "type": "scatter",
                    "mode": "lines",
                    "line": {"shape": "hv", "width": 1, "color": "#D64545"},
                    "name": f"{tr.name} error",
                    "x": vel[keep].tolist(),
                    "y": np.asarray(error)[keep].tolist(),
                    "xaxis": f"x{axis}",
                    "yaxis": f"y{axis}",
                    "showlegend": False,
                }
            )
    layout: dict[str, Any] = {
        "grid": {"rows": 2, "columns": 1, "pattern": "independent"},
        "xaxis": {"range": [vmin, vmax], "title": {"text": f"{t1.name} velocity (km/s)"}},
        "xaxis2": {"range": [vmin, vmax], "title": {"text": f"{t2.name} velocity (km/s)"}},
        "yaxis": {"range": [-0.02, 1.8], "title": {"text": "normalised flux"}},
        "yaxis2": {"range": [-0.02, 1.8], "title": {"text": "normalised flux"}},
        "shapes": [
            {
                "type": "line",
                "xref": f"x{a}",
                "yref": f"y{a}",
                "x0": vmin,
                "x1": vmax,
                "y0": y,
                "y1": y,
                "line": {"dash": "dot", "width": 1, "color": "#6B7280"},
            }
            for a in ("", "2")
            for y in (0.0, 1.0)
        ],
        "title": {"text": f"Doublet check: {t1.name} / {t2.name} (ratio {t1.fval / t2.fval:.2f})"}
        if t2.fval
        else {"text": f"Doublet check: {t1.name} / {t2.name}"},
    }
    return Figure(kind="plotly", plotly={"data": traces, "layout": layout})


def slice_bounds(spec: Spectrum1D) -> tuple[float, float]:
    """Velocity range of a slice (helper for editors and tests)."""
    meta = rb_meta(spec)
    if "slice_spec_lam_min" in meta and meta.get("slice_spec_method", True):
        return float(meta["slice_spec_lam_min"]), float(meta["slice_spec_lam_max"])
    return float(np.min(spec.wave)), float(np.max(spec.wave))


__all__ = [
    "C_KMS",
    "compute_ew",
    "doublet_check",
    "set_redshift",
    "set_transition",
    "slice_bounds",
    "slice_spectrum",
]
