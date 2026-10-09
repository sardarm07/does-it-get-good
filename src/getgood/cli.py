"""Command-line entry point: getgood <command>."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import duckdb
import typer

from getgood import __version__, archive
from getgood.backfill import Span, backfill, save_today, span
from getgood.charts import write_page
from getgood.config import CURRENT_DB, DATA_DIR, MAX_GAP_DAYS, RECENT_DAYS
from getgood.duck import scalar
from getgood.fetch import FetchError, fetch_all
from getgood.history import known_days, source
from getgood.load import build_current
from getgood.report import answer
from getgood.runs import log_run, recent_runs
from getgood.search import Found, Match, find
from getgood.sweep import listing, sweep
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
    started = datetime.now(UTC)
    run: dict[str, Any] = {"started": started.isoformat(timespec="seconds"), "outcome": "stopped"}
    try:
        _sync(data_dir, no_history, run)
        run["outcome"] = "ok"
    finally:
        run["seconds"] = round((datetime.now(UTC) - started).total_seconds(), 1)
        log_run(data_dir, run)


def _sync(data_dir: Path, no_history: bool, run: dict[str, Any]) -> None:
    raw_dir = data_dir / "raw"
    try:
        downloads = fetch_all(raw_dir)
    except FetchError as error:
        run["reason"] = str(error)
        typer.echo(f"Sync stopped: {error}", err=True)
        raise typer.Exit(1) from error
    run["files"] = {d.name: {"changed": d.changed, "as_of": d.as_of} for d in downloads}
    for d in downloads:
        what = f"downloaded {d.size / 1e6:.1f} MB" if d.changed else "unchanged"
        when = f"IMDb's file of {d.as_of}" if d.as_of else "no date from IMDb"
        typer.echo(f"{d.name}: {what} ({when})")

    report = check_files(raw_dir, downloads, today=date.today())
    _print_findings(report.findings)
    if not report.ok:
        run["reason"] = "; ".join(f"{f.file}: {f.message}" for f in report.findings if f.blocking)
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
        run["reason"] = "; ".join(f"{f.file}: {f.message}" for f in built.findings if f.blocking)
        typer.echo("Sync stopped: the tables from the last sync were kept.", err=True)
        raise typer.Exit(1)
    run["tables"] = {"series": built.series, "rated_episodes": built.rated_episodes}
    state = "already up to date" if built.skipped else "built"
    typer.echo(f"Tables {state}: {built.series:,} series, {built.rated_episodes:,} rated episodes")

    history, current = data_dir / "history", data_dir / CURRENT_DB
    if (day := save_today(raw_dir, history, current, downloads)) is not None:
        run["saved_today"] = day
        typer.echo(f"History: saved IMDb's file of {day}")
    if not no_history:
        with archive.client() as http:
            filled = backfill(
                http, history, current, data_dir / "archive", until=date.today(), say=typer.echo
            )
        archived: dict[str, Any] = {"added": len(filled.added), "skipped": len(filled.skipped)}
        run["archive"] = archived
        if filled.added:
            typer.echo(f"Archive: {len(filled.added):,} days added")
        for skipped in filled.skipped:
            typer.echo(f"Warning: archive {skipped}")
        if filled.stopped:
            archived["stopped"] = filled.stopped
            typer.echo(
                f"Warning: the archive stopped answering ({filled.stopped}). "
                "Everything so far is kept, and the next sync carries on."
            )
    s = _print_history(history)
    run["history"] = {"days": s.days, "first": s.first, "last": s.last, "gaps": len(s.gaps)}


@app.command()
def status(data_dir: DataDir = DATA_DIR) -> None:
    """The tables, the history, and the last few syncs."""
    db = data_dir / CURRENT_DB
    if db.exists():
        with duckdb.connect(str(db), read_only=True) as con:
            as_of = scalar(con, "SELECT value FROM meta WHERE key = 'as_of'")
            series = scalar(con, "SELECT count(*) FROM series")
            rated = scalar(con, "SELECT count(*) FROM episodes JOIN ratings USING (tid)")
        typer.echo(f"Tables: {series:,} series, {rated:,} rated episodes, IMDb's files of {as_of}")
    else:
        typer.echo("Tables: none yet. Run getgood sync.")
    _print_history(data_dir / "history")
    runs = recent_runs(data_dir)
    if runs:
        typer.echo("Last syncs:")
    for r in runs:
        when = str(r.get("started", "?"))[:16].replace("T", " ")
        what = r.get("reason") or _run_summary(r)
        typer.echo(f"  {when}  {r.get('outcome', '?'):<7}  {r.get('seconds', 0):>7.1f} s  {what}")


def _run_summary(run: dict[str, Any]) -> str:
    files: dict[str, Any] = run.get("files", {})
    changed = sum(1 for f in files.values() if f.get("changed"))
    parts = [f"{changed} file{'' if changed == 1 else 's'} downloaded"]
    if "archive" in run:
        parts.append(f"{run['archive'].get('added', 0)} archive days added")
    if "history" in run:
        days = run["history"].get("days", 0)
        parts.append(f"history {days:,} day{'' if days == 1 else 's'}")
    return ", ".join(parts)


@app.command()
def show(
    name: Annotated[str, typer.Argument(help="The series as you'd type it, or its IMDb ID.")],
    year: Annotated[
        int | None, typer.Option(help="The year it started, to choose between namesakes.")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the answer as JSON.")] = False,
    chart: Annotated[
        bool, typer.Option("--chart", help="Draw the answer on a page and open it in a browser.")
    ] = False,
    data_dir: DataDir = DATA_DIR,
) -> None:
    """Where a series gets good, where it slumps, its low points and its review bombs."""
    db = data_dir / CURRENT_DB
    if not db.exists():
        typer.echo("No data yet. Run getgood sync first.", err=True)
        raise typer.Exit(1)
    with duckdb.connect(str(db), read_only=True) as con:
        match = _choose(find(con, name, year=year), name, ask=not as_json)
        result = answer(con, match, data_dir / "history")
    if as_json:
        typer.echo(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
    else:
        typer.echo(result.to_text())
    if chart:
        page = write_page(result.to_json(), data_dir / "charts")
        typer.echo(f"Chart: {page}", err=as_json)
        typer.launch(page.resolve().as_uri())


@app.command()
def bombs(
    since: Annotated[
        datetime | None,
        typer.Option(
            formats=["%Y-%m-%d"],
            help=f"The first day to look at. Defaults to {RECENT_DAYS} days before the last.",
        ),
    ] = None,
    until: Annotated[
        datetime | None,
        typer.Option(
            formats=["%Y-%m-%d"], help="The last day to look at. Defaults to the history's last."
        ),
    ] = None,
    every_kind: Annotated[
        bool, typer.Option("--all", help="List boosts and vote surges too, not just bombs.")
    ] = False,
    limit: Annotated[int, typer.Option(min=1, help="How many events to list.")] = 20,
    data_dir: DataDir = DATA_DIR,
) -> None:
    """The biggest review bombs across all shows, newest first."""
    db, history = data_dir / CURRENT_DB, data_dir / "history"
    relation, days = source(history), known_days(history)
    if not db.exists() or relation is None or not days:
        typer.echo("No history yet. Run getgood sync first.", err=True)
        raise typer.Exit(1)
    last = until.date() if until else max(days)
    first = since.date() if since else last - timedelta(days=RECENT_DAYS)
    if first > last:
        typer.echo(f"--since {first} is after the last day, {last}.", err=True)
        raise typer.Exit(2)
    with duckdb.connect(str(db), read_only=True) as con:
        events = sweep(con, relation, days, since=first, until=last)
        typer.echo(
            listing(con, events, since=first, until=last, every_kind=every_kind, limit=limit)
        )


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


def _print_history(history: Path) -> Span:
    s = span(history)
    if not s.days:
        typer.echo("History: empty")
        return s
    typer.echo(f"History: {s.days:,} day{'' if s.days == 1 else 's'} from {s.first} to {s.last}")
    if s.gaps:
        listed = ", ".join(f"{a} to {b}" for a, b in s.gaps[:5])
        more = f" and {len(s.gaps) - 5} more" if len(s.gaps) > 5 else ""
        typer.echo(f"  gaps of more than {MAX_GAP_DAYS} days: {listed}{more}")
    return s


def _print_findings(findings: list[Finding]) -> None:
    for f in findings:
        label = "Problem" if f.blocking else "Warning"
        typer.echo(f"{label}: {f.file}: {f.message}", err=f.blocking)
