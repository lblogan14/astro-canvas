"""rbcodes-first dispatch for the multi-spectrum viewer helpers.

``multispecviewer.LineFitter`` and ``multispecviewer.utils.reconcile_linelists`` are Qt-free (the
``IOManager`` they use is a plain pandas singleton, not a widget), so the nodes call them straight
from the installed rbcodes and fall back to the vendored ports otherwise. Either way the result is
a ``kernels.line_fit.LineFit`` / lists of plain dictionaries, so the node code is
backend-agnostic and ``_rb.provenance()`` records which side produced the numbers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from astro_canvas_rbcodes import _rb
from astro_canvas_rbcodes.kernels import line_fit as F
from astro_canvas_rbcodes.kernels import multispec_io as M


def fit_line(
    wave: npt.ArrayLike,
    flux: npt.ArrayLike,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    kind: F.FitKind,
) -> F.LineFit:
    """``LineFitter.fit_gaussian`` / ``fit_com`` from rbcodes when installed, else the port."""
    module = _rb.import_rbcodes("GUIs.multispecviewer.LineFitter")
    if module is not None:
        raw = (module.fit_gaussian if kind == "gaussian" else module.fit_com)(
            np.asarray(wave, dtype=np.float64), np.asarray(flux, dtype=np.float64), x1, y1, x2, y2
        )
        return _from_upstream(raw, kind, x1, y1, x2, y2, wave)
    if kind == "gaussian":
        return F.fit_gaussian(wave, flux, x1, y1, x2, y2)
    return F.fit_com(wave, flux, x1, y1, x2, y2)


def _from_upstream(
    raw: Mapping[str, Any],
    kind: F.FitKind,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    wave: npt.ArrayLike,
) -> F.LineFit:
    """rbcodes' result dictionary as the kernel dataclass (it omits the fields it never sets)."""
    left, low, right, high = F.order_anchors(x1, y1, x2, y2)
    w = np.asarray(wave, dtype=np.float64)
    n_pixels = int(np.count_nonzero((w >= left) & (w <= right)))
    sigma_ang = float(raw.get("sigma_ang", raw.get("fwhm_ang", 0.0) / F.FWHM_PER_SIGMA))
    centroid = float(raw["centroid"])
    fwhm_ang = float(raw.get("fwhm_ang", raw.get("fwhm_equiv_ang", 0.0)))
    return F.LineFit(
        kind=kind,
        centroid=centroid,
        fwhm_ang=fwhm_ang,
        fwhm_kms=float(raw.get("fwhm_kms", 0.0)),
        amplitude=float(raw["amplitude"]),
        direction=int(raw["direction"]),
        asymmetric=bool(raw["asymmetric"]),
        sigma_ang=sigma_ang,
        sigma_kms=float(
            raw.get("sigma_kms", sigma_ang / centroid * F.C_KMS if centroid > 0 else 0.0)
        ),
        n_pixels=n_pixels,
        window=(left, right),
        continuum=(low, high),
        fit_wave=np.asarray(raw.get("fit_wave", np.empty(0)), dtype=np.float64),
        fit_flux=np.asarray(raw.get("fit_flux", np.empty(0)), dtype=np.float64),
    )


def reconcile(
    paths: Sequence[Path], velocity_threshold: float
) -> tuple[list[M.LineRow], list[M.AbsorberRow], dict[str, Any]]:
    """``utils.reconcile_linelists`` from rbcodes when installed, else the vendored port."""
    module = _rb.import_rbcodes("GUIs.multispecviewer.utils")
    if module is not None:
        lines_df, absorbers_df = module.reconcile_linelists(
            [str(p) for p in paths],
            velocity_threshold=velocity_threshold,
            output_file=None,
            create_absorber_df=True,
        )
        lines = _records(lines_df)
        absorbers = _records(absorbers_df)
        info = {
            "velocity_threshold": velocity_threshold,
            "input_files": [p.name for p in paths if p.exists()],
            "original_line_count": len(lines),
            "reconciled_line_count": len(lines),
        }
        return lines, absorbers, info
    return M.reconcile_linelists(paths, velocity_threshold)


def _records(frame: Any) -> list[dict[str, Any]]:
    """A pandas DataFrame (or ``None``) as a list of plain dictionaries."""
    if frame is None or getattr(frame, "empty", True):
        return []
    records: list[dict[str, Any]] = frame.to_dict(orient="records")
    return [{k: _plain(v) for k, v in row.items()} for row in records]


def _plain(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    return value


__all__ = ["fit_line", "reconcile"]
