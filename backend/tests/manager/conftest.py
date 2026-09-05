"""A scripted ``uv`` stand-in so the manager's orchestration is testable without a network.

The manager's job is *orchestration*: plan, snapshot, install, import-test, register, roll back.
Exercising that against real PyPI would make the suite slow, online and non-deterministic, so
these tests point ``UvRunner`` at a small Python script that keeps an "environment" in a JSON
file and answers ``uv pip install/uninstall/freeze/sync`` from it. Everything between the
manager and that script - argument construction, subprocess handling, output parsing - is the
real code path.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session, sessionmaker

from astro_canvas.manager.packs import PackManager
from astro_canvas.manager.registry import RegistryClient
from astro_canvas.manager.settings import SettingsStore
from astro_canvas.manager.uv import UvRunner
from astro_canvas.sdk import NodeRegistry
from astro_canvas.settings import Settings
from astro_canvas.store.workspace import Workspace
from tests.conftest import FIXTURES

FAKE_UV = r'''
"""A deterministic stand-in for ``uv`` driven by a JSON state file."""
import json, os, sys
from pathlib import Path

STATE = Path(os.environ["FAKE_UV_STATE"])


def load():
    return json.loads(STATE.read_text(encoding="utf-8"))


def save(state):
    STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def freeze(state):
    return sorted(f"{n}=={v}" for n, v in state["installed"].items())


def resolve(state, requirements):
    """Return (changes, conflict) for the requested pins against what is installed."""
    changes, conflict = {}, None
    for req in requirements:
        name, _, version = req.partition("==")
        name = name.strip()
        pinned = state.get("available", {}).get(name)
        if pinned is None and not version:
            conflict = (
                "  x No solution found when resolving dependencies:\n"
                f"  `-> Because {name} is not available and you require {name}, we can "
                "conclude that your requirements are unsatisfiable."
            )
            break
        target = version or pinned or "0"
        requires = state.get("requires", {}).get(f"{name}=={target}", {})
        for dep, dep_version in requires.items():
            other = changes.get(dep) or state["installed"].get(dep)
            if other is not None and other != dep_version:
                conflict = (
                    "  x No solution found when resolving dependencies:\n"
                    f"  `-> Because {name}=={target} depends on {dep}=={dep_version} and you "
                    f"require {dep}=={other}, we can conclude that your requirements are "
                    "unsatisfiable."
                )
                break
            changes[dep] = dep_version
        if conflict:
            break
        changes[name] = target
    return changes, conflict


def diff_lines(state, changes):
    lines = []
    for name, version in sorted(changes.items()):
        current = state["installed"].get(name)
        if current == version:
            continue
        if current is not None:
            lines.append(f" - {name}=={current}")
        lines.append(f" + {name}=={version}")
    return lines


def say(text):
    """Progress and the diff go to stderr, exactly where the real uv puts them."""
    sys.stderr.write(text + "\n")


def main(argv):
    if argv[:1] == ["--version"]:
        print("uv 0.0.0-fake")
        return 0
    if argv[:1] != ["pip"]:
        say(f"fake uv: unsupported command {argv}")
        return 2
    args = [a for a in argv[1:] if a != "--python"]
    args = [a for a in args if not a.endswith("python.exe") and not a.endswith("/python")]
    command, rest = args[0], args[1:]
    state = load()
    if command == "freeze":
        print("\n".join(freeze(state)))
        return 0
    if command == "sync":
        wanted = Path(rest[0]).read_text(encoding="utf-8").split()
        state["installed"] = {
            r.partition("==")[0]: r.partition("==")[2] for r in wanted if r.strip()
        }
        save(state)
        say(f"Installed {len(state['installed'])} packages")
        return 0
    dry = "--dry-run" in rest
    requirements = [r for r in rest if not r.startswith("-")]
    if command == "uninstall":
        removed = [r for r in requirements if r in state["installed"]]
        say(f"{'Would uninstall' if dry else 'Uninstalled'} {len(removed)} package")
        for name in removed:
            say(f" - {name}=={state['installed'][name]}")
            if not dry:
                state["installed"].pop(name, None)
        if not dry:
            save(state)
        return 0
    if command != "install":
        say(f"fake uv: unsupported pip command {command}")
        return 2
    changes, conflict = resolve(state, requirements)
    if conflict:
        say(conflict)
        return 1
    lines = diff_lines(state, changes)
    say(f"Resolved {len(changes)} packages in 1ms")
    if not lines:
        say("Would make no changes" if dry else "Audited 1 package")
        return 0
    say(f"Would install {len(changes)} packages" if dry else f"Installed {len(changes)} packages")
    say("\n".join(lines))
    if not dry:
        state["installed"].update(changes)
        save(state)
    return 0


sys.exit(main(sys.argv[1:]))
'''


class FakeEnvironment:
    """The JSON "environment" the fake uv reads and writes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.state_path = root / "uv-state.json"
        self.script = root / "fake_uv.py"
        self.script.write_text(FAKE_UV, encoding="utf-8")
        self.shim = root / ("uv.cmd" if sys.platform == "win32" else "uv")
        if sys.platform == "win32":
            self.shim.write_text(f'@echo off\r\n"{sys.executable}" "{self.script}" %*\r\n')
        else:
            self.shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{self.script}" "$@"\n')
            self.shim.chmod(0o755)
        self.write(
            installed={"astro-canvas": "0.1.0", "numpy": "2.5.2"},
            available={"astro-canvas-demo": "0.2.0", "astro-canvas-bad": "0.1.0", "numpy": "2.5.2"},
            requires={"astro-canvas-bad==0.1.0": {"numpy": "1.19.5"}},
        )

    def write(self, **state: object) -> None:
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def read(self) -> dict[str, dict[str, str]]:
        data: dict[str, dict[str, str]] = json.loads(self.state_path.read_text(encoding="utf-8"))
        return data

    def installed(self) -> dict[str, str]:
        return self.read()["installed"]

    def set_installed(self, packages: dict[str, str]) -> None:
        state = self.read()
        state["installed"] = packages
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def runner(self) -> UvRunner:
        # ``PYTHONPATH`` makes the fixture packs importable in the manager's import-test
        # subprocess, the way a real install would put them on the interpreter's path.
        return UvRunner(
            self.shim,
            sys.executable,
            env={"FAKE_UV_STATE": str(self.state_path), "PYTHONPATH": str(FIXTURES)},
            timeout=60.0,
        )


