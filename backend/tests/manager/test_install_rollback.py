"""Plan, install, hot-register, snapshot and roll back, against the scripted uv (see conftest)."""

from __future__ import annotations

import importlib.metadata

import pytest
from sqlalchemy.orm import Session, sessionmaker

from astro_canvas.manager import packs as packs_module
from astro_canvas.manager.packs import ManagerError, PackManager
from astro_canvas.manager.plan import SourceError
from astro_canvas.manager.settings import ManagerSettingsUpdate
from tests.conftest import fixture_entry_point
from tests.manager.conftest import FakeEnvironment


def _entry_points_after_install(
    monkeypatch: pytest.MonkeyPatch, fake_uv: FakeEnvironment, pack: str
) -> None:
    """A pack's entry point appears only once its distribution is in the environment."""
    entry = fixture_entry_point(pack)
    monkeypatch.setattr(
        packs_module,
        "pack_entry_points",
        lambda: [entry] if "astro-canvas-demo" in fake_uv.installed() else [],
    )


@pytest.fixture(autouse=True)
def _pin_the_app(fake_uv: FakeEnvironment) -> None:
    """Seed the fake environment with the app's real versions, so the guard pins are satisfied."""
    installed = dict(fake_uv.installed())
    for name in ("astro-canvas", "astro-canvas-sdk"):
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:  # pragma: no cover - dev checkout
            continue
    fake_uv.set_installed(installed)


def test_a_clean_plan_lists_only_the_new_package(manager: PackManager) -> None:
    plan = manager.resolve("astro-canvas-demo")
    assert plan.ok
    assert [(c.name, c.action, c.to_version) for c in plan.changes] == [
        ("astro-canvas-demo", "add", "0.2.0")
    ]


def test_a_conflicting_pin_blocks_the_install_with_the_reason(manager: PackManager) -> None:
    """The pack pins numpy 1.19.5; the app's own pins make that unsatisfiable (design 9)."""
    plan = manager.resolve("astro-canvas-bad")
    assert not plan.ok
    assert plan.changes == []
    assert any("numpy" in line for line in plan.conflicts)
    assert "unsatisfiable" in plan.message
    with pytest.raises(ManagerError, match="unsatisfiable"):
        manager.install("astro-canvas-bad")


def test_a_blocked_plan_leaves_the_environment_untouched(
    manager: PackManager, fake_uv: FakeEnvironment
) -> None:
    before = dict(fake_uv.installed())
    with pytest.raises(ManagerError):
        manager.install("astro-canvas-bad")
    assert fake_uv.installed() == before


def test_install_snapshots_first_then_installs(
    manager: PackManager, fake_uv: FakeEnvironment
) -> None:
    result = manager.install("astro-canvas-demo")
    assert result.ok
    assert fake_uv.installed()["astro-canvas-demo"] == "0.2.0"
    assert result.snapshot_id is not None
    # The snapshot is what the environment looked like *before* the install.
    recorded = manager.snapshot_packages(result.snapshot_id)
    assert "astro-canvas-demo==0.2.0" not in recorded


def test_rollback_restores_the_freeze_exactly(
    manager: PackManager, fake_uv: FakeEnvironment
) -> None:
    """Acceptance: ``uv pip freeze`` after a rollback equals the freeze in the snapshot."""
    before = manager.uv.freeze()
    result = manager.install("astro-canvas-demo")
    assert manager.uv.freeze() != before
    assert result.snapshot_id is not None

    rolled = manager.rollback(result.snapshot_id)
    assert rolled.ok and rolled.restart_required
    assert manager.uv.freeze() == before
    assert "astro-canvas-demo" not in fake_uv.installed()


def test_snapshots_are_listed_newest_first(manager: PackManager) -> None:
    first = manager.snapshot("one")
    second = manager.snapshot("two")
    listed = manager.snapshots()
    assert [s.id for s in listed[:2]] == [second.id, first.id]
    assert listed[0].label == "two"
    assert listed[0].packages == len(manager.uv.freeze())


def test_rolling_back_an_unknown_snapshot_is_refused(manager: PackManager) -> None:
    with pytest.raises(ManagerError, match="unknown snapshot"):
        manager.rollback(9999)


def test_uninstall_removes_the_distribution(manager: PackManager, fake_uv: FakeEnvironment) -> None:
    manager.install("astro-canvas-demo")
    result = manager.uninstall("astro-canvas-demo")
    assert result.ok
    assert "astro-canvas-demo" not in fake_uv.installed()


