"""Recently used workspace folders, kept per user in ``<config>/workspaces.json``."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

MAX_RECENT = 10
FILE_NAME = "workspaces.json"


class RecentWorkspaces:
    """A small most-recent-first list of workspace roots (absolute paths)."""

    def __init__(self, config_dir: Path, *, limit: int = MAX_RECENT) -> None:
        self.path = Path(config_dir) / FILE_NAME
        self.limit = limit

    def list(self) -> builtins.list[str]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [str(p) for p in data if isinstance(p, str)][: self.limit]

    def touch(self, root: Path) -> builtins.list[str]:
        """Move ``root`` to the front and persist; returns the new list."""
        key = str(Path(root).resolve())
        items = [p for p in self.list() if p != key]
        items.insert(0, key)
        items = items[: self.limit]
        self._write(items)
        return items

    def remove(self, root: Path) -> builtins.list[str]:
        key = str(Path(root).resolve())
        items = [p for p in self.list() if p != key]
        self._write(items)
        return items

    def _write(self, items: builtins.list[str]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(items, indent=2), encoding="utf-8")
        except OSError:
            pass  # an unwritable config dir only loses the convenience list
