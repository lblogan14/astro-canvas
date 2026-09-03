"""Turn a decorated Python function into a ``NodeSpec`` plus a pydantic params model."""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
import types
import typing
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, Optional, Union, get_args, get_origin

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, create_model

from astro_canvas.sdk.context import NodeContext
from astro_canvas.sdk.docstrings import DocInfo, parse_docstring
from astro_canvas.sdk.errors import NodeDefinitionError
from astro_canvas.sdk.params import Param
from astro_canvas.sdk.porttype import JSON_TYPE, SCALAR_TYPE_IDS, PortType, is_port_type
from astro_canvas.sdk.spec import Cost, NodeSpec, ParamSpec, PortSpec

NODE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")
_NONE_TYPE = type(None)


@dataclass(frozen=True)
class NodeMeta:
    """Arguments of ``@node`` needed by introspection."""

    id: str
    name: str
    category: str
    version: str = "1.0.0"
    cost: Cost = "cheap"
    icon: str | None = None
    preview: str | None = None
    editor: str | None = None
    outputs: tuple[str, ...] | None = None
    fingerprint: bool = False
    expand: bool = False
    lazy: tuple[str, ...] = ()
    deprecated: bool = False
    experimental: bool = False


@dataclass
class Annotation:
    """Normalized view of one parameter annotation."""

    base: Any
    optional: bool = False
    param: Param | None = None
    unit: str | None = None
    quantity: bool = False
    port: type[PortType] | None = None
    context: bool = False
    extras: tuple[Any, ...] = ()


@dataclass
class NodeShape:
    """Introspection result consumed by ``NodeDef``."""

    spec: NodeSpec
    params_model: type[BaseModel]
    input_names: list[str] = field(default_factory=list)
    param_names: list[str] = field(default_factory=list)
    context_param: str | None = None
    quantity_units: dict[str, str] = field(default_factory=dict)
    output_names: list[str] = field(default_factory=list)
    output_kind: Literal["none", "single", "tuple", "named"] = "none"


def _is_unit(obj: Any) -> bool:
    return type(obj).__module__.startswith("astropy.units")


def _is_quantity_class(obj: Any) -> bool:
    return (
        isinstance(obj, type)
        and obj.__module__.startswith("astropy.units")
        and obj.__name__ == "Quantity"
    )


def _unit_string(unit: Any) -> str:
    return str(unit.to_string())


def analyze_annotation(annotation: Any) -> Annotation:
    """Unwrap ``Annotated``/``Optional`` and classify the annotation."""
    info = Annotation(base=annotation)
    base = annotation
    for _ in range(4):
        if get_origin(base) is Annotated:
            args = get_args(base)
            base = args[0]
            for meta in args[1:]:
                if isinstance(meta, Param):
                    info.param = meta
                elif _is_unit(meta):
                    info.unit = _unit_string(meta)
                else:
                    info.extras += (meta,)
        elif get_origin(base) in (Union, types.UnionType):
            members = [a for a in get_args(base) if a is not _NONE_TYPE]
            if len(members) != len(get_args(base)):
                info.optional = True
            if len(members) == 1:
                base = members[0]
            else:
                base = Union[tuple(members)]  # noqa: UP007 - runtime construction
                break
        else:
            break
    if _is_quantity_class(base):
        info.quantity = True
        base = float
    info.base = base
    if base is NodeContext:
        info.context = True
    elif is_port_type(base):
        info.port = base
    if info.param is not None and info.param.unit is not None:
        info.unit = info.param.unit
    return info


def _link_type(base: Any) -> str:
    return SCALAR_TYPE_IDS.get(base, JSON_TYPE) if isinstance(base, type) else JSON_TYPE


def _param_annotation(name: str, info: Annotation, description: str) -> Any:
    """Rebuild a pydantic-ready annotation carrying constraints and ``x-`` extras."""
    p = info.param or Param()
    extra: dict[str, Any] = {}
    if info.unit:
        extra["x-unit"] = info.unit
    if p.widget:
        extra["x-widget"] = p.widget
    if p.step is not None:
        extra["x-step"] = p.step
    if p.advanced:
        extra["x-advanced"] = True
    inner: Any = info.base
    inner_meta: list[Any] = list(info.extras)
    if p.min is not None or p.max is not None:
        inner_meta.append(Field(ge=p.min, le=p.max))
    if p.choices is not None:
        choices = tuple(p.choices)
        extra["enum"] = list(choices)

        def _check(value: Any, _choices: tuple[Any, ...] = choices) -> Any:
            if value not in _choices:
                raise ValueError(f"{name} must be one of {list(_choices)}, got {value!r}")
            return value

        inner_meta.append(AfterValidator(_check))
    if inner_meta:
        inner = Annotated[tuple([inner, *inner_meta])]
    if info.optional:
        inner = Optional[inner]  # noqa: UP045 - runtime construction
    outer = Field(
        title=p.label or name.replace("_", " ").capitalize(),
        description=p.help or description or None,
        json_schema_extra=extra or None,
    )
    return Annotated[tuple([inner, outer])]


