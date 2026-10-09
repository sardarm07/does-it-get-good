"""Command-line entry point: getgood <command>."""

from typing import Annotated

import typer

from getgood import __version__

app = typer.Typer(
    help="Find where a TV series gets good, slumps or gets review-bombed.",
    no_args_is_help=True,
)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"getgood {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_print_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """Find where a TV series gets good, slumps or gets review-bombed."""
