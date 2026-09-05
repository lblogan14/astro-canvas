"""``--host 0.0.0.0`` must not serve without user accounts (design 11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from astro_canvas.sdk import DiscoveryResult
from astro_canvas.server.app import create_app
from astro_canvas.server.guard import ExposureError, check_exposure, exposure_problem
from astro_canvas.settings import Settings


def config(tmp_path: Path, **overrides: object) -> Settings:
    return Settings(workspace=tmp_path / "ws", config_dir=tmp_path / "cfg", **overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_is_always_allowed(tmp_path: Path, host: str) -> None:
    for mode in ("none", "token", "users"):
        assert exposure_problem(config(tmp_path, host=host, auth=mode)) is None


def test_a_public_bind_with_a_token_is_refused(tmp_path: Path) -> None:
    problem = exposure_problem(config(tmp_path, host="0.0.0.0", auth="token"))
    assert problem is not None
    assert "--auth users" in problem and "0.0.0.0:8765" in problem
    assert "--i-know-what-i-am-doing" in problem


def test_a_public_bind_with_no_auth_says_so_plainly(tmp_path: Path) -> None:
    problem = exposure_problem(config(tmp_path, host="0.0.0.0", auth="none"))
    assert problem is not None and "--auth none" in problem


def test_a_public_bind_with_accounts_is_allowed(tmp_path: Path) -> None:
    assert exposure_problem(config(tmp_path, host="0.0.0.0", auth="users")) is None


def test_the_override_allows_it(tmp_path: Path) -> None:
    settings = config(tmp_path, host="0.0.0.0", auth="token", allow_public_bind=True)
    assert exposure_problem(settings) is None
    check_exposure(settings)


def test_the_override_can_come_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Docker image is configured with env vars, not with flags."""
    monkeypatch.setenv("ASTRO_CANVAS_ALLOW_PUBLIC_BIND", "1")
    monkeypatch.setenv("ASTRO_CANVAS_HOST", "0.0.0.0")
    monkeypatch.setenv("ASTRO_CANVAS_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("ASTRO_CANVAS_CONFIG_DIR", str(tmp_path / "cfg"))
    assert exposure_problem(Settings()) is None


def test_create_app_refuses_rather_than_serving(
    tmp_path: Path, test_discovery: DiscoveryResult
) -> None:
    """The guard lives in ``create_app``, so ``uvicorn --factory`` is covered too."""
    with pytest.raises(ExposureError, match="--auth users"):
        create_app(config(tmp_path, host="0.0.0.0", auth="token"), test_discovery)


def test_create_app_serves_a_public_bind_with_the_override(
    tmp_path: Path, test_discovery: DiscoveryResult
) -> None:
    settings = config(tmp_path, host="0.0.0.0", auth="none", allow_public_bind=True)
    app = create_app(settings, test_discovery)
    assert app.state.token is None
