"""Install sources and the resolution plan parsed out of ``uv pip install --dry-run``.

Design 9 makes the dry run the contract with the user: *nothing* is written to the environment
before the diff (what is added, upgraded, downgraded, removed) and any conflict have been shown
and confirmed. This module owns both halves of that -- classifying what the user typed into a
source the security level can judge, and turning uv's human-readable dry-run output into a
structured ``InstallPlan``.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SourceKind = Literal["pypi", "git", "url", "path"]
ChangeAction = Literal["add", "upgrade", "downgrade", "remove", "reinstall"]
PlanAction = Literal["install", "update", "uninstall", "rollback"]

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REQUIREMENT_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[A-Za-z0-9._,\s-]*\])?"
    r"\s*(?P<spec>(?:[=!<>~^]=?|===)\s*[^,;\s]+(?:\s*,\s*(?:[=!<>~^]=?|===)\s*[^,;\s]+)*)?$"
)
_CHANGE = re.compile(r"^\s*([+\-~])\s*(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>\S+)")
_NO_SOLUTION = re.compile(r"No solution found when resolving dependencies", re.IGNORECASE)
_LEADING = re.compile(r"^[^0-9A-Za-z]*")
"""Strips uv's box-drawing gutter (``╰─▶``, ``│``, ``` `-> ```) off a report line."""
_NO_CHANGES = re.compile(r"Would make no changes", re.IGNORECASE)
_AUDIT_ONLY = re.compile(r"^Audited \d+ package", re.MULTILINE)


class SourceError(ValueError):
    """The install source is malformed, or the security level does not allow it."""


class PackSource(BaseModel):
    """What the user asked to install, classified so the security level can judge it."""

    model_config = ConfigDict(frozen=True)

    raw: str
    kind: SourceKind
    name: str = Field(default="", description="Distribution name when it can be known up front.")
    specifier: str = ""
    ref: str | None = Field(default=None, description="Git ref (``@tag``) when ``kind`` is git.")

    @property
    def requirement(self) -> str:
        """The string handed to ``uv pip install``."""
        return self.raw


def classify_source(raw: str) -> PackSource:
    """Turn a user-typed source into a ``PackSource``.

    Accepts a PyPI requirement (``astro-canvas-rbcodes>=0.1``), a git URL
    (``git+https://host/org/repo@v1``), a direct wheel/sdist URL, or a local path.

    Raises:
        SourceError: when the string is empty or is not a shape the manager understands.
    """
    text = raw.strip()
    if not text:
        raise SourceError("an install source is required")
    lowered = text.lower()
    if lowered.startswith(("git+", "git@")) or (
        lowered.startswith(("http://", "https://")) and lowered.rstrip("/").endswith(".git")
    ):
        stem = text.split("#", 1)[0].rstrip("/")
        ref = stem.rsplit("@", 1)[1] if "@" in stem.rsplit("/", 1)[-1] else None
        repo = stem.rsplit("/", 1)[-1]
        if ref:
            repo = repo.rsplit("@", 1)[0]
        return PackSource(
            raw=text, kind="git", name=repo.removesuffix(".git").replace("_", "-"), ref=ref
        )
    if lowered.startswith(("http://", "https://")):
        return PackSource(raw=text, kind="url", name="")
    if lowered.startswith((".", "/", "~")) or re.match(r"^[A-Za-z]:[\\/]", text) or "/" in text:
        return PackSource(raw=text, kind="path", name="")
    match = REQUIREMENT_PATTERN.match(text)
    if match is None or not NAME_PATTERN.match(match.group("name")):
        raise SourceError(f"{raw!r} is not a package name, git URL, URL or path")
    return PackSource(
        raw=text,
        kind="pypi",
        name=match.group("name").replace("_", "-").lower(),
        specifier=(match.group("spec") or "").strip(),
    )


class PackageChange(BaseModel):
    """One line of the resolution diff."""

    model_config = ConfigDict(frozen=True)

    name: str
    action: ChangeAction
    from_version: str | None = None
    to_version: str | None = None


class InstallPlan(BaseModel):
    """What installing ``source`` would do to the environment (design 9).

    ``ok`` is the gate: the UI shows the diff either way, but only an ``ok`` plan may be confirmed.
    """

    source: str
    action: PlanAction = "install"
    changes: list[PackageChange] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    ok: bool = True
    message: str = ""
    output: str = Field(default="", description="Raw uv output, shown in the dialog's details.")

    @property
    def adds(self) -> list[PackageChange]:
        return [c for c in self.changes if c.action == "add"]

    @property
    def upgrades(self) -> list[PackageChange]:
        return [c for c in self.changes if c.action == "upgrade"]

    @property
    def downgrades(self) -> list[PackageChange]:
        return [c for c in self.changes if c.action == "downgrade"]

    @property
    def removals(self) -> list[PackageChange]:
        return [c for c in self.changes if c.action == "remove"]

    @property
    def is_empty(self) -> bool:
        return not self.changes


