"""CLI surface: ``version`` and ``serve`` option plumbing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from astro_canvas import __version__, cli
from astro_canvas.settings import Settings

runner = CliRunner()


def test_version_prints_version() -> None:
    result = runner.invoke(cli.app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_no_args_shows_help() -> None:
    result = runner.invoke(cli.app, [])
    assert "serve" in result.output
    assert "version" in result.output


def test_serve_passes_options_to_uvicorn(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: calls.append(kw))
    monkeypatch.setenv("ASTRO_CANVAS_LOG_LEVEL", "WARNING")

    result = runner.invoke(
        cli.app,
        ["serve", "--host", "0.0.0.0", "--port", "9100", "--workspace", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert calls == [{"host": "0.0.0.0", "port": 9100, "log_level": "warning"}]


def test_serve_open_spawns_browser_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    started: list[tuple[Any, ...]] = []

    class FakeThread:
        def __init__(self, *, target: Any, args: tuple[Any, ...], daemon: bool) -> None:
            started.append((target, args, daemon))

        def start(self) -> None:
            pass

    monkeypatch.setattr(cli.threading, "Thread", FakeThread)
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kw: None)

    cli.run_server(Settings(port=8123), open_browser=True)
    assert started == [(cli.open_when_ready, ("http://127.0.0.1:8123",), True)]

    started.clear()
    cli.run_server(Settings(port=8123), open_browser=False)
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
    monkeypatch.setattr(cli.httpx, "get", fake_get)
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)

    assert cli.open_when_ready("http://127.0.0.1:8765", timeout=5) is True
    assert opened == ["http://127.0.0.1:8765"]


def test_open_when_ready_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.httpx, "get", lambda *_a, **_k: httpx.Response(500))
    monkeypatch.setattr(cli.webbrowser, "open", lambda _u: pytest.fail("must not open"))
    clock = iter([0.0, 0.1, 10.0, 10.0])
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(cli.time, "sleep", lambda _s: None)
    assert cli.open_when_ready("http://127.0.0.1:8765", timeout=5) is False
