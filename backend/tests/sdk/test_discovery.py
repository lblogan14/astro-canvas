"""Registry behaviour and entry-point discovery with broken packs."""

from __future__ import annotations

import pytest

from astro_canvas.sdk import (
    DiscoveryResult,
    DuplicateNodeError,
    NodeRegistry,
    UnknownNodeError,
    UnknownTypeError,
    discover,
    node,
)
from tests.conftest import fixture_entry_point


def test_discover_installed_packs(discovery: DiscoveryResult) -> None:
    names = {p.name: p for p in discovery.packs}
    assert set(names) >= {"core", "rbcodes"}
    assert names["core"].error is None
    assert names["core"].node_count == 27
    assert names["core"].type_count == 20
    assert names["core"].distribution == "astro-canvas-core"
    assert names["core"].version == "0.1.0a0"
    assert names["rbcodes"].node_count == 0 and names["rbcodes"].error is None
    assert discovery.registry.validate_unique() == []
    assert discovery.errors == []


def test_broken_pack_is_recorded_and_others_load() -> None:
    eps = [fixture_entry_point(n) for n in ("broken", "good", "partial")]
    result = discover(eps)

    by_name = {p.name: p for p in result.packs}
    assert [p.name for p in result.packs] == ["broken", "good", "partial"]
    broken = by_name["broken"]
    assert broken.error is not None
    assert "ImportError" in broken.error.error
    assert "definitely_not_installed" in broken.error.error
    assert "Traceback" in broken.error.traceback
    assert broken.node_count == 0 and broken.version == "unknown"

    good = by_name["good"]
    assert good.error is None and good.node_count == 1 and good.type_count == 1
    assert result.registry.spec("good.text.token").pack == "good"
    assert result.registry.get("good.text.token").spec.pack is None
    assert "fixture.Token" in result.registry.types

    # The partial pack added a node before failing: it must be rolled back.
    partial = by_name["partial"]
    assert partial.error is not None and "RuntimeError" in partial.error.error
    assert "partial.math.one" not in result.registry
    assert result.registry.ids() == ["good.text.token"]
    assert [e.pack for e in result.errors] == ["broken", "partial"]


def test_non_callable_entry_point_is_an_error() -> None:
    from importlib.metadata import EntryPoint

    ep = EntryPoint(name="weird", value="pack_good:__doc__", group="astro_canvas.nodes")
    result = discover([ep])
    assert result.packs[0].error is not None
    assert "not callable" in result.packs[0].error.error


def test_registry_add_get_list_by_category() -> None:
    @node(id="t.a.one", name="One", category="B/Second")
    def one() -> float:
        """One."""
        return 1.0

    @node(id="t.a.two", name="Two", category="A/First")
    def two() -> float:
        """Two."""
        return 2.0

    reg = NodeRegistry()
    reg.add(one, pack="t")
    reg.add(two)
    assert len(reg) == 2 and "t.a.one" in reg and "nope" not in reg
    assert reg.spec("t.a.one").pack == "t" and reg.spec("t.a.two").pack is None
    assert [s.id for s in reg.list()] == ["t.a.one", "t.a.two"]
    assert list(reg.by_category()) == ["A/First", "B/Second"]
    with pytest.raises(DuplicateNodeError):
        reg.add(one)
    with pytest.raises(UnknownNodeError):
        reg.get("missing")
    with pytest.raises(UnknownTypeError):
        reg.types.get("astro.Nope")
    with pytest.raises(TypeError):
        reg.add(lambda: None)  # type: ignore[arg-type]
    # Ports referencing unregistered types are reported, not fatal.
    assert reg.validate_unique() == [
        "t.a.one: port 'out' uses unknown type 'astro.Float'",
        "t.a.two: port 'out' uses unknown type 'astro.Float'",
    ]
    assert reg.remove_pack("t") == 1 and len(reg) == 1


def test_add_module_is_idempotent_for_types() -> None:
    import pack_good

    reg = NodeRegistry()
    assert reg.add_module(pack_good, pack="good") == 1
    assert reg.add_module(pack_good, pack="good") == 0
    assert len(reg.types) == 1
    assert reg.types.spec("fixture.Token").color == "#123456"
    assert reg.for_pack("good").types is reg.types
