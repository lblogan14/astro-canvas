"""Fixtures for the core pack tests: the bundled sample data and a workspace-backed context."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from astro_canvas_rbcodes import sample_data_dir

from astro_canvas.sdk import NullContext

SAMPLES = sample_data_dir()
assert SAMPLES is not None, "packs/rbcodes/sample_data is missing"


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
