"""Ratings by day: one row per in-scope title per day, in yearly Parquet files.

A sync writes each new day to data/history/days/<day>.parquet, then folds the days into
data/history/<year>.parquet, sorted by title and then date, so one show's whole history
reads in milliseconds. Only in-scope titles are kept: the series in current.duckdb and
their episodes.
"""

from collections.abc import Iterable
from datetime import date
from itertools import pairwise
from pathlib import Path

import duckdb

from getgood.config import MAX_GAP_DAYS
from getgood.duck import quote, read_imdb, scalar

DAYS = "days"


def known_days(history: Path) -> set[date]:
    """Every day already in the history, in a yearly file or waiting to be folded in."""
    days = {date.fromisoformat(p.stem) for p in (history / DAYS).glob("*.parquet")}
    years = sorted(history.glob("[0-9][0-9][0-9][0-9].parquet"))
    if years:
        with duckdb.connect() as con:
            files = "[" + ", ".join(quote(p) for p in years) + "]"
            days |= {
                d
                for (d,) in con.execute(
                    f"SELECT DISTINCT date FROM read_parquet({files})"
                ).fetchall()
            }
    return days


def write_day(raw_file: Path, day: date, history: Path, current_db: Path) -> int:
    """Keep the in-scope rows of one IMDb ratings file as that day's history.

    Returns the number of rows kept. The file appears only once it's complete.
    """
    folder = history / DAYS
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{day.isoformat()}.parquet"
    tmp = dest.with_name(dest.name + ".tmp")
    try:
        with duckdb.connect() as con:
            con.execute(f"ATTACH {quote(current_db)} AS cur (READ_ONLY)")
            con.execute(f"""
                COPY (
                    SELECT CAST(substr(tconst, 3) AS INTEGER) AS tid,
                           DATE '{day.isoformat()}' AS date,
                           CAST(round(CAST(averageRating AS DOUBLE) * 10) AS UTINYINT)
                               AS rating_x10,
                           CAST(numVotes AS INTEGER) AS votes
                    FROM {read_imdb(raw_file)}
                    WHERE CAST(substr(tconst, 3) AS INTEGER) IN (
                        SELECT tid FROM cur.series UNION ALL SELECT tid FROM cur.episodes
                    )
                    ORDER BY tid
                ) TO {quote(tmp)} (FORMAT parquet, COMPRESSION zstd)""")
            rows: int = scalar(con, f"SELECT count(*) FROM read_parquet({quote(tmp)})")
        tmp.replace(dest)
        return rows
    finally:
        tmp.unlink(missing_ok=True)


def compact(history: Path) -> list[int]:
    """Fold the waiting days into their years' files, sorted by title then date.

    Returns the years rewritten. A day already in its year's file keeps its first copy.
    """
    waiting = sorted((history / DAYS).glob("*.parquet"))
    years = sorted({int(p.stem[:4]) for p in waiting})
    for year in years:
        target = history / f"{year}.parquet"
        days = [p for p in waiting if p.stem.startswith(f"{year}-")]
        sources = ([target] if target.exists() else []) + days
        tmp = target.with_name(target.name + ".tmp")
        files = "[" + ", ".join(quote(p) for p in sources) + "]"
        with duckdb.connect() as con:
            con.execute(f"""
                COPY (
                    SELECT tid, date, rating_x10, votes
                    FROM read_parquet({files}, filename = true)
                    QUALIFY row_number() OVER (PARTITION BY tid, date ORDER BY filename) = 1
                    ORDER BY tid, date
                ) TO {quote(tmp)} (FORMAT parquet, COMPRESSION zstd)""")
        tmp.replace(target)
        for p in days:
            p.unlink()
    return years


def source(history: Path) -> str | None:
    """SQL that reads the whole history, or None while it's empty."""
    files = sorted(history.glob("[0-9][0-9][0-9][0-9].parquet"))
    files += sorted((history / DAYS).glob("*.parquet"))
    if not files:
        return None
    return "read_parquet([" + ", ".join(quote(p) for p in files) + "])"


def gaps(days: Iterable[date], max_gap: int = MAX_GAP_DAYS) -> list[tuple[date, date]]:
    """Each pair of neighbouring history days more than max_gap days apart."""
    ordered = sorted(days)
    return [(a, b) for a, b in pairwise(ordered) if (b - a).days > max_gap]
