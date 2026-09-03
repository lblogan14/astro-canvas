"""``astro-canvas run``: headless execution with a per-node summary."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from astro_canvas import cli

runner = CliRunner()
WORKFLOWS = Path(__file__).resolve().parent / "fixtures" / "workflows"


def test_run_prints_summary_and_exit_zero(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        ["run", str(WORKFLOWS / "math_chain.json"), "--workspace", str(tmp_path), "--no-processes"],
    )
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].startswith("run ") and lines[0].endswith(": done")
    table = {line.split()[0]: line for line in lines[1:]}
    assert table["sum"].split()[1] == "done" and "out:astro.Float" in table["sum"]
    assert (tmp_path / ".astro-canvas" / "app.db").is_file()


def test_run_json_and_targets_use_cache_on_second_run(tmp_path: Path) -> None:
    args = [
        "run",
        str(WORKFLOWS / "math_chain.json"),
        "--workspace",
        str(tmp_path),
        "--no-processes",
        "--json",
        "--target",
        "sq",
    ]
    first = runner.invoke(cli.app, args)
    assert first.exit_code == 0, first.output
    summary = json.loads(first.output)
    assert summary["status"] == "done"
    assert summary["nodes"]["sq"]["state"] == "done" and summary["nodes"]["sum"]["state"] == "dirty"
    second = json.loads(runner.invoke(cli.app, args).output)
    assert second["nodes"]["sq"]["cache_hit"] is True and second["nodes"]["c"]["cache_hit"] is True


def test_run_invalid_workflow_exits_one(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "run",
            str(WORKFLOWS / "invalid" / "cycle.json"),
            "--workspace",
            str(tmp_path),
            "--no-processes",
        ],
    )
    assert result.exit_code == 1
    assert "! a: cycle" in result.output and "! b: cycle" in result.output


def test_serve_prints_token_url(monkeypatch: object, tmp_path: Path) -> None:
    import pytest

    mp = monkeypatch
    assert isinstance(mp, pytest.MonkeyPatch)
    mp.setattr(cli.uvicorn, "run", lambda app, **kw: None)
    from astro_canvas.settings import Settings

    settings = Settings(
        port=8123, workspace=tmp_path / "ws", config_dir=tmp_path / "cfg", token="abc"
    )
    import contextlib
    import io

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        cli.run_server(settings, open_browser=False)
    assert "http://127.0.0.1:8123/?token=abc" in buffer.getvalue()