def _release_key(version: str) -> tuple[object, ...]:
    """A comparable key for a version string uv printed, when PEP 440 parsing fails.

    Numeric segments compare as numbers; a segment carrying a letter suffix (``1.0rc1``) sorts
    below the same segment without one, which is the pre-release rule that matters for a diff.
    """
    parts: list[object] = []
    for chunk in re.split(r"[.\-+_]", version):
        digits = re.match(r"^(\d*)(.*)$", chunk)
        number = int(digits.group(1)) if digits and digits.group(1) else 0
        suffix = digits.group(2) if digits else chunk
        parts.append((number, 0 if suffix else 1, suffix))
    return tuple(parts)


def compare_versions(old: str, new: str) -> ChangeAction:
    """``upgrade``, ``downgrade`` or ``reinstall`` for a package that changes version."""
    if old == new:
        return "reinstall"
    try:
        from packaging.version import Version  # noqa: PLC0415 - optional, present with uv/pip

        return "upgrade" if Version(new) > Version(old) else "downgrade"
    except Exception:  # noqa: BLE001 - a local version scheme uv accepted but PEP 440 does not
        return "upgrade" if _release_key(new) > _release_key(old) else "downgrade"


def parse_dry_run(
    stdout: str,
    stderr: str = "",
    returncode: int = 0,
    *,
    source: str = "",
    action: PlanAction = "install",
) -> InstallPlan:
    """Turn ``uv pip install --dry-run`` output into an ``InstallPlan``.

    uv prints the diff as ``- name==old`` / ``+ name==new`` lines; a package appearing on both
    sides is an upgrade or a downgrade, ``+`` alone is an addition and ``-`` alone a removal.
    Both streams are scanned: uv writes its progress and diff to **stderr** and reserves stdout
    for machine output, so a parser that reads stdout alone sees an empty plan.
    A failed resolution has no diff at all -- its stderr carries a "No solution found" report,
    which becomes ``conflicts`` and blocks the install.
    """
    text = f"{stdout}\n{stderr}"
    if returncode != 0 or _NO_SOLUTION.search(text):
        report = resolver_report(text)
        summary = _summarize_failure(report, text)
        return InstallPlan(
            source=source,
            action=action,
            conflicts=[report] if report else [],
            ok=False,
            message=summary or "uv could not resolve this source",
            output=text.strip(),
        )
    removed: dict[str, str] = {}
    added: dict[str, str] = {}
    for line in text.splitlines():
        match = _CHANGE.match(line)
        if match is None:
            continue
        sign, name, version = line.strip()[0], match.group("name").lower(), match.group("version")
        (removed if sign == "-" else added)[name] = version
    changes: list[PackageChange] = []
    for name in sorted(set(removed) | set(added)):
        old, new = removed.get(name), added.get(name)
        if old is not None and new is not None:
            changes.append(
                PackageChange(
                    name=name, action=compare_versions(old, new), from_version=old, to_version=new
                )
            )
        elif new is not None:
            changes.append(PackageChange(name=name, action="add", to_version=new))
        else:
            changes.append(PackageChange(name=name, action="remove", from_version=old))
    message = ""
    if not changes and (_NO_CHANGES.search(text) or _AUDIT_ONLY.search(text)):
        message = "already satisfied: nothing would change"
    return InstallPlan(
        source=source, action=action, changes=changes, ok=True, message=message, output=text.strip()
    )


def resolver_report(text: str) -> str:
    """uv's "No solution found" explanation, unwrapped into one readable paragraph.

    uv hard-wraps the report and prefixes it with box-drawing characters, so the raw lines are
    unreadable in a dialog; the words are what matter.
    """
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if _NO_SOLUTION.search(line)), None)
    if start is None:
        return ""
    collected: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped or stripped.startswith(("hint:", "help:")):
            break
        collected.append(_LEADING.sub("", line).strip())
    return " ".join(part for part in collected if part)


def _summarize_failure(report: str, text: str) -> str:
    """The one sentence worth putting in a dialog title: uv's conclusion, not its reasoning.

    Sentences are split on ``". "`` rather than on ``"."`` so version numbers stay intact.
    """
    sentences = [part.strip() for part in report.split(". ") if part.strip()]
    for sentence in reversed(sentences):
        if "unsatisfiable" in sentence:
            return sentence.removeprefix("And because ").strip().rstrip(".") + "."
    if sentences:
        return sentences[0].rstrip(".") + "."
    for line in (line.strip() for line in text.splitlines()):
        if line.startswith(("error:", "Error:", "×")):
            return line.lstrip("× ").removeprefix("error:").strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


__all__ = [
    "ChangeAction",
    "InstallPlan",
    "PackSource",
    "PackageChange",
    "PlanAction",
    "SourceError",
    "SourceKind",
    "classify_source",
    "compare_versions",
    "parse_dry_run",
    "resolver_report",
]
