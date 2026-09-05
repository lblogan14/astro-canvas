"""``astro-canvas pack …`` against the scripted ``uv`` from ``tests/manager``.

These drive the whole command -- argument parsing, the real ``PackManager``, a real subprocess --
and only the ``uv`` binary itself is a stand-in, so the plan-then-confirm contract is what is
actually being tested.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from astro_canvas import cli
from tests.manager.conftest import FakeEnvironment

runner = CliRunner()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeEnvironment:
    """A scripted uv the CLI finds through ``ASTRO_CANVAS_UV_PATH``."""
    root = tmp_path / "uvenv"
    root.mkdir()
    fake = FakeEnvironment(root)
    monkeypatch.setenv("ASTRO_CANVAS_UV_PATH", str(fake.shim))
    monkeypatch.setenv("FAKE_UV_STATE", str(fake.state_path))
    monkeypatch.setenv("ASTRO_CANVAS_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("ASTRO_CANVAS_WORKSPACE", str(tmp_path / "ws"))
    return fake


def test_pack_list_shows_the_installed_packs(env: FakeEnvironment) -> None:
    result = runner.invoke(cli.app, ["pack", "list"])
    assert result.exit_code == 0, result.output
    assert "core" in result.output and "nodes" in result.output


def test_install_prints_the_plan_and_asks_first(env: FakeEnvironment) -> None:
    result = runner.invoke(cli.app, ["pack", "install", "astro-canvas-demo"], input="n\n")
    assert result.exit_code == 1
    assert "plan for astro-canvas-demo" in result.output
    assert "add       astro-canvas-demo" in result.output
    assert "cancelled" in result.output
    assert "astro-canvas-demo" not in env.installed()


def test_dry_run_never_touches_the_environment(env: FakeEnvironment) -> None:
    result = runner.invoke(cli.app, ["pack", "install", "astro-canvas-demo", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "add       astro-canvas-demo" in result.output
    assert "astro-canvas-demo" not in env.installed()


def test_install_with_yes_installs(env: FakeEnvironment) -> None:
    result = runner.invoke(cli.app, ["pack", "install", "astro-canvas-demo", "--yes"])
    assert result.exit_code == 0, result.output
    assert env.installed()["astro-canvas-demo"] == "0.2.0"


def test_a_conflicting_pin_blocks_the_install(env: FakeEnvironment) -> None:
    """The same gate the dialog has: a plan that is not ``ok`` cannot be confirmed (design 9)."""
    result = runner.invoke(cli.app, ["pack", "install", "astro-canvas-bad", "--yes"])
    assert result.exit_code == 1
    assert "conflicts:" in result.output
    assert "unsatisfiable" in result.output
    assert "astro-canvas-bad" not in env.installed()


def test_an_unknown_pack_is_a_clean_error(env: FakeEnvironment) -> None:
    result = runner.invoke(cli.app, ["pack", "install", "not-a-real-pack", "--yes"])
    assert result.exit_code == 1
    assert "not available" in result.output or "conflicts" in result.output


def test_snapshot_then_rollback_restores_the_environment(env: FakeEnvironment) -> None:
    taken = runner.invoke(cli.app, ["pack", "snapshot", "--label", "before demo"])
    assert taken.exit_code == 0, taken.output
    assert "snapshot 1 recorded" in taken.output

    listed = runner.invoke(cli.app, ["pack", "snapshot", "--list"])
    assert "before demo" in listed.output

    before = env.installed()
    installed = runner.invoke(cli.app, ["pack", "install", "astro-canvas-demo", "--yes"])
    assert installed.exit_code == 0, installed.output
    assert env.installed() != before

    rolled = runner.invoke(cli.app, ["pack", "rollback", "1", "--yes"])
    assert rolled.exit_code == 0, rolled.output
    assert "restored" in rolled.output
    assert env.installed() == before


def test_rollback_refuses_an_unknown_snapshot(env: FakeEnvironment) -> None:
    result = runner.invoke(cli.app, ["pack", "rollback", "42", "--yes"])
    assert result.exit_code == 1 and "unknown snapshot 42" in result.output


def test_remove_shows_the_plan_and_can_be_declined(env: FakeEnvironment) -> None:
    runner.invoke(cli.app, ["pack", "install", "astro-canvas-demo", "--yes"])
    result = runner.invoke(cli.app, ["pack", "remove", "astro-canvas-demo"], input="n\n")
    assert result.exit_code == 1 and "cancelled" in result.output
    assert "astro-canvas-demo" in env.installed()
