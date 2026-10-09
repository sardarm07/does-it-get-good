"""Command-line entry point: getgood <command>."""

import json
from datetime import date
from pathlib import Path
from typing import Annotated

import duckdb
import typer

from getgood import __version__, archive
from getgood.backfill import backfill, save_today, span
from getgood.config import CURRENT_DB, DATA_DIR, MAX_GAP_DAYS
from getgood.fetch import FetchError, fetch_all
from getgood.load import build_current
from getgood.report import answer
from getgood.search import Found, Match, find
from getgood.validate import Finding, check_files, remember_good

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
def sync(
    data_dir: DataDir = DATA_DIR,
    no_history: Annotated[
        bool,
        typer.Option(
            "--no-history",
            help="Don't fetch past days from the Internet Archive; history then grows only "
            "from your own syncs.",
        ),
    ] = False,
) -> None:
    """Download IMDb's latest files, check them, rebuild the tables, and fill the history."""
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
    _print_findings(report.findings)
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

    built = build_current(raw_dir, data_dir / CURRENT_DB, downloads)
    _print_findings(built.findings)
    if not built.ok:
        typer.echo("Sync stopped: the tables from the last sync were kept.", err=True)
        raise typer.Exit(1)
    state = "already up to date" if built.skipped else "built"
    typer.echo(f"Tables {state}: {built.series:,} series, {built.rated_episodes:,} rated episodes")

    history, current = data_dir / "history", data_dir / CURRENT_DB
    if (day := save_today(raw_dir, history, current, downloads)) is not None:
        typer.echo(f"History: saved IMDb's file of {day}")
    if not no_history:
        with archive.client() as http:
            filled = backfill(
                http, history, current, data_dir / "archive", until=date.today(), say=typer.echo
            )
        if filled.added:
            typer.echo(f"Archive: {len(filled.added):,} days added")
        for skipped in filled.skipped:
            typer.echo(f"Warning: archive {skipped}")
        if filled.stopped:
            typer.echo(
                f"Warning: the archive stopped answering ({filled.stopped}). "
                "Everything so far is kept, and the next sync carries on."
            )
    _print_history(history)


@app.command()
def show(
    name: Annotated[str, typer.Argument(help="The series as you'd type it, or its IMDb ID.")],
    year: Annotated[
        int | None, typer.Option(help="The year it started, to choose between namesakes.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the answer as JSON.")] = False,
    data_dir: DataDir = DATA_DIR,
) -> None:
    """Where a series gets good, where it slumps, and its low points."""
    db = data_dir / CURRENT_DB
    if not db.exists():
        typer.echo("No data yet. Run getgood sync first.", err=True)
        raise typer.Exit(1)
    with duckdb.connect(str(db), read_only=True) as con:
        match = _choose(find(con, name, year=year), name, ask=not as_json)
        result = answer(con, match)
    if as_json:
        typer.echo(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
    else:
        typer.echo(result.to_text())


def _choose(found: Found, name: str, *, ask: bool) -> Match:
    """The match to answer for, asking which one when the name could mean several."""
    if found.best is None:
        typer.echo(f'No show matches "{name}".', err=True)
        raise typer.Exit(1)
    if not found.ambiguous:
        return found.best
    options = [f"  {i}. {m.title} ({m.years}), {m.imdb_id}" for i, m in enumerate(found.choices, 1)]
    if not ask:
        typer.echo(f'"{name}" could mean:', err=True)
        typer.echo("\n".join(options), err=True)
        typer.echo("Add --year or give the IMDb ID to choose.", err=True)
        raise typer.Exit(2)
    typer.echo(f'"{name}" could mean:')
    typer.echo("\n".join(options))
    while True:
        pick: int = typer.prompt("Which one", default=1, type=int)
        if 1 <= pick <= len(found.choices):
            return found.choices[pick - 1]
        typer.echo(f"Choose a number from 1 to {len(found.choices)}.")


def _print_history(history: Path) -> None:
    s = span(history)
    if not s.days:
        typer.echo("History: empty")
        return
    typer.echo(f"History: {s.days:,} days from {s.first} to {s.last}")
    if s.gaps:
        listed = ", ".join(f"{a} to {b}" for a, b in s.gaps[:5])
        more = f" and {len(s.gaps) - 5} more" if len(s.gaps) > 5 else ""
        typer.echo(f"  gaps of more than {MAX_GAP_DAYS} days: {listed}{more}")


def _print_findings(findings: list[Finding]) -> None:
    for f in findings:
        label = "Problem" if f.blocking else "Warning"
        typer.echo(f"{label}: {f.file}: {f.message}", err=f.blocking)
