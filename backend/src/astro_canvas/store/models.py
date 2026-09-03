"""SQLAlchemy models for ``<workspace>/.astro-canvas/app.db`` (design 6.6)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Declarative base for every table."""


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), default="Untitled")
    doc_json: Mapped[str] = mapped_column(Text)
    created: Mapped[datetime] = mapped_column(default=utcnow)
    modified: Mapped[datetime] = mapped_column(default=utcnow)
    hash: Mapped[str] = mapped_column(String(64), default="")


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), index=True
    )
    doc_json: Mapped[str] = mapped_column(Text)
    created: Mapped[datetime] = mapped_column(default=utcnow)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(64), index=True)
    started: Mapped[datetime] = mapped_column(default=utcnow)
    finished: Mapped[datetime | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="running")
    targets_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class NodeRun(Base):
    __tablename__ = "node_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(255))
    key: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(16))
    elapsed_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Output(Base):
    __tablename__ = "outputs"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    port: Mapped[str] = mapped_column(String(255), primary_key=True)
    node_type: Mapped[str] = mapped_column(String(255))
    type_id: Mapped[str] = mapped_column(String(255))
    blob_hash: Mapped[str] = mapped_column(String(64), index=True)
    blob_manifest: Mapped[str] = mapped_column(Text, default="{}")
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    created: Mapped[datetime] = mapped_column(default=utcnow)
    last_used: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class FileRecord(Base):
    """Cached content hash of a workspace file, keyed by its relative path and mtime (phase 04)."""

    __tablename__ = "files"

    path: Mapped[str] = mapped_column(String(1024), primary_key=True)
    mtime_ns: Mapped[int] = mapped_column(Integer)
    size: Mapped[int] = mapped_column(Integer)
    blake3: Mapped[str] = mapped_column(String(64))
    hashed: Mapped[datetime] = mapped_column(default=utcnow)


class NodeStat(Base):
    """Per node instance runtime statistics used for ``auto`` cost promotion."""

    __tablename__ = "node_stats"

    workflow_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    avg_ms: Mapped[float] = mapped_column(Float, default=0.0)
    n_runs: Mapped[int] = mapped_column(Integer, default=0)
    cost_class: Mapped[str] = mapped_column(String(16), default="cheap")


class Pack(Base):
    __tablename__ = "packs"

    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    version: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    installed: Mapped[datetime] = mapped_column(default=utcnow)


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created: Mapped[datetime] = mapped_column(default=utcnow)
    lock_json: Mapped[str] = mapped_column(Text)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Trust(Base):
    __tablename__ = "trust"

    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision: Mapped[str] = mapped_column(String(16))
    decided: Mapped[datetime] = mapped_column(default=utcnow)


Index("ix_node_runs_run_node", NodeRun.run_id, NodeRun.node_id)
