"""No Qt in the server process: loading the pack and running the template must not import PyQt5."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parents[4] / "packs" / "rbcodes" / "templates"
CASES = {
    "absorption-line-measurement.acw": ("ew", "save"),
    "redshift-finder.acw": ("rank_gal", "zshift_qso"),
    "multi-spectrum-viewer.acw": ("viewer", "export", "vstack"),
    "ifu-cube-explorer.acw": ("extract", "moments", "names", "reg"),
}

SCRIPT = r"""
import json, os, sys, asyncio
from pathlib import Path
from astro_canvas.sdk import discover
from astro_canvas.settings import Settings
from astro_canvas.cli import run_headless

workspace = Path(sys.argv[1]); template = Path(sys.argv[2])
settings = Settings(
    workspace=workspace, config_dir=workspace / "config", process_pool=False, auth="none"
)
discovery = discover()
assert all(p.error is None for p in discovery.packs), [p.error for p in discovery.packs]
summary = asyncio.run(run_headless(settings, template, None))
mpl = sys.modules.get("matplotlib")
print(json.dumps({
    "status": summary["status"],
    "states": {k: v["state"] for k, v in summary["nodes"].items()},
    "pyqt5": "PyQt5" in sys.modules,
    "qt_any": any(m.startswith(("PyQt", "PySide")) for m in sys.modules),
    "mpl_backend": mpl.get_backend() if mpl is not None else None,
    "mpl_pyplot": "matplotlib.pyplot" in sys.modules,
}))
"""


@pytest.mark.parametrize("template", sorted(CASES))
def test_pack_and_template_run_without_qt(tmp_path: Path, template: str) -> None:
    """Runs in a subprocess so earlier tests cannot have imported Qt already."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    env = {**os.environ, "MPLBACKEND": "Agg", "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run(
        [sys.executable, "-c", SCRIPT, str(workspace), str(TEMPLATES / template)],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-4000:]
    import json

    report = json.loads(proc.stdout.strip().splitlines()[-1])
    assert report["pyqt5"] is False and report["qt_any"] is False
    assert report["status"] == "done", report
    assert all(report["states"][node] == "done" for node in CASES[template]), report
    assert report["mpl_backend"] in (None, "agg", "Agg")
