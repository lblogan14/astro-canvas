"""``astro-canvas doctor``: the report a support email can be answered from."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from astro_canvas import cli
from astro_canvas.cli import doctor as doctor_mod

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ASTRO_CANVAS_CONFIG_DIR", str(tmp_path / "cfg"))


def test_doctor_reports_green_on_this_installation(tmp_path: Path) -> None:
    result = runner.invoke(cli.app, ["doctor", "--workspace", str(tmp_path / "ws")])
    assert result.exit_code == 0, result.output
    assert "all checks passed" in result.output
    assert "[ok  ] python" in result.output
    assert "[ok  ] qt not imported" in result.output
    assert "pack core" in result.output and "pack rbcodes" in result.output


def test_doctor_reports_the_workspace_it_checked(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    result = runner.invoke(cli.app, ["doctor", "--workspace", str(workspace)])
    assert str(workspace) in result.output
    assert (workspace / ".astro-canvas" / "app.db").is_file()


def test_doctor_notices_a_busy_port(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        monkeypatch.setenv("ASTRO_CANVAS_PORT", str(held.getsockname()[1]))
        result = runner.invoke(cli.app, ["doctor", "--workspace", str(tmp_path / "ws")])
    assert result.exit_code == 0, result.output
    assert "[warn] port" in result.output and "may already be running" in result.output


def test_doctor_fails_when_uv_cannot_be_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ASTRO_CANVAS_UV_PATH", str(tmp_path / "nowhere" / "uv"))
    result = runner.invoke(cli.app, ["doctor", "--workspace", str(tmp_path / "ws")])
    assert result.exit_code == 1
    assert "[FAIL] uv" in result.output
    assert "check(s) failed" in result.output


def test_qt_check_fails_when_a_binding_was_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pack importing Qt at module level would break every headless run (design 8.5)."""
    monkeypatch.setitem(sys.modules, "PyQt5", object())
    check = doctor_mod.qt_check()
    assert check.status == "fail" and "PyQt5" in check.detail


def test_port_free_is_false_while_a_socket_holds_it() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        port = int(held.getsockname()[1])
        assert doctor_mod.port_free("127.0.0.1", port) is False
    assert doctor_mod.port_free("127.0.0.1", port) is True


def test_disk_check_walks_up_to_an_existing_parent(tmp_path: Path) -> None:
    check = doctor_mod.disk_check(tmp_path / "not" / "created" / "yet")
    assert check.status in ("ok", "warn") and "free of" in check.detail
