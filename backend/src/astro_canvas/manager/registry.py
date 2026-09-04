"""Client for the git-backed pack registry (design 9).

The registry is one JSON file in a git repository served over HTTPS -- no service to run, no
account to hold, and publishing is a pull request (``docs/packs/publishing.md``). The client
fetches it at most once an hour, revalidates with an ``ETag`` so a refresh costs a 304, and keeps
the last good copy on disk so the Registry tab still lists packs offline.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError

log = structlog.get_logger("astro_canvas.manager")

DEFAULT_REGISTRY_URL = (
    "https://raw.githubusercontent.com/lblogan14/astro-canvas-registry/main/index.json"
)
CACHE_TTL_S = 3600.0
"""Design 9: cache the index for one hour."""
CACHE_FILE = "registry-cache.json"
BUILTIN_INDEX = Path(__file__).with_name("builtin_index.json")
"""A copy of this repo's ``registry/index.json``, so the Registry tab works before first contact."""


class RegistryTemplate(BaseModel):
    """A template a registry entry advertises; mirrors ``TemplateInfo`` (phase 10)."""

    id: str
    name: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    layouts: list[str] = Field(default_factory=list)
    default_layout: str = "canvas"


class RegistryEntry(BaseModel):
    """One pack in ``index.json``."""

    name: str
    display_name: str = ""
    publisher: str = ""
    description: str = ""
    source: str = Field(description="What the manager installs: a PyPI requirement or a git URL.")
    latest: str = ""
    requires: dict[str, str] = Field(default_factory=dict)
    categories: list[str] = Field(default_factory=list)
    templates: list[RegistryTemplate] = Field(default_factory=list)
    security: str = "standard"
    homepage: str = ""
    stars: int | None = None

    @property
    def title(self) -> str:
        return self.display_name or self.name


class RegistryIndex(BaseModel):
    """The fetched index plus where it came from and how fresh it is."""

    url: str = ""
    entries: list[RegistryEntry] = Field(default_factory=list)
    fetched: float = 0.0
    stale: bool = Field(default=False, description="True when served from cache after a failure.")
    error: str | None = None

    def search(self, query: str = "", category: str | None = None) -> list[RegistryEntry]:
        """Entries matching a free-text ``query`` (name/description/categories) and ``category``."""
        needle = query.strip().lower()
        out: list[RegistryEntry] = []
        for entry in self.entries:
            if category and category not in entry.categories:
                continue
            haystack = " ".join(
                [entry.name, entry.display_name, entry.description, *entry.categories]
            ).lower()
            if needle and needle not in haystack:
                continue
            out.append(entry)
        return out


def parse_index(payload: Any, *, url: str = "") -> RegistryIndex:
    """Validate a decoded ``index.json``.

    Accepts the design's bare list of entries and, for forward compatibility, an object with a
    ``packs`` (or ``entries``) key. Entries that do not validate are logged and skipped so one
    malformed submission cannot blank the whole registry.

    Raises:
        ValueError: when the payload is neither shape.
    """
    raw = payload.get("packs", payload.get("entries")) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise ValueError("registry index must be a list of pack entries")
    entries: list[RegistryEntry] = []
    for item in raw:
        try:
            entries.append(RegistryEntry.model_validate(item))
        except ValidationError as exc:
            name = item.get("name") if isinstance(item, dict) else item
            log.warning("registry entry skipped", entry=str(name), error=str(exc))
    return RegistryIndex(url=url, entries=entries, fetched=time.time())


