"""Write the app's OpenAPI document to ``backend/src/astro_canvas/server/openapi/openapi.json``.

``--check`` exits 1 when the committed snapshot differs from the running app (CI runs this so the
generated frontend client, ``task api:gen``, never drifts from the backend).

The app is rendered in ``--auth users`` mode because that is the superset: the single-user server
serves the same routes minus ``/api/auth`` and ``/api/users``, and the SPA has to be typed against
both, since it does not know which one it is talking to until ``/api/auth/info`` answers.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "backend" / "src" / "astro_canvas" / "server" / "openapi" / "openapi.json"


def render() -> str:
    # Imported lazily so the module can be read without the backend environment.
    from astro_canvas.sdk import discover  # noqa: PLC0415
    from astro_canvas.server.app import create_app  # noqa: PLC0415
    from astro_canvas.settings import Settings  # noqa: PLC0415

    workspace = Path(tempfile.mkdtemp(prefix="astro-canvas-openapi-"))
    settings = Settings(
        workspace=workspace,
        config_dir=workspace / "config",
        users_dir=workspace / "users",
        auth="users",
        watch_workspace=False,
    )
    app = create_app(settings, discover())
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    document = render()
    if "--check" in argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
        if current != document:
            sys.stderr.write(f"error: {TARGET.relative_to(ROOT)} is stale; run `task api:gen`\n")
            return 1
        sys.stdout.write("ok: openapi.json is current\n")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(document, encoding="utf-8")
    sys.stdout.write(f"wrote {TARGET.relative_to(ROOT)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
