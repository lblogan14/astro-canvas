"""``Expansion``: what a ``@node(expand=True)`` function returns at run time.

An expanding node declares its *external* outputs through its return annotation like any other
node, but instead of computing them it returns an ``Expansion``: a small graph of sub-nodes that
the engine executes in its place. Sub-node inputs may reference the parent's own input ports via
the pseudo node id ``Expansion.PARENT`` (``"$in"``). Sub-node results are cached under the
parent's cache key, so re-running the parent with unchanged inputs is free.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExpandNode(BaseModel):
    """One sub-node of an expansion."""

    model_config = ConfigDict(frozen=True)

    type: str = Field(description="Registered node type id.")
    params: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, tuple[str, str]] = Field(
        default_factory=dict,
        description="Input port -> (sub-node id or ``$in``, output/input port name).",
    )


class Expansion(BaseModel):
    """A sub-graph returned by an expanding node."""

    model_config = ConfigDict(frozen=True)

    PARENT: ClassVar[str] = "$in"

    nodes: dict[str, ExpandNode]
    outputs: dict[str, tuple[str, str]] = Field(
        description="Parent output port -> (sub-node id, sub-node output port)."
    )

    @model_validator(mode="after")
    def _references_resolve(self) -> Expansion:
        for sub_id, sub in self.nodes.items():
            if sub_id == self.PARENT or "/" in sub_id:
                raise ValueError(f"invalid sub-node id {sub_id!r}")
            for port, (src, _) in sub.inputs.items():
                if src != self.PARENT and src not in self.nodes:
                    raise ValueError(f"{sub_id}.{port} references unknown sub-node {src!r}")
        for port, (src, _) in self.outputs.items():
            if src not in self.nodes:
                raise ValueError(f"output {port!r} references unknown sub-node {src!r}")
        return self
