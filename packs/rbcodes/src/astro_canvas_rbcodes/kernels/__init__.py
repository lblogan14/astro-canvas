"""Vendored numerical kernels from rbcodes 2.4.0 (commit ``4499012``), MIT licensed.

Line-by-line ports of ``rbcodes.IGM.compute_EW``, ``rbcodes.IGM.rb_setline``,
``rbcodes.IGM.rb_iter_contfit``, ``rbcodes.IGM.fit_continuum_full_spec``,
``rbcodes.IGM.rb_specbin``, ``rbcodes.utils.compute_SNR_1d`` and (phase 06) the ``rb_zfind``
engine (``GUIs.zfind.engine``, ``picket_fence``, ``linelists``, ``adapters``) without their
plotting, printing and file I/O. The nodes prefer the installed ``rbcodes`` when it is importable
and use these kernels otherwise; ``tests/packs/rbcodes/test_kernels_match_rbcodes.py`` asserts
both agree.
"""

from __future__ import annotations

from astro_canvas_rbcodes.kernels.contfit import (
    calculate_bic,
    calculate_confidence_bounds,
    fit_optimal_polynomial,
    rb_iter_contfit,
)
from astro_canvas_rbcodes.kernels.ew import compute_ew
from astro_canvas_rbcodes.kernels.fullspec import fit_quasar_continuum
from astro_canvas_rbcodes.kernels.picket_fence import PicketFenceZ
from astro_canvas_rbcodes.kernels.setline import LINE_LISTS, rb_setline, read_line_list
from astro_canvas_rbcodes.kernels.snr import estimate_snr, rb_specbin
from astro_canvas_rbcodes.kernels.zfind_linelists import CURATED_NAMES, LineTable, curated

__all__ = [
    "CURATED_NAMES",
    "LINE_LISTS",
    "LineTable",
    "PicketFenceZ",
    "calculate_bic",
    "calculate_confidence_bounds",
    "compute_ew",
    "curated",
    "estimate_snr",
    "fit_optimal_polynomial",
    "fit_quasar_continuum",
    "rb_iter_contfit",
    "rb_setline",
    "rb_specbin",
    "read_line_list",
]
