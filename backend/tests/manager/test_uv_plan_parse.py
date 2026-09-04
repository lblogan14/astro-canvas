"""Parsing ``uv pip install --dry-run`` output, and classifying install sources.

The transcripts below are real uv 0.11 output (``NO_COLOR=1``), kept verbatim so a change in uv's
wording fails here rather than in the Manager dialog.
"""

from __future__ import annotations

import pytest

from astro_canvas.manager.plan import (
    SourceError,
    classify_source,
    compare_versions,
    parse_dry_run,
)

ADD = """\
Resolved 3 packages in 480ms
Would download 3 packages
Would install 3 packages
 + astro-canvas-demo==0.2.0
 + click==8.1.7
 + rich==13.7.1
"""

DOWNGRADE = """\
Resolved 1 package in 122ms
Would download 1 package
Would uninstall 1 package
Would install 1 package
 - structlog==26.1.0
 + structlog==24.4.0
"""

MIXED = """\
Resolved 4 packages in 900ms
Would download 3 packages
Would uninstall 2 packages
Would install 3 packages
 - numpy==2.5.2
 + numpy==2.6.0
 - stale-helper==1.0.0
 + astro-canvas-demo==0.2.0
"""

NO_CHANGES = """\
Checked 1 package in 12ms
Would make no changes
"""

NO_SOLUTION_OUT = ""
NO_SOLUTION_ERR = """\
  x No solution found when resolving dependencies:
  `-> Because astropy>=6.0.0 depends on numpy>=1.22 and you require astropy>=6 and
      numpy==1.19.5, we can conclude that your requirements are unsatisfiable.
"""


def test_pure_addition() -> None:
    plan = parse_dry_run(ADD, source="astro-canvas-demo")
    assert plan.ok and not plan.conflicts
    assert [(c.name, c.action, c.to_version) for c in plan.adds] == [
        ("astro-canvas-demo", "add", "0.2.0"),
        ("click", "add", "8.1.7"),
        ("rich", "add", "13.7.1"),
    ]
    assert not plan.upgrades and not plan.downgrades and not plan.removals


def test_a_version_going_backwards_is_a_downgrade() -> None:
    plan = parse_dry_run(DOWNGRADE)
    assert [(c.name, c.from_version, c.to_version) for c in plan.downgrades] == [
        ("structlog", "26.1.0", "24.4.0")
    ]
    assert plan.ok


def test_mixed_diff_splits_into_add_upgrade_and_remove() -> None:
    plan = parse_dry_run(MIXED)
    assert [c.name for c in plan.adds] == ["astro-canvas-demo"]
    assert [(c.name, c.from_version, c.to_version) for c in plan.upgrades] == [
        ("numpy", "2.5.2", "2.6.0")
    ]
    assert [c.name for c in plan.removals] == ["stale-helper"]


def test_the_diff_is_read_from_stderr_too() -> None:
    """uv writes its progress and diff to stderr; a stdout-only parser sees an empty plan."""
    plan = parse_dry_run("", ADD, source="astro-canvas-demo")
    assert [c.name for c in plan.adds] == ["astro-canvas-demo", "click", "rich"]


def test_nothing_to_do_is_an_empty_but_valid_plan() -> None:
    plan = parse_dry_run(NO_CHANGES)
    assert plan.ok and plan.is_empty
    assert plan.message == "already satisfied: nothing would change"


EXPLANATION = (
    "Because astropy>=6.0.0 depends on numpy>=1.22 and you require astropy>=6 and "
    "numpy==1.19.5, we can conclude that your requirements are unsatisfiable."
)

MULTI_STEP_ERR = """\
  x No solution found when resolving dependencies:
  `-> Because astro-canvas was not found in the package registry and
      astro-canvas==0.1.0a0 depends on numpy>=1.26, we can conclude that
      astro-canvas==0.1.0a0 depends on numpy>=1.26.
      And because you require numpy==1.19.5 and astro-canvas==0.1.0a0, we can
      conclude that your requirements are unsatisfiable.

hint: Pre-releases are available for numpy.
"""


def test_a_failed_resolution_blocks_and_explains() -> None:
    plan = parse_dry_run(NO_SOLUTION_OUT, NO_SOLUTION_ERR, returncode=1, source="astro-canvas-bad")
    assert not plan.ok
    assert plan.changes == []
    # uv hard-wraps its report; the conflict is one readable paragraph, not the raw lines.
    assert plan.conflicts == [EXPLANATION]
    assert plan.message == EXPLANATION
    assert "No solution found" in plan.output


def test_the_summary_is_uvs_conclusion_not_its_first_step() -> None:
    """A multi-step report ends with the sentence the user can act on."""
    plan = parse_dry_run("", MULTI_STEP_ERR, returncode=1)
    assert plan.message == (
        "you require numpy==1.19.5 and astro-canvas==0.1.0a0, we can conclude that your "
        "requirements are unsatisfiable."
    )
    # The hint below the blank line is not part of the explanation.
    assert "hint:" not in plan.conflicts[0]


def test_a_nonzero_exit_without_a_resolver_report_still_blocks() -> None:
    plan = parse_dry_run("", "error: Distribution not found at: file:///nope", returncode=2)
    assert not plan.ok
    assert plan.message == "Distribution not found at: file:///nope"


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("1.0.0", "1.0.1", "upgrade"),
        ("1.10.0", "1.9.0", "downgrade"),
        ("2.5.2", "2.6.0", "upgrade"),
        ("0.1.0a0", "0.1.0", "upgrade"),
        ("1.2.3", "1.2.3", "reinstall"),
    ],
)
def test_version_comparison(old: str, new: str, expected: str) -> None:
    assert compare_versions(old, new) == expected


@pytest.mark.parametrize(
    ("raw", "kind", "name"),
    [
        ("astro-canvas-rbcodes", "pypi", "astro-canvas-rbcodes"),
        ("astro_canvas_demo>=0.2,<1", "pypi", "astro-canvas-demo"),
        ("git+https://github.com/org/astro-canvas-demo@v1.2", "git", "astro-canvas-demo"),
        ("https://github.com/org/demo.git", "git", "demo"),
        ("https://files.example/demo-1.0-py3-none-any.whl", "url", ""),
        ("./packs/demo", "path", ""),
        ("C:/packs/demo", "path", ""),
    ],
)
def test_source_classification(raw: str, kind: str, name: str) -> None:
    source = classify_source(raw)
    assert (source.kind, source.name) == (kind, name)


def test_a_git_ref_is_kept() -> None:
    assert classify_source("git+https://host/org/demo@v1.2").ref == "v1.2"


@pytest.mark.parametrize("raw", ["", "   ", "not a package!"])
def test_unusable_sources_are_refused(raw: str) -> None:
    with pytest.raises(SourceError):
        classify_source(raw)
