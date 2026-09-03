"""Astro Canvas node pack for rbcodes (nodes arrive in phases 05-08).

Importing this package must never import ``rbcodes`` (some of its modules select a Qt matplotlib
backend at import time). Node modules import rbcodes lazily inside the node functions, after
``MPLBACKEND`` has been pinned to a headless backend below.
"""

from __future__ import annotations

import os
from pathlib import Path

from astro_canvas.sdk import PackRegistry

__version__ = "0.1.0a0"

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def sample_data_dir() -> Path | None:
    """Folder of bundled sample spectra/images/cubes (``sample_data`` in the wheel or the repo)."""
    here = Path(__file__).resolve().parent
    for candidate in (here / "sample_data", here.parents[1] / "sample_data"):
        if candidate.is_dir():
            return candidate
    return None


def register(registry: PackRegistry) -> None:
    """Entry point (``astro_canvas.nodes`` -> ``rbcodes``): sample data now, nodes in phases 05+."""
    registry.declare_security("standard")
    samples = sample_data_dir()
    if samples is not None:
        registry.add_sample_data(samples)


__all__ = ["__version__", "register", "sample_data_dir"]