class RegistryClient:
    """Fetches and caches ``index.json``.

    Args:
        url: Index URL; empty falls back to ``DEFAULT_REGISTRY_URL``.
        cache_dir: Where the last good copy and its ETag are kept.
        ttl: Seconds before a cached index is refetched.
    """

    def __init__(
        self, url: str = "", cache_dir: Path | None = None, *, ttl: float = CACHE_TTL_S
    ) -> None:
        self.url = url or DEFAULT_REGISTRY_URL
        self.cache_dir = cache_dir
        self.ttl = ttl
        self._index: RegistryIndex | None = None
        self._etag: str | None = None

    @property
    def cache_path(self) -> Path | None:
        return self.cache_dir / CACHE_FILE if self.cache_dir else None

    def _load_cache(self) -> RegistryIndex | None:
        path = self.cache_path
        if path is None or not path.is_file():
            return None
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            index = parse_index(body.get("index"), url=body.get("url", self.url))
            index.fetched = float(body.get("fetched", 0.0))
            self._etag = body.get("etag")
        except (OSError, ValueError) as exc:
            log.warning("registry cache unreadable", error=str(exc))
            return None
        return index

    def _save_cache(self, payload: Any, index: RegistryIndex) -> None:
        path = self.cache_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "url": self.url,
                        "etag": self._etag,
                        "fetched": index.fetched,
                        "index": payload,
                    }
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover - read-only config dir
            log.warning("registry cache not written", error=str(exc))

    def fetch(self, *, refresh: bool = False) -> RegistryIndex:
        """The index, from memory, disk or the network depending on age and ``refresh``.

        Never raises: a network failure returns the last good copy marked ``stale`` (or an empty
        index carrying ``error``), because the Registry tab must still render.
        """
        if self._index is None:
            self._index = self._load_cache()
        cached = self._index
        fresh_enough = cached is not None and (time.time() - cached.fetched) < self.ttl
        if cached is not None and fresh_enough and not refresh:
            return cached
        if self.url.startswith("file://") or not self.url.startswith(("http://", "https://")):
            return self._read_local(cached)
        import httpx  # noqa: PLC0415 - lazy: only the network path needs an HTTP client

        headers = {"Accept": "application/json"}
        if self._etag and cached is not None:
            headers["If-None-Match"] = self._etag
        try:
            response = httpx.get(self.url, headers=headers, follow_redirects=True, timeout=20.0)
            if response.status_code == 304 and cached is not None:
                cached.fetched = time.time()
                cached.stale = False
                cached.error = None
                self._index = cached
                return cached
            response.raise_for_status()
            payload = response.json()
            index = parse_index(payload, url=self.url)
            self._etag = response.headers.get("ETag")
            self._index = index
            self._save_cache(payload, index)
            return index
        except Exception as exc:  # noqa: BLE001 - the registry is optional, never fatal
            log.warning("registry fetch failed", url=self.url, error=str(exc))
            if cached is not None:
                cached.stale = True
                cached.error = str(exc)
                return cached
            return self._builtin(str(exc))

    def _builtin(self, error: str) -> RegistryIndex:
        """The index shipped inside the wheel, marked stale, when nothing else is available."""
        try:
            index = parse_index(json.loads(BUILTIN_INDEX.read_text(encoding="utf-8")), url=self.url)
        except (OSError, ValueError) as exc:  # pragma: no cover - the file ships with the wheel
            log.warning("built-in registry index unreadable", error=str(exc))
            return RegistryIndex(url=self.url, error=error, stale=True)
        index.stale = True
        index.error = error
        index.fetched = 0.0
        return index

    def _read_local(self, cached: RegistryIndex | None) -> RegistryIndex:
        """A ``file://`` or plain-path registry (the seed index in this repo, and tests)."""
        path = Path(self.url[7:] if self.url.startswith("file://") else self.url)
        try:
            index = parse_index(json.loads(path.read_text(encoding="utf-8")), url=self.url)
        except (OSError, ValueError) as exc:
            log.warning("registry file unreadable", path=str(path), error=str(exc))
            if cached is not None:
                cached.stale = True
                cached.error = str(exc)
                return cached
            return self._builtin(str(exc))
        self._index = index
        return index

    def entry(self, name: str) -> RegistryEntry | None:
        normalized = name.replace("_", "-").lower()
        for candidate in self.fetch().entries:
            if candidate.name.replace("_", "-").lower() == normalized:
                return candidate
        return None


__all__ = [
    "CACHE_TTL_S",
    "DEFAULT_REGISTRY_URL",
    "RegistryClient",
    "RegistryEntry",
    "RegistryIndex",
    "RegistryTemplate",
    "parse_index",
]
