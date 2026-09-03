"""Cache keys and stores (design 6.2).

``key(node) = blake3(type_id | version | canonical_json(params) | fingerprint | upstream keys)``

* ``BlobStore``: content-addressed directory of packed blobs (write-temp-rename, GC by size/age).
* ``OutputIndex``: SQLite index (``outputs`` table) from ``(key, port)`` to blob hash and type.
* ``MemoryLRU``: byte-accounted in-memory cache of deserialized outputs.
* ``OutputCache``: the three combined; ``astro.Any`` values stay memory-only.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from blake3 import blake3
from pydantic_core import to_jsonable_python
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from astro_canvas.sdk import Blob, BlobError, PortType, TypeRegistry
from astro_canvas.store.models import Output, utcnow


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, numpy/pydantic values made JSON-safe."""
    return json.dumps(
        to_jsonable_python(value, fallback=_fallback),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _fallback(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"{type(value).__name__} is not JSON-serializable")


def digest(data: bytes) -> str:
    """blake3 hex digest of ``data``."""
    return str(blake3(data).hexdigest())


def cache_key(
    type_id: str,
    version: str,
    params: Mapping[str, Any],
    upstream: Mapping[str, str],
    fingerprint: Any = None,
) -> str:
    """Hash a node's identity: type, version, resolved params, fingerprint and input keys.

    ``upstream`` maps each connected input port to ``"<upstream key>:<upstream port>"``.
    """
    payload = [type_id, version, dict(params), fingerprint, sorted(upstream.items())]
    return digest(canonical_json(payload).encode("utf-8"))


def sub_key(parent_key: str, sub_id: str) -> str:
    """Cache key of an expansion sub-node, derived from its parent's key."""
    return digest(f"{parent_key}/{sub_id}".encode())


# --- blob store --------------------------------------------------------------------------------


@dataclass(frozen=True)
class BlobEntry:
    digest: str
    size: int
    mtime: float


class BlobStore:
    """Content-addressed files ``<root>/<aa>/<digest>``; writes are temp-file + atomic rename."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        if len(key) < 3 or not all(c in "0123456789abcdef" for c in key):
            raise ValueError(f"invalid blob digest {key!r}")
        return self.root / key[:2] / key

    def put(self, data: bytes) -> str:
        """Store ``data``; returns its digest. Existing content is left untouched."""
        key = digest(data)
        target = self.path(key)
        if target.exists():
            return key
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return key

    def has(self, key: str) -> bool:
        return self.path(key).is_file()

    def get(self, key: str) -> bytes:
        try:
            return self.path(key).read_bytes()
        except FileNotFoundError:
            raise KeyError(key) from None

    def delete(self, key: str) -> bool:
        try:
            self.path(key).unlink()
        except FileNotFoundError:
            return False
        return True

    def entries(self) -> Iterator[BlobEntry]:
        for shard in self.root.iterdir():
            if not shard.is_dir():
                continue
            for file in shard.iterdir():
                if file.name.startswith(".tmp-") or not file.is_file():
                    continue
                stat = file.stat()
                yield BlobEntry(file.name, stat.st_size, stat.st_mtime)

    def size(self) -> int:
        return sum(e.size for e in self.entries())

    def gc(
        self,
        *,
        max_bytes: int | None = None,
        max_age: timedelta | None = None,
        keep: Collection[str] = (),
        now: float | None = None,
    ) -> list[str]:
        """Delete blobs older than ``max_age`` and then the oldest until under ``max_bytes``.

        Digests in ``keep`` are never deleted. Returns the removed digests.
        """
        now = now if now is not None else datetime.now().timestamp()
        removed: list[str] = []
        entries = sorted(self.entries(), key=lambda e: e.mtime)
        total = sum(e.size for e in entries)
        for entry in entries:
            if entry.digest in keep:
                continue
            too_old = max_age is not None and now - entry.mtime > max_age.total_seconds()
            too_big = max_bytes is not None and total > max_bytes
            if (too_old or too_big) and self.delete(entry.digest):
                removed.append(entry.digest)
                total -= entry.size
        return removed


# --- output index ------------------------------------------------------------------------------


@dataclass(frozen=True)
class OutputRef:
    """Where a cached output lives on disk."""

    key: str
    port: str
    type_id: str
    blob_hash: str
    nbytes: int
    node_type: str = ""


class OutputIndex:
    """``outputs`` table access: ``(key, port) -> OutputRef``."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._lock = threading.Lock()

    def put(self, refs: Collection[OutputRef], manifests: Mapping[str, Any] | None = None) -> None:
        with self._lock, self._sessions() as session:
            for ref in refs:
                session.merge(
                    Output(
                        key=ref.key,
                        port=ref.port,
                        node_type=ref.node_type,
                        type_id=ref.type_id,
                        blob_hash=ref.blob_hash,
                        blob_manifest=json.dumps((manifests or {}).get(ref.port, {})),
                        bytes=ref.nbytes,
                        created=utcnow(),
                        last_used=utcnow(),
                    )
                )
            session.commit()

    def get(self, key: str, *, touch: bool = True) -> dict[str, OutputRef] | None:
        """All ports cached under ``key`` (``None`` when nothing is indexed)."""
        with self._lock, self._sessions() as session:
            rows = session.scalars(select(Output).where(Output.key == key)).all()
            if not rows:
                return None
            if touch:
                session.execute(update(Output).where(Output.key == key).values(last_used=utcnow()))
                session.commit()
            return {
                r.port: OutputRef(r.key, r.port, r.type_id, r.blob_hash, r.bytes, r.node_type)
                for r in rows
            }

    def forget(self, key: str) -> None:
        with self._lock, self._sessions() as session:
            session.execute(delete(Output).where(Output.key == key))
            session.commit()

    def total_bytes(self) -> int:
        with self._lock, self._sessions() as session:
            return int(session.scalar(select(func.coalesce(func.sum(Output.bytes), 0))) or 0)

    def referenced_hashes(self) -> set[str]:
        with self._lock, self._sessions() as session:
            return set(session.scalars(select(Output.blob_hash).distinct()).all())

    def evict(self, *, max_bytes: int | None, max_age: timedelta | None) -> list[str]:
        """Drop least-recently-used rows by age then size; returns the evicted keys."""
        evicted: list[str] = []
        with self._lock, self._sessions() as session:
            if max_age is not None:
                cutoff = utcnow() - max_age
                old = session.scalars(
                    select(Output.key).where(Output.last_used < cutoff).distinct()
                ).all()
                if old:
                    session.execute(delete(Output).where(Output.key.in_(old)))
                    evicted.extend(old)
            if max_bytes is not None:
                total = int(session.scalar(select(func.coalesce(func.sum(Output.bytes), 0))) or 0)
                if total > max_bytes:
                    rows = session.execute(
                        select(Output.key, func.sum(Output.bytes), func.min(Output.last_used))
                        .group_by(Output.key)
                        .order_by(func.min(Output.last_used))
                    ).all()
                    for key, nbytes, _ in rows:
                        if total <= max_bytes:
                            break
                        session.execute(delete(Output).where(Output.key == key))
                        evicted.append(key)
                        total -= int(nbytes or 0)
            session.commit()
        return evicted


# --- memory LRU --------------------------------------------------------------------------------


def value_nbytes(value: Any) -> int:
    """Rough memory footprint of a port value (array bytes + a small constant per leaf)."""
    if isinstance(value, PortType):
        value = value.model_dump(mode="python")
    if isinstance(value, np.ndarray):
        return int(value.nbytes)
    if isinstance(value, bytes | bytearray | memoryview):
        return len(value)
    if isinstance(value, Mapping):
        return sum(value_nbytes(v) for v in value.values()) + 64
    if isinstance(value, list | tuple):
        return sum(value_nbytes(v) for v in value) + 64
    if isinstance(value, str):
        return len(value) + 48
    return 32


class MemoryLRU:
    """LRU of ``key -> outputs`` with byte accounting (thread-safe)."""

    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max_bytes
        self._items: OrderedDict[str, tuple[dict[str, PortType], int]] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    @property
    def nbytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: object) -> bool:
        return key in self._items

    def get(self, key: str) -> dict[str, PortType] | None:
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            self._items.move_to_end(key)
            return dict(item[0])

    def put(self, key: str, outputs: Mapping[str, PortType], nbytes: int | None = None) -> None:
        size = nbytes if nbytes is not None else sum(value_nbytes(v) for v in outputs.values())
        with self._lock:
            if key in self._items:
                self._bytes -= self._items.pop(key)[1]
            if size > self.max_bytes:
                return  # a single value larger than the whole cache is not worth keeping
            self._items[key] = (dict(outputs), size)
            self._bytes += size
            while self._bytes > self.max_bytes and len(self._items) > 1:
                _, (_, evicted) = self._items.popitem(last=False)
                self._bytes -= evicted

    def pop(self, key: str) -> None:
        with self._lock:
            item = self._items.pop(key, None)
            if item is not None:
                self._bytes -= item[1]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0


