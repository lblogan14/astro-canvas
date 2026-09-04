"""``astro-canvas workspace list|use|new``: choosing the folder the app opens."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from astro_canvas import cli
from astro_canvas.settings import Settings, get_settings
from astro_canvas.store.recent import RecentWorkspaces

runner = CliRunner()


@pytest.fixture(autouse=True)
def config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    directory = tmp_path / "cfg"
    monkeypatch.setenv("ASTRO_CANVAS_CONFIG_DIR", str(directory))
    monkeypatch.delenv("ASTRO_CANVAS_WORKSPACE", raising=False)
    return directory


def test_new_creates_the_database_and_selects_it(tmp_path: Path, config: Path) -> None:
    target = tmp_path / "papers" / "lya"
    result = runner.invoke(cli.app, ["workspace", "new", str(target)])
    assert result.exit_code == 0, result.output
    assert "created" in result.output
    assert (target / ".astro-canvas" / "app.db").is_file()
    assert RecentWorkspaces(config).selected() == target.resolve()


def test_new_can_leave_the_default_alone(tmp_path: Path, config: Path) -> None:
    result = runner.invoke(cli.app, ["workspace", "new", str(tmp_path / "side"), "--no-use"])
    assert result.exit_code == 0, result.output
    assert RecentWorkspaces(config).selected() is None


def test_use_becomes_the_default_workspace(tmp_path: Path, config: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    result = runner.invoke(cli.app, ["workspace", "use", str(target)])
    assert result.exit_code == 0, result.output
    assert get_settings().workspace == target.resolve()
    assert Settings().workspace == target.resolve()


def test_use_refuses_a_missing_folder_unless_asked_to_create_it(tmp_path: Path) -> None:
    missing = tmp_path / "not-there"
    result = runner.invoke(cli.app, ["workspace", "use", str(missing)])
    assert result.exit_code == 1
    assert "--create" in result.output

    created = runner.invoke(cli.app, ["workspace", "use", str(missing), "--create"])
    assert created.exit_code == 0, created.output
    assert missing.is_dir()


def test_use_refuses_a_file(tmp_path: Path) -> None:
    target = tmp_path / "a-file.txt"
    target.write_text("not a folder", encoding="utf-8")
    result = runner.invoke(cli.app, ["workspace", "use", str(target)])
    assert result.exit_code == 1 and "not a folder" in result.output


def test_list_marks_the_current_workspace(tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    runner.invoke(cli.app, ["workspace", "new", str(first)])
    runner.invoke(cli.app, ["workspace", "new", str(second)])
    result = runner.invoke(cli.app, ["workspace", "list"])
    assert result.exit_code == 0, result.output
    lines = {line[2:].strip(): line[0] for line in result.output.splitlines() if line.strip()}
    assert lines[str(second.resolve())] == "*"
    assert lines[str(first.resolve())] == " "


def test_list_flags_a_workspace_that_was_deleted(tmp_path: Path, config: Path) -> None:
    gone = tmp_path / "gone"
    runner.invoke(cli.app, ["workspace", "new", str(gone)])
    runner.invoke(cli.app, ["workspace", "new", str(tmp_path / "here")])
    for child in sorted(gone.rglob("*"), reverse=True):
        child.unlink() if child.is_file() else child.rmdir()
    gone.rmdir()
    result = runner.invoke(cli.app, ["workspace", "list"])
    assert "(missing)" in result.output
