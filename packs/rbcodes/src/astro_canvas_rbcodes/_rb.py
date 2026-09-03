"""Lazy access to the installed ``rbcodes`` distribution and provenance for node outputs.

``rbcodes`` is optional at runtime: its upstream pin (``python_requires <3.11``) keeps it out of
Python 3.12 environments until the patch in ``docs/dev/rbcodes-upstream.patch`` lands. When it is
importable the nodes call rbcodes itself; otherwise they fall back to the vendored kernels in
``astro_canvas_rbcodes.kernels`` (line-by-line ports of the same functions, MIT). Either way the
numbers are the same and ``provenance()`` records which backend produced them.

Nothing here imports ``rbcodes`` at module import time (some rbcodes modules select a Qt
matplotlib backend on import); ``MPLBACKEND`` is pinned by the package ``__init__``.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
from functools import lru_cache
from types import ModuleType
from typing import Any

VENDORED_VERSION = "2.4.0"
"""rbcodes version the kernels were ported from (commit ``4499012``)."""
VENDORED_COMMIT = "4499012e77eb3bbb9ca934b5b53909864581d060"


def _headless() -> None:
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@lru_cache(maxsize=1)
def rbcodes_version() -> str | None:
    """Installed rbcodes version, or ``None`` when the distribution is not importable."""
    if os.environ.get("ASTRO_CANVAS_RBCODES_DISABLE"):
        return None
    try:
        return importlib.metadata.version("rbcodes")
    except importlib.metadata.PackageNotFoundError:
        return None


def rbcodes_available() -> bool:
    return rbcodes_version() is not None


def import_rbcodes(module: str) -> ModuleType | None:
    """Import ``rbcodes.<module>`` headlessly; ``None`` when rbcodes is missing or broken."""
    if not rbcodes_available():
        return None
    _headless()
    try:
        return importlib.import_module(f"rbcodes.{module}")
    except Exception:  # noqa: BLE001 - a broken optional dependency falls back to the kernels
        return None


def provenance(**extra: Any) -> dict[str, Any]:
    """``meta`` block recorded on every output: which rbcodes produced the numbers."""
    version = rbcodes_version()
    out: dict[str, Any] = {
        "backend": "rbcodes" if version else "vendored",
        "rbcodes_version": version or f"{VENDORED_VERSION}+vendored",
        "vendored_from": f"{VENDORED_VERSION}@{VENDORED_COMMIT[:7]}",
    }
    out.update(extra)
    return out


__all__ = [
    "VENDORED_COMMIT",
    "VENDORED_VERSION",
    "import_rbcodes",
    "provenance",
    "rbcodes_available",
    "rbcodes_version",
]
