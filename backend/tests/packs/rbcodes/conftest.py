"""Fixtures for the rbcodes pack tests: sample data, a workspace, a context and the reference JSON.

Reference values come from running rbcodes itself (``fixtures/generate_reference.py`` in a
Python 3.10 environment where ``rbcodes`` installs); tests compare the nodes against them and,
when rbcodes is importable in the test environment, the vendored kernels against rbcodes directly.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from astro_canvas_core.io.image import read_cube
from astro_canvas_core.nodes.io import load_spectrum
from astro_canvas_core.types import Cube3D, Spectrum1D
from astro_canvas_rbcodes import _rb, sample_data_dir

from astro_canvas.sdk import NullContext

SAMPLES = sample_data_dir()
assert SAMPLES is not None, "packs/rbcodes/sample_data is missing"
FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = FIXTURES / "reference_ew.json"

requires_rbcodes = pytest.mark.skipif(
    not _rb.rbcodes_available(), reason="rbcodes is not installed in this environment"
)


@pytest.fixture(scope="session")
def samples() -> Path:
    return SAMPLES


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A workspace folder with the sample data copied under ``samples/rbcodes``."""
    root = tmp_path / "ws"
    shutil.copytree(SAMPLES, root / "samples" / "rbcodes")
    return root


@pytest.fixture
def ctx(workspace: Path) -> NullContext:
    return NullContext(workspace=workspace)


@pytest.fixture(scope="session")
def reference() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(REFERENCE.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="session")
def sdss1() -> Spectrum1D:
    """The z = 3.01 SDSS quasar with the z = 1.3855 MgII absorber, loaded once per session."""
    return load_spectrum(path="sdss1.fits", ctx=NullContext(workspace=SAMPLES))


@pytest.fixture(scope="session")
def ifu_cube() -> Cube3D:
    """The bundled synthetic IFU cube (``sample_data/make_cube.py``): a rotating disc plus clump."""
    return read_cube(SAMPLES / "synthetic_ifu_icubes.fits")


@pytest.fixture(scope="session")
def samples_galaxy() -> Spectrum1D:
    """The z = 0.00586 SDSS star-forming galaxy, loaded once per session."""
    return load_spectrum(path="spec-0398-51789-0282.fits", ctx=NullContext(workspace=SAMPLES))
