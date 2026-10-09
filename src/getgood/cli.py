"""Command-line entry point: getgood <command>."""

from datetime import date
from pathlib import Path
from typing import Annotated

import typer

from getgood import __version__
from getgood.config import DATA_DIR
from getgood.fetch import FetchError, fetch_all
from getgood.validate import check_files, remember_good

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
    """Download IMDb's latest files and check them before they're used."""
    raw_dir = data_dir / "raw"
    try:
        downloads = fetch_all(raw_dir)
    except FetchError as error:
        typer.echo(f"Sync stopped: {error}", err=True)
        raise typer.Exit(1) from error
    for d in downloads:
        what = f"downloaded {d.size / 1e6:.1f} MB" if d.changed else "unchanged"
        when = f"IMDb's file of {d.as_of}" if d.as_of else "no date from IMDb"
        typer.echo(f"{d.name}: {what} ({when})")

    report = check_files(raw_dir, downloads, today=date.today())
    for f in report.findings:
        label = "Problem" if f.blocking else "Warning"
        typer.echo(f"{label}: {f.file}: {f.message}", err=f.blocking)
    if not report.ok:
        typer.echo("Sync stopped: these files won't be used until they pass.", err=True)
        raise typer.Exit(1)
    remember_good(raw_dir, downloads, report)
    checked = len(downloads) - len(report.already_checked)
    if checked == 0:
        summary = f"all {len(downloads)} files already checked"
    else:
        summary = f"{checked} file{'' if checked == 1 else 's'} checked"
        if report.already_checked:
            summary += f", {len(report.already_checked)} already checked"
    typer.echo(f"Checks passed ({summary})")
