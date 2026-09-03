"""Port types of the rbcodes pack (``rbcodes.*``): zfind results and the multispec view.

``ZFindResult``/``AbsorberResult``/``ZSolution`` mirror the dataclasses in
``rbcodes.GUIs.zfind.io``; the searched spectrum travels inside the result (``input_spec``) so
the ``z-accept`` editor can overlay lines on it without another request. ``ZCandidates`` is the
ranked candidate table produced by ``rbcodes.zfind.rank``, ``MultispecView`` is what
``rbcodes.multispec.view`` draws (the stacked panels plus the absorber and identified-line
catalogues) and ``MomentMaps`` is what ``rbcodes.ifu.moment_maps`` produces. Summaries are
JSON-safe (non-finite numbers become ``null``) and decimate the curves to the viewport's
``n_out``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
from astro_canvas_core.types import Spectrum1D
from pydantic import BaseModel, ConfigDict, model_validator

from astro_canvas.sdk import Float1D, Float32_2D, PortType, decimate_indices, port_type

Statistic = Literal["chi2", "score", "significance"]
"""What the curve measures: reduced chi-square (templates, PCA), the negative SNR-like score of
the line and picket-fence searches (minima = best z), or the absorber significance (maxima)."""


def _viewport_int(viewport: Mapping[str, Any] | None, key: str, default: int, cap: int) -> int:
    try:
        value = int((viewport or {}).get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, cap))


def json_floats(values: npt.ArrayLike) -> list[float | None]:
    """A float array as a JSON list with ``null`` for NaN/inf (``json.dumps`` emits ``NaN``)."""
    out: list[float | None] = []
    for v in np.asarray(values, dtype=np.float64).tolist():
        out.append(float(v) if math.isfinite(v) else None)
    return out


def json_float(value: float | None) -> float | None:
    return None if value is None or not math.isfinite(value) else float(value)


def _pick(
    z: npt.NDArray[np.float64], y: npt.NDArray[np.float64], n_out: int
) -> npt.NDArray[np.intp]:
    """Decimation indices over ``(z, y)``; an all-NaN curve falls back to an even stride."""
    if z.shape[0] <= n_out:
        return np.arange(z.shape[0], dtype=np.intp)
    if not np.any(np.isfinite(y)):
        return np.unique(np.linspace(0, z.shape[0] - 1, n_out).astype(np.intp))
    return decimate_indices(z, y, n_out=n_out)


@port_type(id="rbcodes.ZSolution", color="#EAB308", summary_renderer="chip")
class ZSolution(PortType):
    """One redshift solution: ``z``, curvature error, statistic value, method and feature count."""

    z: float
    z_err: float | None = None
    chi2_dof: float
    method: str
    template_type: str = "Unknown"
    n_features: int = 0

    def summary(self, viewport: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return {"type": self.type_id(), "data": self.row()}

    def row(self) -> dict[str, Any]:
        return {
            "z": json_float(self.z),
            "z_err": json_float(self.z_err),
            "chi2_dof": json_float(self.chi2_dof),
            "method": self.method,
            "template_type": self.template_type,
            "n_features": int(self.n_features),
        }


class ZCurve(BaseModel):
    """One labelled curve on the result's redshift grid."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    label: str
    values: Float1D


