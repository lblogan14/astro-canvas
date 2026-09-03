"""Persistence of runs, node runs and per-node cost statistics (used by the scheduler)."""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astro_canvas.store.models import NodeRun, NodeStat, Run, utcnow


@dataclass(frozen=True)
class NodeRunRecord:
    node_id: str
    key: str
    status: str
    elapsed_ms: float | None = None
    cache_hit: bool = False
    error: str | None = None


class RunStore:
    """``runs`` / ``node_runs`` tables."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._lock = threading.Lock()

    def begin(self, run_id: str, workflow_id: str, targets: Sequence[str] | None) -> None:
        with self._lock, self._sessions() as session:
            session.add(
                Run(
                    id=run_id,
                    workflow_id=workflow_id,
                    status="running",
                    targets_json=json.dumps(list(targets)) if targets is not None else None,
                )
            )
            session.commit()

    def record(self, run_id: str, record: NodeRunRecord) -> None:
        with self._lock, self._sessions() as session:
            session.add(
                NodeRun(
                    run_id=run_id,
                    node_id=record.node_id,
                    key=record.key,
                    status=record.status,
                    elapsed_ms=record.elapsed_ms,
                    cache_hit=record.cache_hit,
                    error=record.error,
                )
            )
            session.commit()

    def finish(self, run_id: str, status: str) -> None:
        with self._lock, self._sessions() as session:
            run = session.get(Run, run_id)
            if run is not None:
                run.status = status
                run.finished = utcnow()
                session.commit()

    def get(self, run_id: str) -> Run | None:
        with self._lock, self._sessions() as session:
            return session.get(Run, run_id)

    def node_runs(self, run_id: str) -> list[NodeRun]:
        with self._lock, self._sessions() as session:
            return list(
                session.scalars(
                    select(NodeRun).where(NodeRun.run_id == run_id).order_by(NodeRun.id)
                ).all()
            )

    def list(self, workflow_id: str | None = None, limit: int = 50) -> list[Run]:
        with self._lock, self._sessions() as session:
            stmt = select(Run).order_by(Run.started.desc()).limit(limit)
            if workflow_id is not None:
                stmt = stmt.where(Run.workflow_id == workflow_id)
            return list(session.scalars(stmt).all())


class NodeStatStore:
    """``node_stats``: moving-average runtime per node instance for ``auto`` cost promotion."""

    def __init__(
        self, sessions: sessionmaker[Session], workflow_id: str, alpha: float = 0.5
    ) -> None:
        self._sessions = sessions
        self.workflow_id = workflow_id
        self.alpha = alpha
        self._lock = threading.Lock()

    def average_ms(self, node_id: str) -> float | None:
        with self._lock, self._sessions() as session:
            stat = session.get(NodeStat, (self.workflow_id, node_id))
            return stat.avg_ms if stat is not None and stat.n_runs else None

    def record(self, node_id: str, elapsed_ms: float, cost_class: str) -> float:
        """Blend ``elapsed_ms`` into the moving average; returns the new average."""
        with self._lock, self._sessions() as session:
            stat = session.get(NodeStat, (self.workflow_id, node_id))
            if stat is None:
                stat = NodeStat(
                    workflow_id=self.workflow_id, node_id=node_id, avg_ms=elapsed_ms, n_runs=0
                )
                session.add(stat)
            else:
                stat.avg_ms = (1 - self.alpha) * stat.avg_ms + self.alpha * elapsed_ms
            stat.n_runs += 1
            stat.cost_class = cost_class
            session.commit()
            return stat.avg_ms


class MemoryStats:
    """In-memory stand-in for ``NodeStatStore`` (tests, headless runs)."""

    def __init__(self, alpha: float = 0.5) -> None:
        self.alpha = alpha
        self.values: dict[str, tuple[float, int]] = {}

    def average_ms(self, node_id: str) -> float | None:
        item = self.values.get(node_id)
        return item[0] if item else None

    def record(self, node_id: str, elapsed_ms: float, cost_class: str) -> float:
        avg, n = self.values.get(node_id, (elapsed_ms, 0))
        avg = elapsed_ms if n == 0 else (1 - self.alpha) * avg + self.alpha * elapsed_ms
        self.values[node_id] = (avg, n + 1)
        return avg