# --- combined cache ----------------------------------------------------------------------------

NO_OUTPUTS = "$none"
"""Index port name marking a completed node that produces no outputs."""


class OutputCache:
    """Memory LRU in front of the blob store + index; the scheduler's only cache API."""

    def __init__(
        self,
        *,
        memory: MemoryLRU,
        blobs: BlobStore,
        index: OutputIndex | None,
        types: TypeRegistry,
        max_disk_bytes: int | None = None,
        max_age: timedelta | None = None,
    ) -> None:
        self.memory = memory
        self.blobs = blobs
        self.index = index
        self.types = types
        self.max_disk_bytes = max_disk_bytes
        self.max_age = max_age
        self._memory_only: set[str] = set()

    def lookup(self, key: str) -> dict[str, PortType] | None:
        """Outputs for ``key`` from memory or disk (rehydrated), else ``None``."""
        hit = self.memory.get(key)
        if hit is not None:
            return hit
        refs = self.index.get(key) if self.index is not None else None
        if refs is None:
            return None
        try:
            outputs = {p: self.load(ref) for p, ref in refs.items() if p != NO_OUTPUTS}
        except (KeyError, BlobError):
            if self.index is not None:
                self.index.forget(key)
            return None
        self.memory.put(key, outputs)
        return outputs

    def refs(self, key: str) -> dict[str, OutputRef] | None:
        """Disk references for ``key`` (used to hand inputs to process workers)."""
        refs = self.index.get(key) if self.index is not None else None
        if refs is None:
            return None
        return {p: r for p, r in refs.items() if p != NO_OUTPUTS}

    def load(self, ref: OutputRef) -> PortType:
        cls = self.types.get(ref.type_id)
        return cls.from_blob(Blob.unpack(self.blobs.get(ref.blob_hash)))

    def store(
        self, key: str, node_type: str, outputs: Mapping[str, PortType]
    ) -> dict[str, OutputRef]:
        """Cache ``outputs`` in memory and, when serializable, on disk. Returns disk refs."""
        self.memory.put(key, outputs)
        refs: dict[str, OutputRef] = {}
        manifests: dict[str, Any] = {}
        for port, value in outputs.items():
            try:
                blob = value.to_blob()
            except BlobError:
                self._memory_only.add(key)
                continue
            data = blob.pack()
            blob_hash = self.blobs.put(data)
            refs[port] = OutputRef(key, port, value.type_id(), blob_hash, len(data), node_type)
            manifests[port] = blob.manifest
        if self.index is not None:
            if refs:
                self.index.put(list(refs.values()), manifests)
            elif not outputs:
                # Nodes without outputs (notes, sinks) still record that they ran.
                self.index.put([OutputRef(key, NO_OUTPUTS, "", "", 0, node_type)])
        return refs

    def adopt(self, key: str, refs: Mapping[str, OutputRef]) -> dict[str, PortType]:
        """Index refs produced by a worker process and load them into memory."""
        if self.index is not None:
            self.index.put(list(refs.values()))
        outputs = {port: self.load(ref) for port, ref in refs.items()}
        self.memory.put(key, outputs)
        return outputs

    def is_memory_only(self, key: str) -> bool:
        return key in self._memory_only

    def gc(self, *, now: float | None = None) -> list[str]:
        """Evict index rows by age/size, then delete blobs nothing references."""
        if self.index is None:
            return self.blobs.gc(max_bytes=self.max_disk_bytes, max_age=self.max_age, now=now)
        self.index.evict(max_bytes=self.max_disk_bytes, max_age=self.max_age)
        referenced = self.index.referenced_hashes()
        removed = [e.digest for e in self.blobs.entries() if e.digest not in referenced]
        for blob_hash in removed:
            self.blobs.delete(blob_hash)
        return removed


KeyFn = Callable[[str], str]
