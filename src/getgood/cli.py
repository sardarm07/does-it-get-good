"""Command-line entry point: getgood <command>."""

from pathlib import Path
from typing import Annotated

import typer

from getgood import __version__
from getgood.config import DATA_DIR
from getgood.fetch import FetchError, fetch_all

app = typer.Typer(
    help="Find where a TV series gets good, slumps or gets review-bombed.",
    no_args_is_help=True,
)

DataDir = Annotated[
    Path, typer.Option(help="Where downloaded data lives. Defaults to $GETGOOD_DATA or ./data.")
]


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


@app.command()
def sync(data_dir: DataDir = DATA_DIR) -> None:
    """Download IMDb's latest files, skipping any that haven't changed."""
    try:
        downloads = fetch_all(data_dir / "raw")
    except FetchError as error:
        typer.echo(f"Sync stopped: {error}", err=True)
        raise typer.Exit(1) from error
    for d in downloads:
        what = f"downloaded {d.size / 1e6:.1f} MB" if d.changed else "unchanged"
        when = f"IMDb's file of {d.as_of}" if d.as_of else "no date from IMDb"
        typer.echo(f"{d.name}: {what} ({when})")
