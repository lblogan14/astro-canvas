"""Generate ``reference_zfind.json`` by running rbcodes' ``rb_zfind`` engine on the sample spectra.

Run in an environment where ``rbcodes`` is installed (Python 3.10 until the upstream pin is
relaxed), from ``backend/``::

    MPLBACKEND=Agg .venv310/Scripts/python tests/packs/rbcodes/fixtures/generate_reference_zfind.py

The spectra are loaded with Astro Canvas' own reader (so both sides see identical float64 arrays)
and handed to rbcodes as ``rb_spectrum`` objects with a *flat median continuum*: the BIC
polynomial fit rbcodes would otherwise run (``fit_optimal_polynomial``, astropy's LevMar fitter
with sigma clipping) converges slightly differently across astropy releases, which flips the
sign check on a few grid points, whereas a constant continuum is identical everywhere.
``test_zfind_nodes.py`` feeds the nodes the same continuum (``continuum="spectrum"``) and compares
curves and solutions; ``continuum="fit"`` (the default) is covered by the recovery tests.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

HERE = Path(__file__).resolve().parent
SAMPLES = HERE.parents[4] / "packs" / "rbcodes" / "sample_data"
GALAXY = "spec-0398-51789-0282.fits"
QSO = "sdss1.fits"

CASES: list[dict[str, Any]] = [
    {
        "id": "galaxy_picket_fence",
        "file": GALAXY,
        "method": "picket_fence",
        "linelist": "zfind_galaxy",
        "kwargs": {
            "z_min": 0.0,
            "z_max": 0.5,
            "n_steps": 3000,
            "smooth_fwhm_pix": 2.0,
            "fwhm_ang": 3.0,
        },
    },
    {
        "id": "galaxy_line_search",
        "file": GALAXY,
        "method": "line_search",
        "linelist": "zfind_galaxy",
        "kwargs": {"z_min": 0.0, "z_max": 0.5, "n_steps": 3000, "mode": "emission"},
    },
    {
        "id": "galaxy_template",
        "file": GALAXY,
        "method": "template",
        "kwargs": {
            "template_name": "LateTypeEmission",
            "z_min": 0.0,
            "z_max": 0.5,
            "n_steps": 1000,
        },
    },
    {
        "id": "galaxy_pca",
        "file": GALAXY,
        "method": "pca",
        "kwargs": {"template_set": "galaxy", "z_min": 0.0, "z_max": 0.5, "n_steps": 500},
    },
    {
        "id": "qso_picket_fence",
        "file": QSO,
        "method": "picket_fence",
        "linelist": "zfind_qso",
        "kwargs": {
            "z_min": 0.0,
            "z_max": 5.0,
            "n_steps": 5000,
            "smooth_fwhm_pix": 3.0,
            "fwhm_ang": 20.0,
        },
    },
    {
        "id": "qso_absorbers",
        "file": QSO,
        "method": "line_search",
        "linelist": "zfind_igm",
        "kwargs": {"z_min": 0.5, "z_max": 2.5, "n_steps": 4000, "mode": "absorption"},
    },
]

PROBE = [0, 1, 7, 100, 999]
"""Curve indices recorded verbatim (plus the minimum), so the whole curve is spot-checked."""


def _spectrum(name: str) -> Any:
    import astropy.units as u
    import numpy as np
    from astro_canvas_core.nodes.io import load_spectrum
    from rbcodes.utils.rb_spectrum import rb_spectrum

    from astro_canvas.sdk import NullContext

    # Astro Canvas' own parser (float64 ``10**loglam``); rbcodes' reader keeps float32 grids.
    spec = load_spectrum(path=name, use_rbcodes=False, ctx=NullContext(workspace=SAMPLES))
    unit = u.dimensionless_unscaled
    continuum = np.full(len(spec), float(np.nanmedian(spec.flux)))
    return rb_spectrum(
        spec.wave * u.AA,
        spec.flux * unit,
        error=spec.error * unit if spec.error is not None else None,
        continuum=continuum * unit,
        meta={"airvac": "vac"},
    )


def _curve_stats(z: Any, values: Any) -> dict[str, Any]:
    import numpy as np

    finite = np.isfinite(values)
    idx = int(np.nanargmin(values)) if finite.any() else None
    probe = [i for i in PROBE if i < len(values)]
    return {
        "n": int(len(values)),
        "n_finite": int(finite.sum()),
        "argmin_z": float(z[idx]) if idx is not None else None,
        "min": float(values[idx]) if idx is not None else None,
        "probe_index": probe,
        "probe": [None if not np.isfinite(values[i]) else float(values[i]) for i in probe],
    }


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    from rbcodes.GUIs.zfind import engine
    from rbcodes.GUIs.zfind.linelists import get_curated_df

    spec = _spectrum(case["file"])
    kwargs = dict(case["kwargs"])
    method = case["method"]
    if method == "picket_fence":
        result = engine.picket_fence_search(spec, get_curated_df(case["linelist"]), **kwargs)
    elif method == "line_search":
        result = engine.line_search(spec, get_curated_df(case["linelist"]), **kwargs)
    elif method == "template":
        result = engine.template_search(spec, **kwargs)
    else:
        result = engine.pca_search(spec, **kwargs)

    out: dict[str, Any] = {"warnings": list(result.warnings)}
    if hasattr(result, "candidates"):
        out["curve"] = _curve_stats(result.z_array, result.significance_curve)
        out["candidates"] = [
            {
                "z": float(c.z),
                "significance": float(c.significance),
                "n_lines": int(c.n_lines),
                "linelist_name": str(c.linelist_name),
                "lines_matched": [str(v) for v in c.lines_matched],
            }
            for c in result.candidates[:5]
        ]
    else:
        out["curve"] = _curve_stats(result.z_array, result.chi2_curves[0]["chi2"])
        out["label"] = str(result.chi2_curves[0]["label"])
        out["solutions"] = [
            {
                "z": float(s.z),
                "z_err": None if s.z_err != s.z_err else float(s.z_err),
                "chi2_dof": float(s.chi2_dof),
                "method": str(s.method),
                "template_type": str(s.template_type),
                "n_features": int(s.n_features),
            }
            for s in result.solutions[:5]
        ]
    return out


def main() -> int:
    import importlib.metadata

    import astropy
    import numpy
    import scipy

    version = importlib.metadata.version("rbcodes")
    results = {case["id"]: {"case": case, "expected": run_case(case)} for case in CASES}
    document = {
        "rbcodes_version": version,
        "python": sys.version.split()[0],
        "numpy": numpy.__version__,
        "astropy": astropy.__version__,
        "scipy": scipy.__version__,
        "generated_by": "tests/packs/rbcodes/fixtures/generate_reference_zfind.py",
        "cases": results,
    }
    target = HERE / "reference_zfind.json"
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {target} ({len(CASES)} cases, rbcodes {version})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
