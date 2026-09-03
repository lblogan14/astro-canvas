"""Settings come from ``ASTRO_CANVAS_*`` with sane defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from astro_canvas.settings import Settings, default_workspace, get_settings


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("HOST", "PORT", "WORKSPACE", "LOG_LEVEL"):
        monkeypatch.delenv(f"ASTRO_CANVAS_{key}", raising=False)
    s = Settings()
    assert (s.host, s.port, s.log_level) == ("127.0.0.1", 8765, "info")
    assert s.workspace == default_workspace()
    assert s.workspace.name == "AstroCanvas"


def test_env_prefix(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ASTRO_CANVAS_PORT", "9001")
    monkeypatch.setenv("ASTRO_CANVAS_HOST", "0.0.0.0")
    monkeypatch.setenv("ASTRO_CANVAS_WORKSPACE", str(tmp_path))
    s = get_settings()
    assert (s.host, s.port, s.workspace) == ("0.0.0.0", 9001, tmp_path)


def test_overrides_beat_env_and_none_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASTRO_CANVAS_PORT", "9001")
    s = get_settings(port=7000, host=None)
    assert s.port == 7000
    assert s.host == "127.0.0.1"


def test_port_is_validated() -> None:
    with pytest.raises(ValueError, match="port"):
        Settings(port=70000)
