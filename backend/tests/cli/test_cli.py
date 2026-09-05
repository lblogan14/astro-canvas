"""CLI surface: ``version``, ``serve`` option plumbing and ``open``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from astro_canvas import cli
from astro_canvas._version import __version__
from astro_canvas.cli import serve as serve_mod
from astro_canvas.settings import Settings

runner = CliRunner()


def test_version_prints_version() -> None:
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_no_args_shows_help() -> None:
    result = runner.invoke(cli.app, [])
    for command in ("serve", "open", "run", "doctor", "workspace", "pack", "bundle", "version"):
        assert command in result.output


def test_serve_passes_options_to_uvicorn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(serve_mod.uvicorn, "run", lambda app, **kw: calls.append(kw))
    monkeypatch.setenv("ASTRO_CANVAS_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("ASTRO_CANVAS_CONFIG_DIR", str(tmp_path / "cfg"))

    result = runner.invoke(
        cli.app,
        [
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "9100",
            "--workspace",
            str(tmp_path),
            "--auth",
            "none",
            "--i-know-what-i-am-doing",
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == [
        {
            "host": "0.0.0.0",
            "port": 9100,
            "log_level": "warning",
            "proxy_headers": True,
            "forwarded_allow_ips": "127.0.0.1",
        }
    ]


def test_serve_refuses_a_public_bind_without_accounts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        serve_mod.uvicorn, "run", lambda *_a, **_k: pytest.fail("must not start uvicorn")
    )
    monkeypatch.setenv("ASTRO_CANVAS_CONFIG_DIR", str(tmp_path / "cfg"))
    result = runner.invoke(
        cli.app, ["serve", "--host", "0.0.0.0", "--workspace", str(tmp_path / "ws")]
    )
    assert result.exit_code == 2
    assert "--auth users" in result.output


def test_serve_open_spawns_browser_thread(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    started: list[tuple[Any, ...]] = []

    class FakeThread:
        def __init__(self, *, target: Any, args: tuple[Any, ...], daemon: bool) -> None:
            started.append((target, args, daemon))

        def start(self) -> None:
            pass

    monkeypatch.setattr(serve_mod.threading, "Thread", FakeThread)
    monkeypatch.setattr(serve_mod.uvicorn, "run", lambda app, **kw: None)
    settings = Settings(port=8123, auth="none", workspace=tmp_path / "ws", config_dir=tmp_path)

    serve_mod.run_server(settings, open_browser=True)
    assert started == [(serve_mod.open_when_ready, ("http://127.0.0.1:8123",), True)]

    started.clear()
    serve_mod.run_server(settings, open_browser=False)
    assert started == []


def test_open_when_ready_opens_after_health_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = iter([httpx.ConnectError("down"), httpx.Response(503), httpx.Response(200)])

    def fake_get(url: str, timeout: float) -> httpx.Response:
        assert url == "http://127.0.0.1:8765/api/health"
        outcome = next(attempts)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    opened: list[str] = []
    monkeypatch.setattr(serve_mod.httpx, "get", fake_get)
    monkeypatch.setattr(serve_mod.webbrowser, "open", opened.append)
    monkeypatch.setattr(serve_mod.time, "sleep", lambda _s: None)

    assert serve_mod.open_when_ready("http://127.0.0.1:8765", timeout=5) is True
    assert opened == ["http://127.0.0.1:8765"]


def test_open_when_ready_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(serve_mod.httpx, "get", lambda *_a, **_k: httpx.Response(500))
    monkeypatch.setattr(
        serve_mod.webbrowser, "open", lambda _u: pytest.fail("must not open a browser")
    )
    clock = iter([0.0, 0.1, 10.0, 10.0])
    monkeypatch.setattr(serve_mod.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(serve_mod.time, "sleep", lambda _s: None)
    assert serve_mod.open_when_ready("http://127.0.0.1:8765", timeout=5) is False


def test_open_reuses_a_running_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The desktop shortcut must not start a second server on a port that already answers."""
    config = tmp_path / "cfg"
    config.mkdir()
    (config / "token").write_text("saved-token", encoding="utf-8")
    monkeypatch.setenv("ASTRO_CANVAS_CONFIG_DIR", str(config))
    monkeypatch.setattr(
        serve_mod.httpx,
        "get",
        lambda *_a, **_k: httpx.Response(200, json={"status": "ok", "version": "9.9.9"}),
    )
    opened: list[str] = []
    monkeypatch.setattr(serve_mod.webbrowser, "open", opened.append)
    monkeypatch.setattr(
        serve_mod.uvicorn, "run", lambda *_a, **_k: pytest.fail("must not start a second server")
    )

    result = runner.invoke(cli.app, ["open", "--port", "8123", "--workspace", str(tmp_path / "ws")])
    assert result.exit_code == 0, result.output
    assert "9.9.9 is already running" in result.output
    assert opened == ["http://127.0.0.1:8123/?token=saved-token"]


def test_open_starts_a_server_when_none_is_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ASTRO_CANVAS_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(
        serve_mod.httpx, "get", lambda *_a, **_k: (_ for _ in ()).throw(httpx.ConnectError("down"))
    )
    started: list[dict[str, Any]] = []
    monkeypatch.setattr(serve_mod.uvicorn, "run", lambda app, **kw: started.append(kw))
    monkeypatch.setattr(serve_mod.threading, "Thread", _NoThread)

    result = runner.invoke(cli.app, ["open", "--port", "8124", "--workspace", str(tmp_path / "ws")])
    assert result.exit_code == 0, result.output
    assert started and started[0]["port"] == 8124


class _NoThread:
    """A ``threading.Thread`` stand-in that never runs its target."""

    def __init__(self, **_kwargs: Any) -> None:
        pass

    def start(self) -> None:
        pass
