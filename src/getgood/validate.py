"""Checks on IMDb's files that stop a sync before bad data gets used."""

import gzip
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from getgood.config import (
    EXPECTED_COLUMNS,
    MAX_UNPARSED_NUMBERS,
    MIN_VOTES,
    ROW_COUNT_PERIOD_DAYS,
    ROW_COUNT_TOLERANCE,
    STALE_AFTER_DAYS,
)
from getgood.duck import read_imdb
from getgood.fetch import Download

LAST_GOOD = "last_good.json"

QUERIES = {
    "title.basics.tsv.gz": "SELECT count(*) AS rows FROM {src}",
    "title.episode.tsv.gz": """
        SELECT count(*) AS rows,
               count(*) - count(DISTINCT tconst) AS duplicate_ids,
               count(seasonNumber) + count(episodeNumber) AS numbers,
               count(*) FILTER (WHERE seasonNumber IS NOT NULL
                                  AND TRY_CAST(seasonNumber AS INTEGER) IS NULL)
             + count(*) FILTER (WHERE episodeNumber IS NOT NULL
                                  AND TRY_CAST(episodeNumber AS INTEGER) IS NULL)
                 AS unparsed_numbers
        FROM {src}""",
    "title.ratings.tsv.gz": """
        SELECT count(*) AS rows,
               count(*) - count(DISTINCT tconst) AS duplicate_ids,
               count(*) FILTER (WHERE NOT coalesce(
                   TRY_CAST(averageRating AS DOUBLE) BETWEEN 1 AND 10, false)) AS bad_ratings,
               count(*) FILTER (WHERE TRY_CAST(numVotes AS BIGINT) IS NULL
                                   OR TRY_CAST(numVotes AS BIGINT) < 0) AS bad_votes,
               count(*) FILTER (WHERE TRY_CAST(numVotes AS BIGINT) < {min_votes}) AS low_votes
        FROM {src}""",
}


@dataclass(frozen=True)
class Finding:
    """One problem with one file. A blocking finding stops the sync; the rest are warnings."""

    file: str
    message: str
    blocking: bool = True


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list[Finding])
    rows: dict[str, int] = field(default_factory=dict[str, int])
    already_checked: list[str] = field(default_factory=list[str])

    @property
    def ok(self) -> bool:
        return not any(f.blocking for f in self.findings)


def check_files(raw_dir: Path, downloads: Sequence[Download], *, today: date) -> Report:
    """Check each downloaded file, skipping any already checked and unchanged since."""
    last_good = _read_last_good(raw_dir)
    report = Report()
    with duckdb.connect() as con:
        for d in downloads:
            previous = last_good.get(d.name)
            if d.as_of is not None and (age := (today - d.as_of).days) > STALE_AFTER_DAYS:
                report.findings.append(
                    Finding(d.name, f"IMDb's newest file is {age} days old", blocking=False)
                )
            if previous and d.last_modified and previous.get("last_modified") == d.last_modified:
                report.rows[d.name] = previous["rows"]
                report.already_checked.append(d.name)
                continue
            report.findings += _check(con, d, previous, report)
    return report


def check_copy(path: Path) -> list[Finding]:
    """The blocking checks for one ratings file on its own, such as an archived copy:
    header, readability, duplicate IDs, ratings and vote counts."""
    copy = Download("title.ratings.tsv.gz", path, False, 0, None)
    with duckdb.connect() as con:
        return [f for f in _check(con, copy, None, Report()) if f.blocking]


def remember_good(raw_dir: Path, downloads: Sequence[Download], report: Report) -> None:
    """Record row counts and dates, for the next sync to compare against."""
    if not report.ok:
        raise ValueError("only a report without blocking findings can be remembered")
    record = {
        d.name: {
            "rows": report.rows[d.name],
            "as_of": d.as_of.isoformat() if d.as_of else None,
            "last_modified": d.last_modified,
        }
        for d in downloads
    }
    (raw_dir / LAST_GOOD).write_text(json.dumps(record, indent=2) + "\n")


def _check(
    con: duckdb.DuckDBPyConnection, d: Download, previous: dict[str, Any] | None, report: Report
) -> list[Finding]:
    expected = EXPECTED_COLUMNS[d.name]
    try:
        with gzip.open(d.path, "rt", encoding="utf-8") as f:
            header = tuple(f.readline().rstrip("\n").split("\t"))
        if header != expected:
            was, now = ", ".join(expected), ", ".join(header)
            return [Finding(d.name, f"columns changed from {was} to {now}")]
        result = con.sql(QUERIES[d.name].format(src=read_imdb(d.path), min_votes=MIN_VOTES))
        stats = dict(zip(result.columns, result.fetchone() or (), strict=True))
    except (OSError, EOFError, UnicodeDecodeError, duckdb.Error) as error:
        return [Finding(d.name, f"can't be read ({type(error).__name__}: {error})")]

    report.rows[d.name] = stats["rows"]
    found: list[Finding] = []
    if previous:
        found += _row_count_change(d, stats["rows"], previous)
    if stats.get("duplicate_ids"):
        found.append(Finding(d.name, f"IDs that appear more than once: {stats['duplicate_ids']:,}"))
    if stats.get("bad_ratings"):
        found.append(Finding(d.name, f"ratings outside 1.0 to 10.0: {stats['bad_ratings']:,}"))
    if stats.get("bad_votes"):
        found.append(
            Finding(d.name, f"vote counts that aren't whole numbers: {stats['bad_votes']:,}")
        )
    if stats.get("numbers") and stats["unparsed_numbers"] / stats["numbers"] > MAX_UNPARSED_NUMBERS:
        share = stats["unparsed_numbers"] / stats["numbers"]
        found.append(
            Finding(
                d.name,
                f"season and episode numbers that fail to parse: {share:.2%} "
                f"(the limit is {MAX_UNPARSED_NUMBERS:.1%})",
            )
        )
    if stats.get("low_votes"):
        found.append(
            Finding(
                d.name,
                f"ratings with fewer than {MIN_VOTES} votes: {stats['low_votes']:,} "
                "(IMDb may have changed its cut-off)",
                blocking=False,
            )
        )
    return found


def _row_count_change(d: Download, rows: int, previous: dict[str, Any]) -> list[Finding]:
    if not previous.get("rows"):
        return []
    days = days_between(d.as_of, previous.get("as_of"))
    allowed = allowance(ROW_COUNT_TOLERANCE, days)
    change = rows / previous["rows"] - 1
    if abs(change) <= allowed:
        return []
    return [
        Finding(
            d.name,
            f"row count moved {change:+.1%} since the last good file ({previous['rows']:,} to "
            f"{rows:,}); the limit is ±{allowed:.0%} for files {apart(days)}",
        )
    ]


def days_between(newer: date | None, older: str | None) -> int:
    """Whole days from an ISO date to a newer date; at least 1, and 1 when either is unknown."""
    if newer is None or not older:
        return 1
    return max(1, (newer - date.fromisoformat(older)).days)


def allowance(tolerance: float, days: int) -> float:
    """The change allowed between two files: one tolerance per period between them, at least one."""
    return tolerance * max(1.0, days / ROW_COUNT_PERIOD_DAYS)


def apart(days: int) -> str:
    return f"{days} day{'' if days == 1 else 's'} apart"


def _read_last_good(raw_dir: Path) -> dict[str, dict[str, Any]]:
    try:
        return json.loads((raw_dir / LAST_GOOD).read_text())
    except FileNotFoundError, json.JSONDecodeError:
        return {}
