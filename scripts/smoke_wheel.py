"""Start the installed `astro-canvas` server and check it serves the SPA and the API.

Intended to run against a fresh environment containing only the built wheel:

    uv run --isolated --no-project --with backend/dist/astro_canvas-*.whl \
        python scripts/smoke_wheel.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = "smoke-token"


def fetch(path: str, *, token: str | None = TOKEN) -> str:
    request = urllib.request.Request(BASE + path)  # noqa: S310
    if token is not None:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=2) as response:  # noqa: S310
        return response.read().decode()


def wait_ready(deadline_s: float = 30.0) -> None:
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        try:
            if '"status":"ok"' in fetch("/api/health", token=None):
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(0.25)
    raise SystemExit("server did not become ready")


def main() -> int:
    # ``ignore_cleanup_errors``: on Windows the just-terminated server can still hold the
    # workspace SQLite handle for a moment, and a smoke test must not fail on the tidy-up.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as workspace:
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
        env = {**os.environ, "ASTRO_CANVAS_TOKEN": TOKEN, "ASTRO_CANVAS_CONFIG_DIR": workspace}
        proc = subprocess.Popen(cmd, env=env)
        try:
            wait_ready()
            index = fetch("/")
            assert '<div id="app">' in index, "root did not serve the SPA index"
            assert "Astro Canvas" in index, "SPA title missing"
            assert "Astro Canvas" in fetch("/workflows/x"), "history fallback failed"
            system = fetch("/api/system")
            assert '"python"' in system
            # No packs are installed in the smoke env: the catalogue is empty but must answer.
            assert fetch("/api/nodes") == "[]", "node catalogue should be empty without packs"
            assert fetch("/api/types") == "[]"
            assert fetch("/api/packs") == "[]"
            assert fetch("/api/workflows") == "[]", "workflow store should start empty"
            try:
                fetch("/api/workflows", token=None)
            except urllib.error.HTTPError as exc:
                assert exc.code == 401, "API must reject requests without the token"
            else:
                raise AssertionError("API answered without a token")
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
