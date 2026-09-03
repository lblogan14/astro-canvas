"""Port types of the rbcodes pack (``rbcodes.*``): the ``rb_zfind`` result objects.

``ZFindResult``/``AbsorberResult``/``ZSolution`` mirror the dataclasses in
``rbcodes.GUIs.zfind.io``; the searched spectrum travels inside the result (``input_spec``) so
the ``z-accept`` editor can overlay lines on it without another request. ``ZCandidates`` is the
ranked candidate table produced by ``rbcodes.zfind.rank``. Summaries are JSON-safe (non-finite
numbers become ``null``) and decimate the curves to the viewport's ``n_out``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
from astro_canvas_core.types import Spectrum1D
from pydantic import BaseModel, ConfigDict, model_validator

from astro_canvas.sdk import Float1D, PortType, decimate_indices, port_type

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


__all__ = [
    "AbsorberCandidate",
    "AbsorberResult",
    "Statistic",
    "ZCandidateRow",
    "ZCandidates",
    "ZCurve",
    "ZFindResult",
    "ZSolution",
    "json_float",
    "json_floats",
]
