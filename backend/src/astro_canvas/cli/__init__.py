"""``astro-canvas`` command line interface.

The entry point of the wheel (``[project.scripts]``) and of the PyApp launcher
(``PYAPP_EXEC_SPEC=astro_canvas.cli:main``). Subcommands live in one module each; the *modules*
are imported here rather than the command functions, so ``astro_canvas.cli.serve`` stays the
module and tests can patch inside it. The heavy imports (the engine, the packs, SQLAlchemy) all
happen inside the command bodies, so ``astro-canvas version`` and ``--help`` stay instant.
"""

from __future__ import annotations

import typer

from astro_canvas._version import __version__
from astro_canvas.cli import bundles, doctor, packs, runner, serve, workspaces

app = typer.Typer(
    name="astro-canvas",
    help="Node-based canvas for exploring astronomical data.",
    no_args_is_help=True,
    add_completion=False,
)

app.command("serve")(serve.serve)
app.command("open")(serve.open_app_in_browser)
app.command("run")(runner.run)
app.command("doctor")(doctor.doctor)
app.add_typer(workspaces.app, name="workspace")
app.add_typer(packs.app, name="pack")
app.add_typer(bundles.app, name="bundle")

run_headless = runner.run_headless
run_server = serve.run_server
open_when_ready = serve.open_when_ready


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


def main() -> None:
    """Console-script and PyApp entry point."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()


__all__ = [
    "app",
    "main",
    "open_when_ready",
    "run_headless",
    "run_server",
    "version",
]