@port_type(id="rbcodes.ZFindResult", color="#F59E0B", summary_renderer="zfind-curve")
class ZFindResult(PortType):
    """A redshift scan: z grid, one or more curves, ranked solutions and the searched spectrum."""

    z_array: Float1D
    curves: list[ZCurve]
    solutions: list[ZSolution] = []
    input_spec: Spectrum1D | None = None
    warnings: list[str] = []
    statistic: Statistic = "chi2"
    linelist: str | None = None
    meta: dict[str, Any] = {}

    @model_validator(mode="after")
    def _curves_match_grid(self) -> ZFindResult:
        n = self.z_array.shape[0]
        for curve in self.curves:
            if curve.values.shape[0] != n:
                raise ValueError(
                    f"curve {curve.label!r} has {curve.values.shape[0]} points, z has {n}"
                )
        return self

    def best(self) -> ZSolution | None:
        return self.solutions[0] if self.solutions else None

    def summary(self, viewport: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Decimated ``z``/``curves`` (``n_out``, default 2000), the solutions and the spectrum.

        Every curve is sampled at the indices chosen for the first one so overlays stay aligned.
        ``spectrum`` is the input spectrum's own summary at the same point budget.
        """
        n_out = _viewport_int(viewport, "n_out", 2000, 20000)
        first = self.curves[0].values if self.curves else np.zeros_like(self.z_array)
        pick = _pick(self.z_array, first, n_out)
        return {
            "type": self.type_id(),
            "statistic": self.statistic,
            "n": int(self.z_array.shape[0]),
            "z_range": [float(self.z_array[0]), float(self.z_array[-1])]
            if self.z_array.size
            else None,
            "z": json_floats(self.z_array[pick]),
            "curves": [
                {"label": c.label, "values": json_floats(c.values[pick])} for c in self.curves
            ],
            "solutions": [s.row() for s in self.solutions],
            "spectrum": self.input_spec.summary({"n_out": n_out}) if self.input_spec else None,
            "warnings": list(self.warnings),
            "linelist": self.linelist,
        }


class AbsorberCandidate(BaseModel):
    """One absorber candidate (``io.AbsorberCandidate``)."""

    model_config = ConfigDict(extra="forbid")

    z: float
    significance: float
    n_lines: int
    is_doublet: bool = False
    linelist_name: str = "custom"
    lines_matched: list[str] = []

    def row(self) -> dict[str, Any]:
        return {
            "z": json_float(self.z),
            "significance": json_float(self.significance),
            "n_lines": int(self.n_lines),
            "is_doublet": bool(self.is_doublet),
            "linelist_name": self.linelist_name,
            "lines_matched": list(self.lines_matched),
        }


@port_type(id="rbcodes.AbsorberResult", color="#D97706", summary_renderer="zfind-curve")
class AbsorberResult(PortType):
    """An absorber scan: significance versus z and ranked candidates (many per sightline)."""

    z_array: Float1D
    significance_curve: Float1D
    candidates: list[AbsorberCandidate] = []
    input_spec: Spectrum1D | None = None
    warnings: list[str] = []
    linelist: str | None = None
    meta: dict[str, Any] = {}

    @model_validator(mode="after")
    def _curve_matches_grid(self) -> AbsorberResult:
        if self.significance_curve.shape[0] != self.z_array.shape[0]:
            raise ValueError("significance_curve must have the same length as z_array")
        return self

    def summary(self, viewport: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Like ``ZFindResult.summary`` (``statistic = "significance"``) plus ``candidates``."""
        n_out = _viewport_int(viewport, "n_out", 2000, 20000)
        pick = _pick(self.z_array, self.significance_curve, n_out)
        label = self.linelist or "absorbers"
        return {
            "type": self.type_id(),
            "statistic": "significance",
            "n": int(self.z_array.shape[0]),
            "z_range": [float(self.z_array[0]), float(self.z_array[-1])]
            if self.z_array.size
            else None,
            "z": json_floats(self.z_array[pick]),
            "curves": [{"label": label, "values": json_floats(self.significance_curve[pick])}],
            "candidates": [c.row() for c in self.candidates],
            "spectrum": self.input_spec.summary({"n_out": n_out}) if self.input_spec else None,
            "warnings": list(self.warnings),
            "linelist": self.linelist,
        }


class ZCandidateRow(BaseModel):
    """One row of the ranked candidate table (``index`` is what ``rank.accepted`` refers to)."""

    model_config = ConfigDict(extra="forbid")

    index: int
    source: int
    rank: int
    z: float
    z_err: float | None = None
    score: float
    method: str
    template_type: str = "Unknown"
    n_features: int = 0

    def row(self) -> dict[str, Any]:
        return {
            "index": int(self.index),
            "source": int(self.source),
            "rank": int(self.rank),
            "z": json_float(self.z),
            "z_err": json_float(self.z_err),
            "score": json_float(self.score),
            "method": self.method,
            "template_type": self.template_type,
            "n_features": int(self.n_features),
        }


@port_type(id="rbcodes.ZCandidates", color="#CA8A04", summary_renderer="candidates-table")
class ZCandidates(PortType):
    """The ranked redshift candidates of one or more scans, with the accepted index."""

    rows: list[ZCandidateRow] = []
    accepted: int | None = None
    statistics: list[Statistic] = []

    def __len__(self) -> int:
        return len(self.rows)

    def summary(self, viewport: Mapping[str, Any] | None = None) -> dict[str, Any]:
        return {
            "type": self.type_id(),
            "n": len(self.rows),
            "accepted": self.accepted,
            "statistics": list(self.statistics),
            "rows": [r.row() for r in self.rows],
        }


class AbsorberSystem(BaseModel):
    """One row of rb_multispec's absorber manager (``Zabs``/``LineList``/``Color``/``Visible``)."""

    model_config = ConfigDict(extra="forbid")

    zabs: float
    linelist: str = "LLS"
    color: str = "sky_blue"
    visible: bool = True
    label: str = ""

    def row(self) -> dict[str, Any]:
        return {
            "zabs": json_float(self.zabs),
            "linelist": self.linelist,
            "color": self.color,
            "visible": bool(self.visible),
            "label": self.label,
        }


class IdentifiedLine(BaseModel):
    """One identified transition (rb_multispec's ``Name``/``Wave_obs``/``Zabs`` line list)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    wave_obs: float
    zabs: float
    wave_rest: float | None = None
    spectrum: str = ""

    def rest(self) -> float:
        if self.wave_rest is not None:
            return float(self.wave_rest)
        return float(self.wave_obs) / (1.0 + float(self.zabs))

    def row(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "wave_obs": json_float(self.wave_obs),
            "zabs": json_float(self.zabs),
            "wave_rest": json_float(self.rest()),
            "spectrum": self.spectrum,
        }


@port_type(id="rbcodes.MultispecView", color="#0EA5E9", summary_renderer="multispec-thumb")
class MultispecView(PortType):
    """What the multi-spectrum viewer shows: the stacked spectra, absorbers and identified lines.

    The ``view`` output of ``rbcodes.multispec.view``: the panels as they are displayed (after
    smoothing and the wavelength window), the absorber systems whose lines are overlaid and the
    identified-line catalogue. Its summary drives the ``multispec-thumb`` inline preview.
    """

    spectra: list[Spectrum1D] = []
    labels: list[str] = []
    absorbers: list[AbsorberSystem] = []
    identified: list[IdentifiedLine] = []
    z: float = 0.0
    linelist: str = "LLS"
    meta: dict[str, Any] = {}

    @model_validator(mode="after")
    def _labels_match(self) -> MultispecView:
        if self.labels and len(self.labels) != len(self.spectra):
            raise ValueError("labels must match spectra")
        return self

    def __len__(self) -> int:
        return len(self.spectra)

    def wave_range(self) -> tuple[float, float] | None:
        lo = min((float(s.wave[0]) for s in self.spectra if len(s)), default=None)
        hi = max((float(s.wave[-1]) for s in self.spectra if len(s)), default=None)
        return None if lo is None or hi is None else (lo, hi)

    def summary(self, viewport: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Panels decimated to ``n_out`` (default 400, at most ``max_panels`` of them).

        Every panel is a ``Spectrum1D`` summary, so the thumbnail and the editor share the
        decimation. ``absorbers``/``identified`` are the whole (small) catalogues.
        """
        n_out = _viewport_int(viewport, "n_out", 400, 20000)
        max_panels = _viewport_int(viewport, "max_panels", 8, 64)
        window = self.wave_range()
        return {
            "type": self.type_id(),
            "count": len(self.spectra),
            "labels": list(self.labels),
            "range": [window[0], window[1]] if window else None,
            "z": json_float(self.z),
            "linelist": self.linelist,
            "panels": [s.summary({"n_out": n_out}) for s in self.spectra[:max_panels]],
            "absorbers": [a.row() for a in self.absorbers],
            "identified": [line.row() for line in self.identified],
        }


@port_type(id="rbcodes.MomentMaps", color="#F472B6", summary_renderer="moment-thumbs")
class MomentMaps(PortType):
    """The moment maps of one emission line: integrated flux, velocity, dispersion and SNR.

    ``m0`` is the integrated flux over ``window``; ``m1`` and ``m2`` are the flux-weighted velocity
    centroid and dispersion in km/s relative to ``lambda_rest`` (both NaN where ``m0 <= 0``), and
    ``snr`` is the per-spaxel signal-to-noise of ``m0``. Spatial ``wcs`` is the cube's celestial
    part, so the maps overlay the same apertures the spectra were extracted from.
    """

    m0: Float32_2D
    m1: Float32_2D | None = None
    m2: Float32_2D | None = None
    snr: Float32_2D | None = None
    wcs: dict[str, Any] | None = None
    unit: str | None = None
    lambda_rest: float | None = None
    window: tuple[float, float] | None = None
    meta: dict[str, Any] = {}

    @model_validator(mode="after")
    def _same_shape(self) -> MomentMaps:
        for name in ("m1", "m2", "snr"):
            array = getattr(self, name)
            if array is not None and array.shape != self.m0.shape:
                raise ValueError(f"{name} must have the same shape as m0")
        return self

    @property
    def shape(self) -> tuple[int, int]:
        return int(self.m0.shape[0]), int(self.m0.shape[1])

    def maps(self) -> list[tuple[str, npt.NDArray[np.float32], str]]:
        """The present maps as ``(key, data, unit)``, in display order."""
        out: list[tuple[str, npt.NDArray[np.float32], str]] = [("m0", self.m0, self.unit or "")]
        if self.m1 is not None:
            out.append(("m1", self.m1, "km/s"))
        if self.m2 is not None:
            out.append(("m2", self.m2, "km/s"))
        if self.snr is not None:
            out.append(("snr", self.snr, ""))
        return out

    def summary(self, viewport: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """One tile per map (edge <= ``n_out``, default 96) sharing the preview's colour map."""
        from astro_canvas_core.types import image_tile  # noqa: PLC0415 - avoids an import cycle

        size = _viewport_int(viewport, "n_out", 96, 512)
        return {
            "type": self.type_id(),
            "shape": list(self.shape),
            "unit": self.unit,
            "lambda_rest": json_float(self.lambda_rest),
            "window": [json_float(self.window[0]), json_float(self.window[1])]
            if self.window
            else None,
            "wcs": self.wcs,
            "maps": [
                {"key": key, "unit": unit, "tile": image_tile(data, size)}
                for key, data, unit in self.maps()
            ],
        }


__all__ = [
    "AbsorberCandidate",
    "AbsorberResult",
    "AbsorberSystem",
    "IdentifiedLine",
    "MomentMaps",
    "MultispecView",
    "Statistic",
    "ZCandidateRow",
    "ZCandidates",
    "ZCurve",
    "ZFindResult",
    "ZSolution",
    "json_float",
    "json_floats",
]
