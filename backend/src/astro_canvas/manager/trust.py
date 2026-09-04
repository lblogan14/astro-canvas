"""The trust gate for code nodes (design 7.2, 11).

A shared workflow can carry arbitrary Python. Rather than refuse code nodes or run them blind,
every snippet is addressed by the hash of its source and the user decides once per hash: a
workflow whose snippets are not all trusted opens **quarantined** -- the code nodes report a
``quarantined`` issue and never execute -- and editing a trusted snippet changes its hash, so the
gate closes again by construction.

Locally authored code is trusted on the spot (``trust_local``); only documents that arrived from
outside -- a bundle import -- start quarantined.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from astro_canvas.engine.cache import digest
from astro_canvas.engine.graph import WorkflowDoc
from astro_canvas.store.models import Trust

CODE_NODE_TYPES: frozenset[str] = frozenset({"core.code.python"})
"""Node types whose ``source`` param is executed as Python and therefore needs a decision."""

SOURCE_PARAM = "source"
Decision = Literal["trusted", "blocked"]


def snippet_hash(source: str) -> str:
    """Content hash of one snippet, normalised so line endings alone do not change it."""
    normalized = "\n".join(str(source).replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    return digest(normalized.encode("utf-8"))


class CodeSnippet(BaseModel):
    """One code node found in a document."""

    node: str
    type: str
    title: str = ""
    hash: str
    source: str = ""
    lines: int = 0
    decision: Decision | None = None

    @property
    def trusted(self) -> bool:
        return self.decision == "trusted"


class TrustRecord(BaseModel):
    """A stored decision (``GET /api/manager/trust``)."""

    hash: str
    decision: Decision
    decided: str


def code_snippets(doc: WorkflowDoc, *, include_source: bool = True) -> list[CodeSnippet]:
    """Every code node in ``doc``, including the ones inside subgraph bodies.

    Subgraph nodes are reported with their fully-qualified ``<instance path>`` shape
    (``<subgraph id>/<node>``) so a decision names exactly one snippet.
    """
    found: list[CodeSnippet] = []
    containers: list[tuple[str, dict[str, object]]] = [("", dict(doc.nodes))]
    for sg_id, sg in doc.subgraphs.items():
        containers.append((f"{sg_id}/", dict(sg.nodes)))
    for prefix, nodes in containers:
        for node_id, node in nodes.items():
            node_type = getattr(node, "type", "")
            if node_type not in CODE_NODE_TYPES:
                continue
            source = str(getattr(node, "params", {}).get(SOURCE_PARAM, "") or "")
            found.append(
                CodeSnippet(
                    node=f"{prefix}{node_id}",
                    type=node_type,
                    title=getattr(node, "title", None) or node_id,
                    hash=snippet_hash(source),
                    source=source if include_source else "",
                    lines=len(source.splitlines()),
                )
            )
    return sorted(found, key=lambda s: s.node)


class TrustStore:
    """Decisions in the workspace's ``trust`` table, keyed by snippet hash."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def decisions(self, hashes: Iterable[str] | None = None) -> dict[str, Decision]:
        wanted = set(hashes) if hashes is not None else None
        with self.sessions() as session:
            rows = session.scalars(select(Trust)).all()
        return {
            row.hash: row.decision  # type: ignore[misc]
            for row in rows
            if wanted is None or row.hash in wanted
        }

    def records(self) -> list[TrustRecord]:
        with self.sessions() as session:
            rows = session.scalars(select(Trust).order_by(Trust.decided.desc())).all()
            return [
                TrustRecord(hash=r.hash, decision=r.decision, decided=r.decided.isoformat())
                for r in rows
            ]

    def set(self, snippet: str, decision: Decision) -> TrustRecord:
        """Record a decision for one snippet hash (idempotent)."""
        with self.sessions() as session:
            row = session.get(Trust, snippet)
            if row is None:
                row = Trust(hash=snippet, decision=decision)
                session.add(row)
            else:
                row.decision = decision
            session.commit()
            return TrustRecord(hash=row.hash, decision=decision, decided=row.decided.isoformat())

    def forget(self, snippet: str) -> bool:
        with self.sessions() as session:
            row = session.get(Trust, snippet)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def trust_local(self, doc: WorkflowDoc) -> list[str]:
        """Trust every snippet in a locally authored document; returns the new hashes.

        Called on save: a snippet the user typed here needs no dialog. A document that arrived
        from a bundle is marked ``meta.quarantine`` and is skipped, so importing does not launder
        someone else's code into the trusted set.
        """
        if doc.meta.get("quarantine"):
            return []
        known = self.decisions()
        added: list[str] = []
        for snippet in code_snippets(doc, include_source=False):
            if snippet.hash not in known:
                self.set(snippet.hash, "trusted")
                added.append(snippet.hash)
        return added

    def on_workflow_saved(self, doc: WorkflowDoc) -> None:
        """Trust hook for every save (``EngineRuntime.before_save``).

        Code the user wrote here is trusted on the spot; an imported document stays quarantined
        until every one of its snippets has a decision, and then loses the flag for good.
        """
        if doc.meta.get("quarantine"):
            if not self.quarantined(doc):
                doc.meta = {k: v for k, v in doc.meta.items() if k != "quarantine"}
            return
        self.trust_local(doc)

    def quarantined(self, doc: WorkflowDoc) -> dict[str, str]:
        """``{node id: reason}`` for the code nodes of ``doc`` that may not run yet."""
        snippets = code_snippets(doc, include_source=False)
        if not snippets:
            return {}
        known = self.decisions({s.hash for s in snippets})
        out: dict[str, str] = {}
        for snippet in snippets:
            decision = known.get(snippet.hash)
            if decision == "trusted":
                continue
            out[snippet.node] = (
                "this code snippet was blocked"
                if decision == "blocked"
                else "review and trust this code snippet before it can run"
            )
        return out

    def review(self, doc: WorkflowDoc) -> list[CodeSnippet]:
        """The snippets of ``doc`` with their current decisions, for the trust dialog."""
        snippets = code_snippets(doc)
        known = self.decisions({s.hash for s in snippets})
        return [s.model_copy(update={"decision": known.get(s.hash)}) for s in snippets]


class TrustReview(BaseModel):
    """``GET /api/workflows/{id}/trust``: what the quarantine banner and dialog render."""

    workflow_id: str
    quarantined: bool = False
    snippets: list[CodeSnippet] = Field(default_factory=list)
    blocked_nodes: list[str] = Field(default_factory=list)


__all__ = [
    "CODE_NODE_TYPES",
    "CodeSnippet",
    "Decision",
    "TrustRecord",
    "TrustReview",
    "TrustStore",
    "code_snippets",
    "snippet_hash",
]
