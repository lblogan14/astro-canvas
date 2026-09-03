"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from astro_canvas.server.app import create_app
from astro_canvas.settings import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return Settings(workspace=workspace, port=8765)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
