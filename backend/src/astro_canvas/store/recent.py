"""Recently used workspace folders, kept per user in ``<config>/workspaces.json``."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

MAX_RECENT = 10
FILE_NAME = "workspaces.json"
SELECTED_FILE = "workspace"


class RecentWorkspaces:
    """A small most-recent-first list of workspace roots, plus the chosen default.

    The list is a convenience (the *Open workspace* menu); the single-line ``workspace`` file
    beside it is the *decision* -- what ``astro-canvas serve`` opens next time. Only an explicit
    choice writes it (``astro-canvas workspace use``, or switching folders in the app), so a
    headless ``astro-canvas run --workspace /tmp/x`` never moves the user's default.
    """

    def __init__(self, config_dir: Path, *, limit: int = MAX_RECENT) -> None:
        self.path = Path(config_dir) / FILE_NAME
        self.selected_path = Path(config_dir) / SELECTED_FILE
        self.limit = limit

    def selected(self) -> Path | None:
        """The workspace the user last chose, or ``None`` when they never did."""
        try:
            text = self.selected_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return Path(text) if text else None

    def select(self, root: Path) -> Path:
        """Record ``root`` as the default workspace and move it to the front of the list."""
        target = Path(root).resolve()
        self.touch(target)
        try:
            self.selected_path.parent.mkdir(parents=True, exist_ok=True)
            self.selected_path.write_text(str(target), encoding="utf-8")
        except OSError:
            pass  # an unwritable config dir only loses the default; the folder still opens
        return target

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