def _self_contained(prop: dict[str, Any], defs: dict[str, Any] | None) -> dict[str, Any]:
    """Attach the model's ``$defs`` to a property schema that references them."""
    if defs and "$ref" in json.dumps(prop):
        return {**prop, "$defs": defs}
    return prop


def _output_type(annotation: Any, where: str) -> str:
    info = analyze_annotation(annotation)
    if info.port is not None:
        return info.port.type_id()
    if info.base in SCALAR_TYPE_IDS:
        return SCALAR_TYPE_IDS[info.base]
    if info.base in (dict, list, Any) or get_origin(info.base) in (dict, list):
        return JSON_TYPE
    raise NodeDefinitionError(
        f"{where}: return annotation {annotation!r} is not a port type or JSON-native type"
    )


def _analyze_outputs(
    return_annotation: Any, meta: NodeMeta, doc: DocInfo, where: str
) -> tuple[list[PortSpec], list[str], Literal["none", "single", "tuple", "named"]]:
    if return_annotation is inspect.Signature.empty:
        raise NodeDefinitionError(f"{where}: a return annotation is required (use -> None)")
    if return_annotation is None or return_annotation is _NONE_TYPE:
        if meta.outputs:
            raise NodeDefinitionError(f"{where}: outputs= given but the node returns None")
        return [], [], "none"
    kind: Literal["single", "tuple", "named"]
    items: list[tuple[str, Any]]
    if get_origin(return_annotation) is tuple:
        args = list(get_args(return_annotation))
        if not args or Ellipsis in args:
            raise NodeDefinitionError(f"{where}: tuple outputs need fixed element types")
        names = list(meta.outputs) if meta.outputs else [f"out{i}" for i in range(len(args))]
        if len(names) != len(args):
            raise NodeDefinitionError(f"{where}: outputs= names {names} do not match {len(args)}")
        items, kind = list(zip(names, args, strict=True)), "tuple"
    elif (
        isinstance(return_annotation, type)
        and issubclass(return_annotation, tuple)
        and hasattr(return_annotation, "_fields")
    ):
        hints = typing.get_type_hints(return_annotation, include_extras=True)
        items = [(f, hints[f]) for f in return_annotation._fields]
        kind = "named"
    elif dataclasses.is_dataclass(return_annotation) and isinstance(return_annotation, type):
        hints = typing.get_type_hints(return_annotation, include_extras=True)
        items = [(f.name, hints[f.name]) for f in dataclasses.fields(return_annotation)]
        kind = "named"
    else:
        if meta.outputs and len(meta.outputs) != 1:
            raise NodeDefinitionError(f"{where}: single output but {len(meta.outputs)} names given")
        items, kind = [(meta.outputs[0] if meta.outputs else "out", return_annotation)], "single"
    descriptions = doc.returns if len(doc.returns) == len(items) else []
    outputs = [
        PortSpec(
            name=name,
            type=_output_type(ann, f"{where}.{name}"),
            description=descriptions[i] if descriptions else "",
        )
        for i, (name, ann) in enumerate(items)
    ]
    return outputs, [name for name, _ in items], kind


def _check_meta(meta: NodeMeta, where: str) -> None:
    if not NODE_ID_PATTERN.match(meta.id):
        raise NodeDefinitionError(f"{where}: invalid node id {meta.id!r} (e.g. 'core.spec.crop')")
    if not VERSION_PATTERN.match(meta.version):
        raise NodeDefinitionError(f"{where}: version {meta.version!r} must be semver (1.0.0)")
    if meta.cost not in ("cheap", "expensive", "auto"):
        raise NodeDefinitionError(f"{where}: cost must be cheap|expensive|auto, got {meta.cost!r}")
    if not meta.name.strip() or not meta.category.strip():
        raise NodeDefinitionError(f"{where}: name and category must be non-empty")


def _link_type_of(info: Annotation) -> str:
    base = info.base
    if get_origin(base) is Literal:
        kinds = {type(a) for a in get_args(base)}
        return SCALAR_TYPE_IDS.get(kinds.pop(), JSON_TYPE) if len(kinds) == 1 else JSON_TYPE
    return _link_type(base)


