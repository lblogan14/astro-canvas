"""Start a ``--auth users`` server against ``$ASTRO_CANVAS_DATABASE_URL`` and use it.

Run by the ``postgres`` CI job. The unit tests cover the identity schema on Postgres; this covers
the thing the schema exists for -- registering, logging in, getting your own workspace, and the
admin flag -- against the real database a lab deployment uses.

    ASTRO_CANVAS_DATABASE_URL=postgresql://canvas:canvas@127.0.0.1:5432/canvas \\
        uv run --directory backend python ../scripts/smoke_postgres.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from pathlib import Path

ADMIN = "pi@example.org"
MEMBER = "student@example.org"
PASSWORD = "a good long phrase"


def main() -> int:
    url = os.environ.get("ASTRO_CANVAS_DATABASE_URL", "")
    if "postgres" not in url:
        sys.stderr.write("error: set ASTRO_CANVAS_DATABASE_URL to a Postgres instance\n")
        return 2

    # Imported here so the module can be read without the backend environment.
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from astro_canvas.sdk import discover  # noqa: PLC0415
    from astro_canvas.server.app import create_app  # noqa: PLC0415
    from astro_canvas.settings import Settings  # noqa: PLC0415

    root = Path(tempfile.mkdtemp(prefix="astro-canvas-pg-"))
    # Unique addresses: the CI database is not dropped between steps.
    suffix = uuid.uuid4().hex[:8]
    admin, member = f"{suffix}-{ADMIN}", f"{suffix}-{MEMBER}"
    settings = Settings(
        workspace=root,
        config_dir=root / "config",
        users_dir=root / "users",
        auth="users",
        process_pool=False,
        watch_workspace=False,
        admin_emails=admin,
    )

    with TestClient(create_app(settings, discover())) as client:
        info = client.get("/api/auth/info").json()
        assert info["mode"] == "users", info
        assert client.get("/api/workflows").status_code == 401

        roots = {}
        for email, expect_admin in ((admin, True), (member, False)):
            created = client.post("/api/auth/register", json={"email": email, "password": PASSWORD})
            assert created.status_code == 201, created.text
            assert created.json()["is_superuser"] is expect_admin, created.text

            login = client.post("/api/auth/login", data={"username": email, "password": PASSWORD})
            assert login.status_code in (200, 204), login.text

            roots[email] = client.get("/api/workspace").json()["root"]
            manager = client.get("/api/manager/packs").status_code
            assert manager == (200 if expect_admin else 403), (email, manager)
            client.cookies.clear()

        assert roots[admin] != roots[member], roots
        sys.stdout.write(
            f"ok: two accounts on postgres, separate workspaces, admin-only manager\n"
            f"    admin  {roots[admin]}\n"
            f"    member {roots[member]}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
