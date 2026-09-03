"""Copy the built SPA (frontend/dist) into the wheel's static folder.

Run by `task build` and CI after `pnpm -C frontend build`. Uses only the stdlib so it
works from any interpreter: ``uv run --directory backend python ../scripts/copy_static.py``.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "frontend" / "dist"
STATIC = ROOT / "backend" / "src" / "astro_canvas" / "static"


def main() -> int:
    if not (DIST / "index.html").is_file():
        sys.stderr.write(f"error: {DIST} has no index.html; run `pnpm -C frontend build` first\n")
        return 1
    STATIC.mkdir(parents=True, exist_ok=True)
    for entry in STATIC.iterdir():
        if entry.name == ".gitkeep":
            continue
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    shutil.copytree(DIST, STATIC, dirs_exist_ok=True)
    count = sum(1 for p in STATIC.rglob("*") if p.is_file())
    sys.stdout.write(f"copied {count} files from {DIST} to {STATIC}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