def build_shape(func: Any, meta: NodeMeta) -> NodeShape:
    """Introspect ``func`` and produce the ``NodeShape`` behind a ``NodeDef``.

    Raises:
        NodeDefinitionError: for anything the schema cannot express (missing annotations,
            ``*args``, non-JSON params, unknown return types, bad ids).
    """
    where = f"@node({meta.id!r}) on {getattr(func, '__qualname__', func)!s}"
    _check_meta(meta, where)
    if not callable(func):
        raise NodeDefinitionError(f"{where}: not callable")
    try:
        signature = inspect.signature(func)
        hints = typing.get_type_hints(func, include_extras=True)
    except (TypeError, NameError, ValueError) as exc:
        raise NodeDefinitionError(f"{where}: cannot resolve annotations: {exc}") from exc
    doc = parse_docstring(inspect.getdoc(func))

    inputs: list[PortSpec] = []
    fields: dict[str, Any] = {}
    infos: dict[str, Annotation] = {}
    shape_inputs: list[str] = []
    shape_params: list[str] = []
    context_param: str | None = None
    quantity_units: dict[str, str] = {}

    for name, parameter in signature.parameters.items():
        if parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            raise NodeDefinitionError(f"{where}: *args/**kwargs are not supported ({name})")
        if name not in hints:
            raise NodeDefinitionError(f"{where}: parameter {name!r} needs a type annotation")
        info = analyze_annotation(hints[name])
        has_default = parameter.default is not inspect.Parameter.empty
        if info.context:
            context_param = name
            continue
        if info.port is not None:
            inputs.append(
                PortSpec(
                    name=name,
                    type=info.port.type_id(),
                    description=doc.params.get(name, ""),
                    required=not (info.optional or has_default),
                    lazy=name in meta.lazy,
                )
            )
            shape_inputs.append(name)
            continue
        default: Any = parameter.default if has_default else ...
        if info.quantity:
            if info.unit is None:
                raise NodeDefinitionError(f"{where}: Quantity param {name!r} needs a unit")
            quantity_units[name] = info.unit
            if has_default and hasattr(default, "to_value"):
                default = float(default.to_value(info.unit))
        fields[name] = (_param_annotation(name, info, doc.params.get(name, "")), default)
        infos[name] = info
        shape_params.append(name)

    for lazy in meta.lazy:
        if lazy not in shape_inputs:
            raise NodeDefinitionError(f"{where}: lazy={lazy!r} is not an input port")

    model_name = "".join(part.capitalize() for part in meta.id.split(".")) + "Params"
    try:
        params_model = create_model(
            model_name,
            __config__=ConfigDict(arbitrary_types_allowed=True, extra="forbid"),
            **fields,
        )
        schema = params_model.model_json_schema()
    except Exception as exc:
        raise NodeDefinitionError(f"{where}: unsupported parameter annotation: {exc}") from exc

    defs = schema.get("$defs")
    properties: dict[str, Any] = schema.get("properties", {})
    required = set(schema.get("required", []))
    params: list[ParamSpec] = []
    for name in shape_params:
        info = infos[name]
        p = info.param or Param()
        prop = _self_contained(properties[name], defs)
        params.append(
            ParamSpec(
                name=name,
                label=str(prop.get("title", name)),
                description=str(prop.get("description", "")),
                json_schema=prop,
                required=name in required,
                default=prop.get("default"),
                widget=p.widget,
                unit=info.unit,
                step=p.step,
                advanced=p.advanced,
                linkable=True,
                link_type=_link_type_of(info),
            )
        )

    return_annotation = hints.get("return", signature.return_annotation)
    outputs, output_names, output_kind = _analyze_outputs(return_annotation, meta, doc, where)
    spec = NodeSpec(
        id=meta.id,
        name=meta.name,
        category=meta.category,
        version=meta.version,
        cost=meta.cost,
        inputs=inputs,
        params=params,
        outputs=outputs,
        description=doc.description,
        param_docs=doc.params,
        icon=meta.icon,
        preview=meta.preview,
        editor=meta.editor,
        module=getattr(func, "__module__", "") or "",
        deprecated=meta.deprecated,
        experimental=meta.experimental,
        expand=meta.expand,
        fingerprint=meta.fingerprint,
        is_async=inspect.iscoroutinefunction(func),
    )
    return NodeShape(
        spec=spec,
        params_model=params_model,
        input_names=shape_inputs,
        param_names=shape_params,
        context_param=context_param,
        quantity_units=quantity_units,
        output_names=output_names,
        output_kind=output_kind,
    )