@pytest.fixture(autouse=True)
def _fresh_process() -> Iterator[None]:
    """Forget the fixture packs between tests.

    Hot-registration deliberately refuses to re-import a module that is already in
    ``sys.modules`` (it would not pick up new code, so a restart is required instead). Each test
    therefore has to start from the state a freshly started server is in.
    """
    yield
    for name in [n for n in sys.modules if n.startswith("pack_")]:
        del sys.modules[name]


@pytest.fixture
def fake_uv(tmp_path: Path) -> FakeEnvironment:
    root = tmp_path / "uvenv"
    root.mkdir()
    return FakeEnvironment(root)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    workspace = Workspace(tmp_path / "ws")
    yield workspace.sessions
    workspace.close()


@pytest.fixture
def manager(
    fake_uv: FakeEnvironment, sessions: sessionmaker[Session], tmp_path: Path
) -> PackManager:
    """A ``PackManager`` on an empty registry, the fake uv and a temp workspace database."""
    settings = Settings(workspace=tmp_path / "ws", config_dir=tmp_path / "cfg", auth="none")
    store = SettingsStore(sessions, settings)
    return PackManager(
        NodeRegistry(),
        sessions,
        store,
        uv=fake_uv.runner(),
        records=[],
        registry_client=RegistryClient(str(tmp_path / "missing-index.json")),
    )
