"""Per-package coverage gates over ``backend/coverage.json`` (written by pytest-cov).

Thresholds are line coverage percentages for files whose path contains the package fragment.
Run after ``uv run --directory backend pytest``; exit code 1 lists every gate that failed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "backend" / "coverage.json"

# Package fragment (posix path) -> minimum line coverage in percent (CONVENTIONS §5; phases 01-02).
GATES: dict[str, float] = {
    "astro_canvas/sdk/": 90.0,
    "astro_canvas/engine/": 85.0,
    "astro_canvas/store/": 85.0,
}


def main() -> int:
    if not REPORT.is_file():
        sys.stderr.write(f"error: {REPORT} not found; run pytest first\n")
        return 1
    files = json.loads(REPORT.read_text(encoding="utf-8"))["files"]
    failures: list[str] = []
    for fragment, minimum in GATES.items():
        covered = total = 0
        for path, data in files.items():
            if fragment in Path(path).as_posix():
                covered += int(data["summary"]["covered_lines"])
                total += int(data["summary"]["num_statements"])
        if total == 0:
            failures.append(f"{fragment}: no files measured")
            continue
        percent = 100.0 * covered / total
        status = "ok" if percent >= minimum else "FAIL"
        sys.stdout.write(f"{status}: {fragment} {percent:.1f}% (min {minimum:.0f}%)\n")
        if percent < minimum:
            failures.append(f"{fragment}: {percent:.1f}% < {minimum:.0f}%")
    for failure in failures:
        sys.stderr.write(f"coverage gate failed: {failure}\n")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
