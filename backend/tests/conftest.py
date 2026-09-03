"""Shared fixtures."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from astro_canvas.sdk import DiscoveryResult, NodeRegistry, discover
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


@pytest.fixture(scope="session")
def registry() -> NodeRegistry:
    """Core packs plus the engine test nodes (``tests/engine/nodes.py``)."""
    from tests.engine.nodes import build_registry

    return build_registry()


@pytest.fixture(scope="session")
def test_discovery(registry: NodeRegistry) -> DiscoveryResult:
    """A ``DiscoveryResult`` exposing the test nodes to ``create_app``."""
    return DiscoveryResult(registry=registry, packs=[])


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return Settings(
        workspace=workspace,
        port=8765,
        config_dir=tmp_path / "config",
        token="test-token",
        process_pool=False,
        debounce_ms=20,
    )


def authed_client(app: Any) -> TestClient:
    """A ``TestClient`` sending the app's bearer token on every request."""
    token = getattr(app.state, "token", None)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return TestClient(app, headers=headers)


@pytest.fixture
def client(settings: Settings, discovery: DiscoveryResult) -> Iterator[TestClient]:
    with authed_client(create_app(settings, discovery)) as client:
        yield client
