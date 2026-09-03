"""Start the installed `astro-canvas` server and check it serves the SPA and the API.

Intended to run against a fresh environment containing only the built wheel:

    uv run --isolated --no-project --with backend/dist/astro_canvas-*.whl \
        python scripts/smoke_wheel.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"


def fetch(path: str) -> str:
    with urllib.request.urlopen(BASE + path, timeout=2) as response:  # noqa: S310
        return response.read().decode()


def wait_ready(deadline_s: float = 30.0) -> None:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        try:
            if '"status":"ok"' in fetch("/api/health"):
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.25)
    raise SystemExit("server did not become ready")


def main() -> int:
    with tempfile.TemporaryDirectory() as workspace:
        cmd = [
            sys.executable,
            "-m",
            "astro_canvas.cli",
            "serve",
            "--port",
            str(PORT),
            "--workspace",
            workspace,
        ]
        proc = subprocess.Popen(cmd)
        try:
            wait_ready()
            index = fetch("/")
            assert '<div id="app">' in index, "root did not serve the SPA index"
            assert "Astro Canvas" in index, "SPA title missing"
            assert "Astro Canvas" in fetch("/workflows/x"), "history fallback failed"
            system = fetch("/api/system")
            assert '"python"' in system
            sys.stdout.write("ok: wheel serves SPA and API\n")
            return 0
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
