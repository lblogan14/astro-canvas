"""Shared fixtures."""

from __future__ import annotations

import sys
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from astro_canvas.sdk import DiscoveryResult, discover
from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def fixture_packs_on_path() -> None:
    """Make ``tests/fixtures/pack_*`` importable as top-level packages."""
    if str(FIXTURES) not in sys.path:
        sys.path.insert(0, str(FIXTURES))


def fixture_entry_point(name: str) -> EntryPoint:
    """An ``astro_canvas.nodes`` entry point for ``tests/fixtures/pack_<name>``."""
    return EntryPoint(name=name, value=f"pack_{name}:register", group="astro_canvas.nodes")


@pytest.fixture(scope="session")
def discovery() -> DiscoveryResult:
    """Real installed packs (core, rbcodes) discovered once per session."""
    return discover()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return Settings(workspace=workspace, port=8765)


@pytest.fixture
def client(settings: Settings, discovery: DiscoveryResult) -> TestClient:
    return TestClient(create_app(settings, discovery))
