"""Generate ``reference_ew.json`` by running rbcodes itself on the bundled sample data.

Run in an environment where ``rbcodes`` is installed (Python 3.10 until the upstream pin is
relaxed), from ``backend/``::

    UV_PROJECT_ENVIRONMENT=.venv310 uv sync --python 3.10 --all-extras --frozen
    MPLBACKEND=Agg .venv310/Scripts/python tests/packs/rbcodes/fixtures/generate_reference.py

Each case follows the canonical ``rb_spec`` pipeline (``from_file -> shift_spec -> slice_spec ->
fit_continuum(mask, Legendre, optimize_cont) -> compute_EW``) with fixed masks so the numbers are
deterministic. The nodes are compared against these values in ``test_absorption_pipeline.py``.
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

CASES: list[dict[str, Any]] = [
    {
        "id": "sdss1_mgii2796",
        "file": "sdss1.fits",
        "zabs": 1.3855,
        "wrest": 2796.35,
        "linelist": "atom",
        "slice": [-1500.0, 1500.0],
        "masks": [-300.0, 250.0, 500.0, 1000.0],
        "order": 3,
        "optimize": True,
        "ew": [-200.0, 200.0],
    },
    {
        "id": "sdss1_mgii2803",
        "file": "sdss1.fits",
        "zabs": 1.3855,
        "wrest": 2803.53,
        "linelist": "atom",
        "slice": [-1500.0, 1500.0],
        "masks": [-1100.0, -500.0, -300.0, 250.0],
        "order": 3,
        "optimize": True,
        "ew": [-200.0, 200.0],
    },
    {
        "id": "sdss1_feii2600_fixed_order",
        "file": "sdss1.fits",
        "zabs": 1.3855,
        "wrest": 2600.17,
        "linelist": "atom",
        "slice": [-1200.0, 1200.0],
        "masks": [-250.0, 250.0],
        "order": 2,
        "optimize": False,
        "ew": [-150.0, 150.0],
    },
    {
        "id": "sdss1_mgii2796_weighted",
        "file": "sdss1.fits",
        "zabs": 1.3855,
        "wrest": 2796.35,
        "linelist": "atom",
        "slice": [-1500.0, 1500.0],
        "masks": [-300.0, 250.0, 500.0, 1000.0],
        "order": 3,
        "optimize": True,
        "use_weights": True,
        "ew": [-200.0, 200.0],
        "snr": True,
    },
]


def run_case(case: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    from rbcodes.GUIs.rb_spec import rb_spec

    spec = rb_spec.from_file(str(SAMPLES / case["file"]))
    spec.shift_spec(case["zabs"])
    spec.slice_spec(
        case["wrest"], *case["slice"], method="closest", linelist=case["linelist"], use_vel=True
    )
    spec.fit_continuum(
        mask=list(case["masks"]),
        Legendre=case["order"],
        optimize_cont=case["optimize"],
        use_weights=case.get("use_weights", False),
        verbose=False,
    )
    spec.compute_EW(
        case["wrest"], vmin=case["ew"][0], vmax=case["ew"][1], SNR=case.get("snr", False)
    )
    out = {
        "transition": {
            "name": str(spec.trans),
            "wrest": float(spec.trans_wave),
            "fval": float(spec.fval),
        },
        "n_slice": int(len(spec.velo)),
        "velo_first": float(spec.velo[0]),
        "velo_last": float(spec.velo[-1]),
        "legendre_order": spec.continuum_fit_params.get("legendre_order"),
        "cont_median": float(np.median(spec.cont)),
        "cont_first": float(spec.cont[0]),
        "cont_last": float(spec.cont[-1]),
        "fnorm_median": float(np.median(spec.fnorm)),
        "W": float(spec.W),
        "W_e": float(spec.W_e),
        "N": float(spec.N),
        "N_e": float(spec.N_e),
        "logN": float(spec.logN),
        "logN_e": float(spec.logN_e),
        "vel_centroid": float(spec.vel_centroid),
        "vel_disp": float(spec.vel_disp),
        "vel50_err": float(spec.vel50_err),
        "SNR": float(spec.SNR) if case.get("snr") else None,
    }
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
        "generated_by": "tests/packs/rbcodes/fixtures/generate_reference.py",
        "cases": results,
    }
    target = HERE / "reference_ew.json"
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {target} ({len(CASES)} cases, rbcodes {version})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
