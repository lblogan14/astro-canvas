"""Assert the newest wheel in backend/dist bundles the SPA (astro_canvas/static/index.html)."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "backend" / "dist"


def main() -> int:
    wheels = sorted(DIST.glob("astro_canvas-*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        sys.stderr.write(f"error: no wheel in {DIST}; run `uv build backend` first\n")
        return 1
    wheel = wheels[-1]
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
    required = "astro_canvas/static/index.html"
    if required not in names:
        sys.stderr.write(f"error: {wheel.name} lacks {required}\n")
        return 1
    static = [n for n in names if n.startswith("astro_canvas/static/")]
    sys.stdout.write(f"ok: {wheel.name} contains {required} ({len(static)} static files)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