def test_update_is_a_no_op_when_already_current(manager: PackManager) -> None:
    manager.install("astro-canvas-demo")
    result = manager.update("astro-canvas-demo")
    assert result.ok and result.plan is not None and result.plan.is_empty
    assert "up to date" in result.message


# --- security levels ----------------------------------------------------------------------------


def test_standard_refuses_a_git_url(manager: PackManager) -> None:
    with pytest.raises(SourceError, match="does not allow"):
        manager.check_source("git+https://example.invalid/org/demo")


def test_permissive_allows_a_git_url(manager: PackManager) -> None:
    manager.settings.update(ManagerSettingsUpdate(security="permissive"))
    assert manager.check_source("git+https://example.invalid/org/demo").kind == "git"


def test_strict_refuses_a_package_that_is_not_in_the_registry(manager: PackManager) -> None:
    manager.settings.update(ManagerSettingsUpdate(security="strict"))
    with pytest.raises(SourceError, match="not in the registry"):
        manager.check_source("astro-canvas-demo")


def test_strict_allows_a_registry_pack(manager: PackManager, tmp_path: object) -> None:
    from astro_canvas.manager.registry import RegistryClient

    index = manager.settings.defaults.workspace.parent / "index.json"
    index.write_text(
        '[{"name": "astro-canvas-demo", "source": "astro-canvas-demo"}]', encoding="utf-8"
    )
    manager._registry_client = RegistryClient(str(index))  # noqa: SLF001 - test seam
    manager.settings.update(ManagerSettingsUpdate(security="strict"))
    assert manager.check_source("astro-canvas-demo").name == "astro-canvas-demo"


# --- registration -------------------------------------------------------------------------------


def test_a_new_pack_registers_without_a_restart(
    manager: PackManager, monkeypatch: pytest.MonkeyPatch, fake_uv: FakeEnvironment
) -> None:
    """Acceptance: after installing a pure-Python pack, its nodes are there immediately."""
    _entry_points_after_install(monkeypatch, fake_uv, "good")
    assert len(manager.registry) == 0

    result = manager.install("astro-canvas-demo")
    assert result.ok and not result.restart_required
    assert result.packs == ["good"]
    assert "good.text.token" in manager.registry
    assert result.import_test is not None and result.import_test.ok
    assert [p.name for p in manager.installed()] == ["good"]
    assert manager.installed()[0].source == "astro-canvas-demo"
    assert fake_uv.installed()["astro-canvas-demo"] == "0.2.0"


def test_a_pack_that_cannot_be_imported_is_rolled_back(
    manager: PackManager, monkeypatch: pytest.MonkeyPatch, fake_uv: FakeEnvironment
) -> None:
    _entry_points_after_install(monkeypatch, fake_uv, "broken")
    before = manager.uv.freeze()

    result = manager.install("astro-canvas-demo")
    assert not result.ok
    assert result.import_test is not None and not result.import_test.ok
    assert "definitely_not_installed" in result.import_test.error
    assert "rolled back" in result.message
    assert manager.uv.freeze() == before


def test_disabling_a_pack_unregisters_its_nodes(
    manager: PackManager, monkeypatch: pytest.MonkeyPatch, fake_uv: FakeEnvironment
) -> None:
    _entry_points_after_install(monkeypatch, fake_uv, "good")
    assert manager.install("astro-canvas-demo").packs == ["good"]

    info = manager.set_enabled("good", False)
    assert not info.enabled and not info.loaded
    assert "good.text.token" not in manager.registry
    assert manager.disabled() == {"good"}


def test_a_disabled_pack_stays_unregistered_on_the_next_start(
    manager: PackManager,
    monkeypatch: pytest.MonkeyPatch,
    sessions: sessionmaker[Session],
    fake_uv: FakeEnvironment,
) -> None:
    _entry_points_after_install(monkeypatch, fake_uv, "good")
    manager.install("astro-canvas-demo")
    manager.set_enabled("good", False)

    # A fresh manager over the same database, as a restart would build.
    restarted = PackManager(
        manager.registry, sessions, manager.settings, uv=manager.uv, records=manager.records
    )
    assert "good.text.token" not in restarted.registry
    assert restarted.disabled() == {"good"}
