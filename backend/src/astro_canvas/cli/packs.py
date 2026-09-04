"""``astro-canvas pack list|install|remove|snapshot|rollback``: the Manager from a terminal.

Every command here calls the same ``PackManager`` the ``/api/manager`` routes do, so the two
cannot drift. ``install`` keeps the plan-then-confirm shape the UI has (design 9): it resolves,
prints the diff, refuses a plan with conflicts, and asks before touching the environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from astro_canvas.cli.context import open_app
from astro_canvas.manager.packs import InstallResult, ManagerError
from astro_canvas.manager.plan import InstallPlan, SourceError
from astro_canvas.manager.uv import UvError, UvNotFoundError

app = typer.Typer(help="Install, remove and roll back node packs.", no_args_is_help=True)

WorkspaceOption = Annotated[Path | None, typer.Option(help="Workspace folder to act on.")]


def _fail(exc: Exception) -> typer.Exit:
    typer.secho(str(exc), fg=typer.colors.RED, err=True)
    return typer.Exit(code=1)


def print_plan(plan: InstallPlan) -> None:
    """Show a resolution the way the confirmation dialog does: changes first, then conflicts."""
    for change in plan.changes:
        arrow = f"{change.from_version or '-'} -> {change.to_version or '-'}"
        typer.echo(f"  {change.action:<9} {change.name:<28} {arrow}")
    if plan.is_empty and plan.ok:
        typer.echo("  (nothing to do: already satisfied)")
    if plan.conflicts:
        typer.secho("conflicts:", fg=typer.colors.RED)
        for conflict in plan.conflicts:
            typer.echo(f"  {conflict}")
    if plan.message:
        typer.echo(plan.message)


def print_result(result: InstallResult) -> None:
    colour = typer.colors.GREEN if result.ok else typer.colors.RED
    typer.secho(result.message or result.action, fg=colour)
    if result.import_test is not None and not result.import_test.ok:
        typer.echo(result.import_test.error)
    if result.restart_required:
        typer.secho("restart the server to load the new code", fg=typer.colors.YELLOW)


@app.command("list")
def list_packs(workspace: WorkspaceOption = None) -> None:
    """List installed packs with their versions, node counts and load errors."""
    with open_app(workspace) as ctx:
        for pack in ctx.packs.installed():
            state = "" if pack.enabled else "  disabled"
            if pack.error:
                state = f"  ERROR {pack.error}"
            typer.echo(
                f"{pack.name:<20} {pack.version:<12} "
                f"{pack.node_count:>3} nodes {pack.type_count:>3} types{state}"
            )


@app.command("install")
def install(
    source: Annotated[str, typer.Argument(help="Pack name, requirement, git URL or local path.")],
    workspace: WorkspaceOption = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation.")] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Resolve and print the plan, install nothing.")
    ] = False,
) -> None:
    """Resolve a pack, show what would change, then install it."""
    with open_app(workspace) as ctx:
        manager = ctx.packs
        try:
            plan = manager.resolve(source)
        except (ManagerError, SourceError, UvError, UvNotFoundError) as exc:
            raise _fail(exc) from exc
        typer.echo(f"plan for {source}:")
        print_plan(plan)
        if not plan.ok:
            raise typer.Exit(code=1)
        if dry_run:
            return
        if not yes and not typer.confirm("install?", default=False):
            typer.echo("cancelled")
            raise typer.Exit(code=1)
        try:
            result = manager.install(source, plan=plan)
        except (ManagerError, UvError, UvNotFoundError) as exc:
            raise _fail(exc) from exc
        print_result(result)
        if not result.ok:
            raise typer.Exit(code=1)


@app.command("remove")
def remove(
    name: Annotated[str, typer.Argument(help="Pack name as ``pack list`` shows it.")],
    workspace: WorkspaceOption = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation.")] = False,
) -> None:
    """Uninstall a pack's distribution and unregister its nodes."""
    with open_app(workspace) as ctx:
        manager = ctx.packs
        try:
            plan = manager.resolve_uninstall(name)
        except (ManagerError, UvError, UvNotFoundError) as exc:
            raise _fail(exc) from exc
        typer.echo(f"plan for removing {name}:")
        print_plan(plan)
        if not yes and not typer.confirm("remove?", default=False):
            typer.echo("cancelled")
            raise typer.Exit(code=1)
        try:
            result = manager.uninstall(name)
        except (ManagerError, UvError, UvNotFoundError) as exc:
            raise _fail(exc) from exc
        print_result(result)
        if not result.ok:
            raise typer.Exit(code=1)


@app.command("snapshot")
def snapshot(
    label: Annotated[str, typer.Option(help="What this snapshot is for.")] = "",
    workspace: WorkspaceOption = None,
    show: Annotated[
        bool, typer.Option("--list", help="List snapshots instead of taking one.")
    ] = False,
) -> None:
    """Record the current environment so ``pack rollback`` can restore it."""
    with open_app(workspace) as ctx:
        manager = ctx.packs
        if show:
            for info in manager.snapshots():
                typer.echo(
                    f"{info.id:>4}  {info.created}  {info.packages:>4} packages  {info.label}"
                )
            return
        try:
            info = manager.snapshot(label)
        except (UvError, UvNotFoundError) as exc:
            raise _fail(exc) from exc
        typer.echo(f"snapshot {info.id} recorded ({info.packages} packages)")


@app.command("rollback")
def rollback(
    snapshot_id: Annotated[int, typer.Argument(help="Snapshot id from ``pack snapshot --list``.")],
    workspace: WorkspaceOption = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation.")] = False,
) -> None:
    """Restore a recorded environment."""
    with open_app(workspace) as ctx:
        manager = ctx.packs
        try:
            packages = manager.snapshot_packages(snapshot_id)
        except ManagerError as exc:
            raise _fail(exc) from exc
        typer.echo(f"snapshot {snapshot_id} holds {len(packages)} packages")
        if not yes and not typer.confirm("roll back to it?", default=False):
            typer.echo("cancelled")
            raise typer.Exit(code=1)
        try:
            result = manager.rollback(snapshot_id)
        except (ManagerError, UvError, UvNotFoundError) as exc:
            raise _fail(exc) from exc
        print_result(result)
        if not result.ok:
            raise typer.Exit(code=1)


__all__ = ["app", "print_plan", "print_result"]
