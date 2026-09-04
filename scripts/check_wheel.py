"""Assert the newest ``astro_canvas`` wheel bundles the SPA (``astro_canvas/static/index.html``).

Looks in ``backend/dist`` by default; ``--dist <dir>`` points it somewhere else, which is what
the Docker build does (it collects every wheel in one directory).
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIST = ROOT / "backend" / "dist"


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    dist = DEFAULT_DIST
    if "--dist" in args:
        index = args.index("--dist")
        if index + 1 >= len(args):
            sys.stderr.write("error: --dist needs a directory\n")
            return 2
        dist = Path(args[index + 1])
    wheels = sorted(dist.glob("astro_canvas-*.whl"), key=lambda p: p.stat().st_mtime)
    if not wheels:
        sys.stderr.write(f"error: no wheel in {dist}; run `uv build backend` first\n")
        return 1
    wheel = wheels[-1]
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
    required = "astro_canvas/static/index.html"
    if required not in names:
        sys.stderr.write(f"error: {wheel.name} lacks {required}\n")
        return 1
    static = [n for n in names if n.startswith("astro_canvas/static/")]
    size_mb = wheel.stat().st_size / 1024**2
    sys.stdout.write(
        f"ok: {wheel.name} contains {required} "
        f"({len(static)} static files, {size_mb:.1f} MB wheel)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
