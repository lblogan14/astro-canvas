"""Astro Canvas node pack for rbcodes: absorption-line measurements (phase 05), more to come.

Importing this package must never import ``rbcodes`` (some of its modules select a Qt matplotlib
backend at import time). Node modules import rbcodes lazily inside the node functions, after
``MPLBACKEND`` has been pinned to a headless backend below, and fall back to the vendored kernels
in ``astro_canvas_rbcodes.kernels`` when rbcodes is not installed.
"""

from __future__ import annotations

import os
from pathlib import Path

from astro_canvas.sdk import PackRegistry

__version__ = "0.1.0a0"

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _bundled(name: str) -> Path | None:
    """A folder shipped next to the package (wheel) or at the pack root (repo checkout)."""
    here = Path(__file__).resolve().parent
    for candidate in (here / name, here.parents[1] / name):
        if candidate.is_dir():
            return candidate
    return None


def sample_data_dir() -> Path | None:
    """Folder of bundled sample spectra/images/cubes (``sample_data`` in the wheel or the repo)."""
    return _bundled("sample_data")


def templates_dir() -> Path | None:
    """Folder of bundled workflow templates (``templates`` in the wheel or the repo)."""
    return _bundled("templates")


def register(registry: PackRegistry) -> None:
    """Entry point (``astro_canvas.nodes`` -> ``rbcodes``): nodes, sample data and templates."""
    from astro_canvas_rbcodes.nodes import absorption, continuum, io, lines  # noqa: PLC0415

    registry.declare_security("standard")
    for module in (lines, absorption, continuum, io):
        registry.add_module(module)
    samples = sample_data_dir()
    if samples is not None:
        registry.add_sample_data(samples)
    templates = templates_dir()
    if templates is not None:
        registry.add_templates(templates)


__all__ = ["__version__", "register", "sample_data_dir", "templates_dir"]
