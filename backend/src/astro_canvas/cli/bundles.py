"""``astro-canvas bundle export|import``: move a workflow, its data and its provenance around.

The same functions the ``/api/bundles`` routes call, so a bundle written here is byte-for-byte
the one the Share menu writes -- which is what makes "export on my laptop, import on the cluster"
a supported path rather than a coincidence.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from astro_canvas.cli.context import open_app
from astro_canvas.manager.bundles import (
    DEFAULT_EMBED_MB,
    BundleError,
    ExportOptions,
    OutputSelection,
    bundle_target,
    export_bundle,
    open_bundle,
    prepare_import,
)
from astro_canvas.server.runtime import UnknownWorkflowError
from astro_canvas.store.workspace import PathOutsideWorkspaceError

app = typer.Typer(help="Export and import ``.acw`` bundles.", no_args_is_help=True)

WorkspaceOption = Annotated[Path | None, typer.Option(help="Workspace folder to act on.")]


@app.command("export")
def export(
    workflow_id: Annotated[str, typer.Argument(help="Workflow id (see the app's Workflows list).")],
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Where to write the .acw file.")
    ] = None,
    workspace: WorkspaceOption = None,
    embed_mb: Annotated[
        int, typer.Option(help="Embed input files up to this size; larger ones are referenced.")
    ] = DEFAULT_EMBED_MB,
    outputs: Annotated[
        OutputSelection, typer.Option(help="Which cached outputs to carry.")
    ] = "leaves",
    figures: Annotated[bool, typer.Option("--figures/--no-figures")] = True,
) -> None:
    """Pack a stored workflow into a bundle."""
    with open_app(workspace) as ctx:
        runtime = ctx.runtime
        try:
            doc = runtime.get(workflow_id)
            scheduler = runtime.scheduler(workflow_id)
        except UnknownWorkflowError:
            typer.secho(f"unknown workflow {workflow_id!r}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from None
        target = out.expanduser().resolve() if out else bundle_target(runtime.workspace, doc)
        target.parent.mkdir(parents=True, exist_ok=True)
        requirements: list[str] = []
        if ctx.manager is not None:
            try:
                requirements = ctx.manager.uv.freeze()
            except Exception as exc:  # noqa: BLE001 - a lock without a freeze is still a lock
                typer.secho(f"note: no dependency freeze ({exc})", fg=typer.colors.YELLOW)
        manifest = export_bundle(
            doc,
            scheduler,
            runtime.workspace,
            runtime.registry,
            ctx.discovery.packs,
            target=target,
            options=ExportOptions(
                embed_inputs_max_mb=embed_mb, include_outputs=outputs, include_figures=figures
            ),
            requirements=requirements,
        )
        typer.echo(f"wrote {target}")
        typer.echo(
            f"  {manifest.name}: {len(manifest.inputs)} inputs, "
            f"{len(manifest.outputs)} outputs, {len(manifest.figures)} figures"
        )


@app.command("import")
def import_bundle(
    path: Annotated[Path, typer.Argument(help="The .acw file to import.")],
    workspace: WorkspaceOption = None,
    restore_into: Annotated[
        str, typer.Option(help="Workspace folder for restored input files.")
    ] = "imports",
) -> None:
    """Validate a bundle, restore what it carries and store its workflow."""
    with open_app(workspace) as ctx:
        runtime = ctx.runtime
        try:
            payload = path.expanduser().read_bytes()
        except OSError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from None
        try:
            contents = open_bundle(payload)
            doc, result = prepare_import(
                contents,
                runtime.workspace,
                runtime.registry,
                ctx.discovery.packs,
                restore_into=restore_into,
            )
        except (BundleError, PathOutsideWorkspaceError) as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from None
        runtime.save(doc, label=f"imported from {path.name}")
        typer.echo(f"imported {doc.name} as {doc.id}")
        for missing in result.missing_inputs:
            typer.secho(f"  missing input: {missing.path}", fg=typer.colors.YELLOW)
        for pack, requirement in sorted(result.missing_packs.items()):
            typer.secho(f"  missing pack: {pack} ({requirement})", fg=typer.colors.YELLOW)
        if result.quarantined:
            typer.secho(
                "  the code nodes are quarantined: review them in the app before running",
                fg=typer.colors.YELLOW,
            )


__all__ = ["app"]
