"""Enforce the tooling rule: pnpm only for the frontend, uv only for the backend.

Scans scripts, CI, docs, and manifests for forbidden package-manager invocations and for
lockfiles that should not exist. Exit code 1 lists every violation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCAN_ROOTS = [
    "Taskfile.yml",
    "README.md",
    "CONTRIBUTING.md",
    ".github",
    "docs",
    "launcher",
    "deploy",
    "scripts",
    "frontend/package.json",
    "frontend/playwright.config.ts",
    "backend/pyproject.toml",
    "backend/README.md",
    "packs",
]
SKIP_DIRS = {"node_modules", ".venv", "dist", "designs", "__pycache__"}
SKIP_SUFFIXES = {".patch", ".lock", ".png", ".svg", ".ico"}

FORBIDDEN = [
    re.compile(r"\b(npm|npx|yarn|bun)\s+(install|i|ci|run|exec|add|create|dlx|x)\b"),
    re.compile(r"\bnpx\s+\S"),
    # `uv pip ...` is allowed (manager code targeting the app env); bare pip is not.
    re.compile(r"(?<!uv )\bpip3?\s+(install|download|wheel|freeze|uninstall)\b"),
    re.compile(r"\bpython3?\s+-m\s+(pip|venv|virtualenv)\b"),
    re.compile(r"\bpip-(compile|sync)\b"),
    re.compile(r"\bpoetry\s+(install|add|run|lock|build)\b"),
    re.compile(r"\bconda\s+(install|create|env|activate)\b"),
    re.compile(r"\bvirtualenv\s+\S"),
]
FORBIDDEN_FILES = [
    "frontend/package-lock.json",
    "frontend/yarn.lock",
    "frontend/bun.lockb",
    "frontend/bun.lock",
]
SELF = Path(__file__).resolve()


def iter_files() -> list[Path]:
    files: list[Path] = []
    for entry in SCAN_ROOTS:
        path = ROOT / entry
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            for sub in path.rglob("*"):
                if sub.is_file() and not (set(sub.parts) & SKIP_DIRS):
                    files.append(sub)
    return [f for f in files if f != SELF and f.suffix not in SKIP_SUFFIXES]


def main() -> int:
    problems: list[str] = []
    for file in iter_files():
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in FORBIDDEN:
                if pattern.search(line):
                    rel = file.relative_to(ROOT).as_posix()
                    problems.append(f"{rel}:{lineno}: {line.strip()}")
                    break
    for name in FORBIDDEN_FILES:
        if (ROOT / name).exists():
            problems.append(f"{name}: must not exist (pnpm-lock.yaml is the only lockfile)")
    for req in (ROOT / "backend").glob("requirements*.txt"):
        problems.append(f"{req.relative_to(ROOT).as_posix()}: must not exist (use uv.lock)")

    if problems:
        listing = "\n  ".join(problems)
        sys.stderr.write(f"tooling rule violations (pnpm/uv only):\n  {listing}\n")
        return 1
    sys.stdout.write("ok: no npm/npx/yarn/bun/pip/poetry/conda invocations found\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
