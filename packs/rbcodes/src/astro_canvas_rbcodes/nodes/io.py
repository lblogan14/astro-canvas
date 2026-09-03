"""``save_rbspec_json`` / ``load_rbspec_json``: the ``rb_spec.save_slice`` JSON file as nodes."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Annotated, Any

import numpy as np
from astro_canvas_core.io.paths import describe_file, file_fingerprint, resolve_in_workspace
from astro_canvas_core.types import Continuum, EWMeasurement, File, Spectrum1D, Transition

from astro_canvas.sdk import NodeContext, Param, node
from astro_canvas_rbcodes import _rb
from astro_canvas_rbcodes.nodes._common import RB_META, rb_meta, rest_wavelength
from astro_canvas_rbcodes.nodes.lines import LineListParam

FIELD_DESCRIPTIONS: dict[str, str] = {
    "zabs": "Absorber redshift",
    "linelist": "Line list used for atomic data",
    "line_sel_flag": "Line selection method",
    "trans": "Name of the transition",
    "fval": "Oscillator strength of the transition",
    "trans_wave": "Rest frame wavelength of transition (Angstroms)",
    "vmin": "Minimum velocity for equivalent width calculation (km/s)",
    "vmax": "Maximum velocity for equivalent width calculation (km/s)",
    "W": "Rest frame equivalent width (Angstroms)",
    "W_e": "Uncertainty in rest frame equivalent width (Angstroms)",
    "N": "Apparent optical depth column density (cm^-2)",
    "N_e": "Uncertainty in column density (cm^-2)",
    "logN": "Log10 of the column density (cm^-2)",
    "logN_e": "Uncertainty in log column density",
    "vel_centroid": "Velocity centroid of absorption line (km/s)",
    "vel_disp": "1-sigma velocity dispersion (km/s)",
    "vel50_err": "Error on velocity centroid (km/s)",
    "SNR": "Signal-to-noise ratio",
    "wave_slice": "Wavelength array for the slice (Angstroms)",
    "flux_slice": "Flux array for the slice",
    "error_slice": "Error array for the slice",
    "velo": "Velocity array (km/s)",
    "cont": "Fitted continuum array",
    "fnorm": "Normalized flux array",
    "enorm": "Normalized error array",
    "Tau": "Apparent optical depth as a function of velocity",
    "continuum_masks": "Velocity ranges excluded from continuum fitting (km/s)",
    "continuum_mask_wavelengths": "Wavelength ranges excluded from continuum fitting (Angstroms)",
    "continuum_fit_params": "Parameters used for continuum fitting",
}


def _workspace(ctx: NodeContext | None) -> Path:
    return Path(ctx.workspace) if ctx is not None else Path.cwd()


def rbspec_document(
    normalized: Spectrum1D,
    continuum: Continuum,
    measurement: EWMeasurement,
    *,
    linelist: str,
) -> dict[str, Any]:
    """The ``rb_spec.save_slice`` JSON document (all keys, arrays as lists)."""
    meta = rb_meta(normalized)
    transition: Transition | None = measurement.transition
    wave_slice = rest_wavelength(normalized)
    velo = np.asarray(normalized.wave, dtype=np.float64)
    if normalized.frame != "velocity":
        if transition is None:
            raise ValueError(
                "a rest-frame spectrum needs the measured transition to derive velocities"
            )
        velo = (wave_slice - transition.wrest) * 2.9979e5 / transition.wrest
    cont = np.asarray(continuum.cont, dtype=np.float64)
    if cont.shape != wave_slice.shape:
        raise ValueError("continuum and spectrum have different lengths")
    fnorm = np.asarray(normalized.flux, dtype=np.float64)
    enorm = (
        np.asarray(normalized.error, dtype=np.float64)
        if normalized.error is not None
        else np.full_like(fnorm, np.nan)
    )
    # rb_spec divides the whole spectrum by its median flux at load time; mirror that scale so
    # flux_slice/error_slice/cont match what launch_specgui would have produced.
    scale = float(meta.get("flux_scale", 1.0)) or 1.0
    flux_slice = fnorm * cont / scale
    error_slice = enorm * cont / scale
    with np.errstate(all="ignore"):
        tau = -np.log(np.clip(fnorm, np.finfo(float).eps, None))
    masks = list(meta.get("continuum_masks") or [])
    if not masks and continuum.masks:
        for lo, hi in continuum.masks:
            masks.extend([float(lo), float(hi)])
    mask_waves: list[float] = []
    for i in range(0, len(masks) - 1, 2):
        lo_i = int(np.abs(velo - masks[i]).argmin())
        hi_i = int(np.abs(velo - masks[i + 1]).argmin())
        mask_waves.extend([float(wave_slice[lo_i]), float(wave_slice[hi_i])])
    fit_params = dict(meta.get("continuum_fit_params") or {})
    fit_params.setdefault("method", continuum.method or "polynomial")
    fit_params.setdefault("legendre_order", continuum.order)
    fit_params.setdefault("timestamp", datetime.datetime.now().isoformat())
    zabs = normalized.z if normalized.z is not None else float(meta.get("zabs", 0.0))
    doc: dict[str, Any] = {
        "zabs": float(zabs),
        "linelist": linelist,
        "line_sel_flag": "closest",
        "trans": transition.name if transition else meta.get("transition_name", ""),
        "fval": float(transition.fval) if transition else 0.0,
        "trans_wave": float(transition.wrest) if transition else float(normalized.v0_wrest or 0.0),
        "vmin": measurement.vmin,
        "vmax": measurement.vmax,
        "W": measurement.W,
        "W_e": measurement.W_e,
        "N": measurement.N,
        "N_e": measurement.N_e,
        "logN": measurement.logN,
        "logN_e": measurement.logN_e,
        "vel_centroid": measurement.vel_centroid,
        "vel_disp": measurement.vel_disp,
        "vel50_err": measurement.vel50_err,
        "SNR": measurement.SNR if measurement.SNR is not None else -99,
        "wave_slice": wave_slice.tolist(),
        "flux_slice": flux_slice.tolist(),
        "error_slice": error_slice.tolist(),
        "velo": velo.tolist(),
        "cont": (cont / scale).tolist(),
        "fnorm": fnorm.tolist(),
        "enorm": enorm.tolist(),
        "Tau": tau.tolist(),
        "slice_spec_lam_min": meta.get("slice_spec_lam_min", float(np.min(velo))),
        "slice_spec_lam_max": meta.get("slice_spec_lam_max", float(np.max(velo))),
        "slice_spec_method": meta.get("slice_spec_method", True),
        "continuum_masks": masks,
        "continuum_mask_wavelengths": mask_waves,
        "continuum_fit_params": fit_params,
        "metadata": {
            "field_descriptions": FIELD_DESCRIPTIONS,
            "timestamp": datetime.datetime.now().isoformat(),
            "rbcodes_version": _rb.rbcodes_version() or _rb.VENDORED_VERSION,
            "astro_canvas": _rb.provenance(),
        },
    }
    return doc


@node(
    id="rbcodes.absorption.save_rbspec_json",
    name="Save rb_spec JSON",
    category="rbcodes/Absorption",
    icon="save",
)
def save_rbspec_json(
    normalized: Spectrum1D,
    continuum: Continuum,
    measurement: EWMeasurement,
    path: Annotated[str, Param(label="Output path")] = "outputs/absorption.json",
    linelist: LineListParam = "atom",
    ctx: NodeContext | None = None,
) -> File:
    """Write the measurement as an ``rb_spec.save_slice`` JSON file.

    The file has exactly the keys rbcodes writes (slice arrays, continuum, masks, fit parameters,
    ``W``, ``N``, ``logN``...) so ``launch_specgui analysis.json`` and
    ``rb_spec.load_rb_spec_object`` open it. Flux and continuum are scaled by the median flux of
    the full spectrum, as ``rb_spec`` does at load time.

    Args:
        normalized: The normalised slice (``Fit Continuum`` -> ``normalized``).
        continuum: The fitted continuum on the same grid.
        measurement: The equivalent-width result.
        path: Workspace-relative output path.
        linelist: Line list name recorded in the file.

    Returns:
        The written file.
    """
    root = _workspace(ctx)
    target = resolve_in_workspace(root, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc = rbspec_document(normalized, continuum, measurement, linelist=linelist)
    target.write_text(json.dumps(doc, indent=4, default=_json_default), encoding="utf-8")
    return describe_file(root, target)


def _json_default(value: Any) -> Any:
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _as_float(values: Any) -> np.ndarray:
    return np.asarray(values, dtype=np.float64)


@node(
    id="rbcodes.absorption.load_rbspec_json",
    name="Load rb_spec JSON",
    category="rbcodes/Absorption",
    icon="file-json",
    fingerprint=file_fingerprint,
    outputs=("spec", "normalized", "continuum", "measurement"),
)
def load_rbspec_json(
    path: Annotated[str, Param(widget="file", label="File")] = "",
    ctx: NodeContext | None = None,
) -> tuple[Spectrum1D, Spectrum1D, Continuum, EWMeasurement]:
    """Read an ``rb_spec`` JSON analysis back into its slice, continuum and measurement.

    Args:
        path: Workspace-relative path of a file written by ``Save rb_spec JSON`` or rbcodes.

    Returns:
        The raw slice (velocity axis, continuum attached), the normalised slice, the continuum
        and the equivalent-width measurement stored in the file.
    """
    if not path:
        raise ValueError("choose a file to load")
    target = resolve_in_workspace(_workspace(ctx), path)
    data = json.loads(target.read_text(encoding="utf-8"))
    if "wave_slice" not in data or "fnorm" not in data:
        raise ValueError("not an rb_spec JSON file (wave_slice/fnorm missing)")
    velo = _as_float(data["velo"])
    cont = _as_float(data["cont"])
    trans_wave = float(data.get("trans_wave", 0.0))
    zabs = float(data.get("zabs", 0.0))
    transition = Transition(
        name=str(data.get("trans", "")), wrest=trans_wave, fval=float(data.get("fval", 0.0))
    )
    masks_flat = [float(v) for v in data.get("continuum_masks", [])]
    masks = [(masks_flat[i], masks_flat[i + 1]) for i in range(0, len(masks_flat) - 1, 2)]
    fit_params = dict(data.get("continuum_fit_params") or {})
    base_meta: dict[str, Any] = {
        "source": target.name,
        "format": "rbspec_json",
        "airvac": "vac",
        RB_META: {
            "zabs": zabs,
            "transition": trans_wave,
            "transition_name": transition.name,
            "linelist": data.get("linelist"),
            "slice_spec_lam_min": data.get("slice_spec_lam_min"),
            "slice_spec_lam_max": data.get("slice_spec_lam_max"),
            "slice_spec_method": data.get("slice_spec_method", True),
            "continuum_masks": masks_flat,
            "continuum_fit_params": fit_params,
            "flux_scale": 1.0,
        },
        "rbcodes": _rb.provenance(
            file_rbcodes_version=(data.get("metadata") or {}).get("rbcodes_version")
        ),
    }
    spec = Spectrum1D(
        wave=velo,
        flux=_as_float(data["flux_slice"]),
        error=_as_float(data["error_slice"]) if "error_slice" in data else None,
        continuum=cont,
        wave_unit="km / s",
        flux_unit="rb_spec (median-normalised)",
        frame="velocity",
        z=zabs,
        v0_wrest=trans_wave,
        meta=base_meta,
    )
    normalized = spec.model_copy(
        update={
            "flux": _as_float(data["fnorm"]),
            "error": _as_float(data["enorm"]) if "enorm" in data else None,
            "continuum": np.ones_like(cont),
            "flux_unit": "normalized",
        }
    )
    continuum = Continuum(
        cont=cont,
        masks=masks,
        method=str(fit_params.get("method", "polynomial")),
        order=fit_params.get("legendre_order"),
        params={k: v for k, v in fit_params.items() if k not in ("method", "legendre_order")},
    )
    snr_value = data.get("SNR", -99)
    measurement = EWMeasurement(
        W=float(data["W"]),
        W_e=float(data["W_e"]),
        N=float(data.get("N", 0.0)),
        N_e=float(data.get("N_e", 0.0)),
        logN=float(data.get("logN", 0.0)),
        logN_e=float(data.get("logN_e", 0.0)),
        vel_centroid=float(data["vel_centroid"]) if data.get("vel_centroid") is not None else None,
        vel_disp=float(data["vel_disp"]) if data.get("vel_disp") is not None else None,
        vel50_err=float(data["vel50_err"]) if data.get("vel50_err") is not None else None,
        SNR=None if snr_value in (None, -99) else float(snr_value),
        vmin=float(data["vmin"]) if data.get("vmin") is not None else None,
        vmax=float(data["vmax"]) if data.get("vmax") is not None else None,
        transition=transition,
    )
    return spec, normalized, continuum, measurement


__all__ = ["FIELD_DESCRIPTIONS", "load_rbspec_json", "rbspec_document", "save_rbspec_json"]
