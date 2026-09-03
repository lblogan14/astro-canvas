"""Contract tests for ``/api/health``, ``/api/system`` and the SPA mount."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from astro_canvas._version import __version__
from astro_canvas.server.app import create_app
from astro_canvas.server.static import STATIC_DIR, mount_static
from astro_canvas.settings import Settings


def test_health_reports_ok_and_version(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_system_reports_environment(client: TestClient, settings: Settings) -> None:
    body = client.get("/api/system").json()
    assert body["version"] == __version__
    assert body["workspace"] == str(settings.workspace)
    assert body["workspace_exists"] is True
    assert body["disk_total_bytes"] >= body["disk_free_bytes"] > 0
    assert [p["name"] for p in body["packs"]] == ["core", "rbcodes"]
    assert body["packs"][0]["node_count"] == 7 and body["packs"][0]["error"] is None
    assert body["python"].count(".") == 2


def test_system_creates_missing_workspace(tmp_path: Path) -> None:
    missing = tmp_path / "does" / "not" / "exist"
    settings = Settings(workspace=missing, auth=False, config_dir=tmp_path / "cfg")
    body = TestClient(create_app(settings)).get("/api/system").json()
    assert body["workspace_exists"] is True  # the engine runtime creates it at startup
    assert (missing / ".astro-canvas" / "app.db").is_file()
    assert body["disk_total_bytes"] > 0


def test_openapi_lives_under_api(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 200
    assert client.get("/api/docs").status_code == 200


def test_no_static_build_means_no_root_route(client: TestClient) -> None:
    if STATIC_DIR.joinpath("index.html").is_file():
        pytest.skip("a built SPA is present in astro_canvas/static (run `task clean`)")
    assert client.get("/").status_code == 404


def _make_build(root: Path) -> Path:
    static = root / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>Astro Canvas</title>")
    (static / "assets" / "app.js").write_text("console.log(1)")
    (static / "favicon.svg").write_text("<svg/>")
    return static


def test_static_mount_serves_spa_with_history_fallback(tmp_path: Path) -> None:
    app = FastAPI()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    assert mount_static(app, _make_build(tmp_path)) is True
    client = TestClient(app)

    assert "Astro Canvas" in client.get("/").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert client.get("/favicon.svg").text == "<svg/>"
    # Unknown client-side routes fall back to index.html ...
    assert "Astro Canvas" in client.get("/workflows/abc").text
    # ... but API and websocket paths do not.
    assert client.get("/api/nope").status_code == 404
    assert client.get("/ws").status_code == 404
    assert client.get("/api/health").status_code == 200
    # Path traversal never escapes the static dir.
    assert "Astro Canvas" in client.get("/../pyproject.toml").text


def test_static_mount_skipped_without_index(tmp_path: Path) -> None:
    assert mount_static(FastAPI(), tmp_path) is False
