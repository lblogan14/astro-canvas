"""``astro-canvas workspace list|use|new``: pick the folder the app opens."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from astro_canvas.settings import get_settings
from astro_canvas.store.recent import RecentWorkspaces
from astro_canvas.store.workspace import STATE_DIR

app = typer.Typer(help="Choose which folder Astro Canvas opens.", no_args_is_help=True)


def _recent() -> RecentWorkspaces:
    return RecentWorkspaces(get_settings().config_dir)


@app.command("list")
def list_workspaces() -> None:
    """List recently used workspaces; the one the app will open is marked."""
    recent = _recent()
    current = get_settings().workspace.resolve()
    entries = recent.list()
    if str(current) not in entries:
        entries.insert(0, str(current))
    for entry in entries:
        path = Path(entry)
        mark = "*" if path.resolve() == current else " "
        state = "" if (path / STATE_DIR).is_dir() else "  (not initialised)"
        missing = "" if path.is_dir() else "  (missing)"
        typer.echo(f"{mark} {path}{state}{missing}")


@app.command("use")
def use_workspace(
    path: Annotated[Path, typer.Argument(help="Folder to open from now on.")],
    create: Annotated[bool, typer.Option("--create", help="Create it if it is missing.")] = False,
) -> None:
    """Make ``path`` the workspace the app opens next time."""
    target = path.expanduser().resolve()
    if not target.exists():
        if not create:
            typer.secho(
                f"no such folder: {target} (pass --create to make it)",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=1)
        target.mkdir(parents=True, exist_ok=True)
    if not target.is_dir():
        typer.secho(f"not a folder: {target}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    _recent().select(target)
    typer.echo(f"workspace set to {target}")


@app.command("new")
def new_workspace(
    path: Annotated[Path, typer.Argument(help="Folder to create and open.")],
    use: Annotated[
        bool, typer.Option("--use/--no-use", help="Also make it the default workspace.")
    ] = True,
) -> None:
    """Create a workspace folder, initialise its database and select it."""
    from astro_canvas.store.workspace import Workspace  # noqa: PLC0415 - pulls in SQLAlchemy

    target = path.expanduser().resolve()
    if target.exists() and not target.is_dir():
        typer.secho(f"not a folder: {target}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1)
    existed = (target / STATE_DIR).is_dir()
    workspace = Workspace(target)
    workspace.close()
    if use:
        _recent().select(target)
    verb = "opened" if existed else "created"
    typer.echo(f"{verb} {target}")


__all__ = ["app"]
