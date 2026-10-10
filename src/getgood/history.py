"""Ratings by day: one row per in-scope title per day, in monthly Parquet files.

A sync writes each new day to data/history/days/<day>.parquet, then folds the days into
data/history/<year>-<month>.parquet. Every row names its series (a series page names
itself), and a month's rows are sorted by series, title and date, so one show's whole
history reads in milliseconds, however far apart its episodes' IDs are. A month is small
enough to re-sort on every sync, and each month's file lists its days in its metadata, so
the history's days are known without reading its rows. Only in-scope titles are kept: the
series in current.duckdb and their episodes.
"""

from collections.abc import Iterable
from datetime import date
from itertools import pairwise
from pathlib import Path

import duckdb

from getgood.config import MAX_GAP_DAYS
from getgood.duck import quote, read_imdb, scalar

DAYS = "days"
MONTHS = "[0-9][0-9][0-9][0-9]-[0-9][0-9].parquet"
DAYS_KEY = "getgood_days"
"""The metadata key under which a month's file lists its days."""
COLUMNS = "tid, series, date, rating_x10, votes"
ORDER = "series, tid, date"


def known_days(history: Path) -> set[date]:
    """Every day already in the history, in a month's file or waiting to be folded in."""
    days = {date.fromisoformat(p.stem) for p in (history / DAYS).glob("*.parquet")}
    months = sorted(history.glob(MONTHS))
    if months:
        with duckdb.connect() as con:
            for (listed,) in con.execute(
                f"SELECT decode(value) FROM parquet_kv_metadata({_list(months)}) "
                "WHERE key = encode(?)",
                [DAYS_KEY],
            ).fetchall():
                days |= {date.fromisoformat(d) for d in listed.split(",")}
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
                    SELECT t.tid, t.series, DATE '{day.isoformat()}' AS date,
                           CAST(round(CAST(r.averageRating AS DOUBLE) * 10) AS UTINYINT)
                               AS rating_x10,
                           CAST(r.numVotes AS INTEGER) AS votes
                    FROM {read_imdb(raw_file)} r
                    JOIN (
                        SELECT tid, tid AS series FROM cur.series
                        UNION ALL SELECT tid, series FROM cur.episodes
                    ) t ON t.tid = CAST(substr(r.tconst, 3) AS INTEGER)
                    ORDER BY t.series, t.tid
                ) TO {quote(tmp)} (FORMAT parquet, COMPRESSION zstd)""")
            rows: int = scalar(con, f"SELECT count(*) FROM read_parquet({quote(tmp)})")
        tmp.replace(dest)
        return rows
    finally:
        tmp.unlink(missing_ok=True)


def compact(history: Path) -> list[str]:
    """Fold the waiting days into their months' files, sorted by series, title and date.

    Returns the months rewritten, as YYYY-MM. A day already in its month's file keeps the
    copy it has.
    """
    waiting = sorted((history / DAYS).glob("*.parquet"))
    rewritten: list[str] = []
    for month in sorted({p.stem[:7] for p in waiting}):
        target = history / f"{month}.parquet"
        days = [p for p in waiting if p.stem.startswith(f"{month}-")]
        with duckdb.connect() as con:
            held: set[date] = set()
            if target.exists():
                held = {
                    d
                    for (d,) in con.execute(
                        f"SELECT DISTINCT date FROM read_parquet({quote(target)})"
                    ).fetchall()
                }
            new = [p for p in days if date.fromisoformat(p.stem) not in held]
            if new:
                listed = ",".join(
                    d.isoformat() for d in sorted(held | {date.fromisoformat(p.stem) for p in new})
                )
                sources = ([target] if target.exists() else []) + new
                tmp = target.with_name(target.name + ".tmp")
                con.execute(f"""
                    COPY (
                        SELECT {COLUMNS} FROM read_parquet({_list(sources)}) ORDER BY {ORDER}
                    ) TO {quote(tmp)}
                    (FORMAT parquet, COMPRESSION zstd, KV_METADATA {{{DAYS_KEY}: '{listed}'}})""")
                tmp.replace(target)
                rewritten.append(month)
        for p in days:
            p.unlink()
    return rewritten


def upgrade(history: Path, current_db: Path) -> list[str]:
    """Name each row's series in files written before rows named it, from the current
    tables, and re-sort them. Returns the names of the files rewritten.
    """
    files = sorted(history.glob(MONTHS)) + sorted((history / DAYS).glob("*.parquet"))
    rewritten: list[str] = []
    if not files:
        return rewritten
    with duckdb.connect() as con:
        con.execute(f"ATTACH {quote(current_db)} AS cur (READ_ONLY)")
        for path in files:
            columns = {
                name
                for (name,) in con.execute(
                    f"SELECT name FROM parquet_schema({quote(path)})"
                ).fetchall()
            }
            if "series" in columns:
                continue
            listed = con.execute(
                f"SELECT decode(value) FROM parquet_kv_metadata({quote(path)}) "
                "WHERE key = encode(?)",
                [DAYS_KEY],
            ).fetchone()
            metadata = f", KV_METADATA {{{DAYS_KEY}: '{listed[0]}'}}" if listed else ""
            tmp = path.with_name(path.name + ".tmp")
            # an episode no longer in the tables can't be placed, so it's kept as its own series
            con.execute(f"""
                COPY (
                    SELECT h.tid, coalesce(e.series, h.tid) AS series, h.date, h.rating_x10,
                           h.votes
                    FROM read_parquet({quote(path)}) h LEFT JOIN cur.episodes e USING (tid)
                    ORDER BY {ORDER}
                ) TO {quote(tmp)} (FORMAT parquet, COMPRESSION zstd{metadata})""")
            tmp.replace(path)
            rewritten.append(path.name)
    return rewritten


def source(history: Path) -> str | None:
    """SQL that reads the whole history, or None while it's empty."""
    files = sorted(history.glob(MONTHS)) + sorted((history / DAYS).glob("*.parquet"))
    if not files:
        return None
    return f"read_parquet({_list(files)})"


def gaps(days: Iterable[date], max_gap: int = MAX_GAP_DAYS) -> list[tuple[date, date]]:
    """Each pair of neighbouring history days more than max_gap days apart."""
    ordered = sorted(days)
    return [(a, b) for a, b in pairwise(ordered) if (b - a).days > max_gap]


def _list(paths: Iterable[Path]) -> str:
    return "[" + ", ".join(quote(p) for p in paths) + "]"
