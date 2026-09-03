"""``@node`` and ``NodeDef``: a Python function with a schema attached."""

from __future__ import annotations

import functools
from collections.abc import Callable, Hashable, Mapping, Sequence
from typing import Any

from astro_canvas.sdk.context import NodeContext
from astro_canvas.sdk.introspect import NodeMeta, build_shape
from astro_canvas.sdk.spec import Cost, NodeSpec


class NodeDef:
    """A registered node: the original function plus its ``NodeSpec`` and params model.

    Instances stay callable exactly like the wrapped function (``node(spec, vmin=-100)``) so
    packs can unit-test nodes directly. ``call`` is the engine entry point: it validates params,
    converts ``Quantity`` params, injects inputs and the ``NodeContext``.
    """

    def __init__(
        self,
        func: Callable[..., Any],
        meta: NodeMeta,
        fingerprint: Callable[..., Hashable] | None = None,
    ) -> None:
        shape = build_shape(func, meta)
        self.func = func
        self.meta = meta
        self.spec: NodeSpec = shape.spec
        self.params_model = shape.params_model
        self.input_names: list[str] = shape.input_names
        self.param_names: list[str] = shape.param_names
        self.output_names: list[str] = shape.output_names
        self.output_kind = shape.output_kind
        self.context_param = shape.context_param
        self.quantity_units: dict[str, str] = shape.quantity_units
        self.fingerprint = fingerprint
        functools.update_wrapper(self, func)

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def cost(self) -> Cost:
        return self.spec.cost

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.func(*args, **kwargs)

    def __repr__(self) -> str:
        return f"<node {self.spec.id} v{self.spec.version} ({self.spec.cost})>"

    def validate_params(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and coerce ``params`` (JSON values) into Python call arguments.

        Raises ``pydantic.ValidationError`` on bad or unknown parameters. Float params declared
        as ``Quantity[unit]`` come back as ``astropy.units.Quantity``.
        """
        model = self.params_model.model_validate(dict(params))
        out: dict[str, Any] = {name: getattr(model, name) for name in self.param_names}
        for name, unit in self.quantity_units.items():
            if out.get(name) is not None:
                out[name] = _to_quantity(out[name], unit)
        return out

    def call(
        self,
        inputs: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        ctx: NodeContext | None = None,
    ) -> Any:
        """Invoke the node with validated params, port values, and an optional context."""
        kwargs = self.validate_params(params or {})
        given = dict(inputs or {})
        unknown = set(given) - set(self.input_names)
        if unknown:
            raise TypeError(f"{self.spec.id}: unknown inputs {sorted(unknown)}")
        kwargs.update(given)
        if self.context_param is not None:
            kwargs[self.context_param] = ctx
        return self.func(**kwargs)


def _to_quantity(value: Any, unit: str) -> Any:
    import astropy.units as u  # noqa: PLC0415 - optional dependency, only for Quantity params

    return u.Quantity(value, u.Unit(unit))


def node(
    *,
    id: str,
    name: str,
    category: str,
    cost: Cost = "cheap",
    version: str = "1.0.0",
    icon: str | None = None,
    preview: str | None = None,
    editor: str | None = None,
    outputs: Sequence[str] | None = None,
    fingerprint: Callable[..., Hashable] | None = None,
    expand: bool = False,
    lazy: Sequence[str] = (),
    deprecated: bool = False,
    experimental: bool = False,
) -> Callable[[Callable[..., Any]], NodeDef]:
    """Declare a node. See ``astro_canvas.sdk`` for the parameter/port rules.

    Args:
        id: Dotted, lowercase, unique across packs (``core.spec.crop``).
        name: Display name.
        category: Slash-separated menu path (``Spectra/Transform``).
        cost: ``cheap`` runs reactively; ``expensive`` waits for Run; ``auto`` is measured.
        version: Semantic version of the node contract.
        icon: Icon id for the frontend.
        preview: Frontend preview renderer id.
        editor: Frontend expandable editor id.
        outputs: Names for tuple outputs (default ``out0``, ``out1``, ...) or one single output.
        fingerprint: Callable returning a hashable that changes when external state changes.
        expand: The node returns a graph to expand into sub-nodes (batch runner).
        lazy: Input ports resolved on demand through ``ctx.needs(port)``.
        deprecated: Hide from the menu, keep loadable.
        experimental: Flag in the UI.
    """
    meta = NodeMeta(
        id=id,
        name=name,
        category=category,
        version=version,
        cost=cost,
        icon=icon,
        preview=preview,
        editor=editor,
        outputs=tuple(outputs) if outputs is not None else None,
        fingerprint=fingerprint is not None,
        expand=expand,
        lazy=tuple(lazy),
        deprecated=deprecated,
        experimental=experimental,
    )

    def decorate(func: Callable[..., Any]) -> NodeDef:
        return NodeDef(func, meta, fingerprint)

    return decorate


def validate_call(node: NodeDef, params: Mapping[str, Any]) -> dict[str, Any]:
    """Validate ``params`` against ``node``'s schema; returns Python-typed arguments."""
    return node.validate_params(params)
