"""Build data/current.duckdb: today's in-scope series, their episodes and ratings."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import duckdb

from getgood.config import (
    EXCLUDED_GENRES,
    IMDB_FILES,
    LOST_VOTES_TOLERANCE,
    MIN_RATED_EPISODES,
    SCOPE_SIZE_TOLERANCE,
)
from getgood.duck import quote, read_imdb, scalar
from getgood.fetch import Download
from getgood.validate import Finding, allowance, apart, days_between

BASICS, EPISODE, RATINGS = IMDB_FILES

BUILD_VERSION = "2"
"""Bump when the tables change for the same IMDb files, so the next sync rebuilds them."""

SEARCH_KEY = (
    "trim(regexp_replace(lower(strip_accents(replace({}, '&', ' and '))), '[^a-z0-9]+', ' ', 'g'))"
)
"""SQL that turns a title, or a name someone types, into the key that search compares."""


@dataclass
class Build:
    """What a build produced, or why it stopped."""

    series: int = 0
    rated_episodes: int = 0
    as_of: date | None = None
    skipped: bool = False
    findings: list[Finding] = field(default_factory=list[Finding])

    @property
    def ok(self) -> bool:
        return not any(f.blocking for f in self.findings)


def build_current(raw_dir: Path, db_path: Path, downloads: Sequence[Download]) -> Build:
    """Rebuild the tables from IMDb's files, unless they were built from these same files.

    The new database replaces the old one only if it passes the checks against it.
    """
    stamp = {
        "build_version": BUILD_VERSION,
        **{f"source:{d.name}": d.last_modified or "" for d in downloads},
    }
    as_of = max((d.as_of for d in downloads if d.as_of), default=None)
    if db_path.exists() and _stamp(db_path) == stamp:
        return _summary(db_path, skipped=True)

    building = db_path.with_name(db_path.name + ".building")
    building.unlink(missing_ok=True)
    try:
        with duckdb.connect(str(building)) as con:
            _create_tables(con, raw_dir)
            con.execute("CREATE TABLE meta (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)")
            meta = [("as_of", as_of.isoformat() if as_of else ""), *stamp.items()]
            con.executemany("INSERT INTO meta VALUES (?, ?)", meta)
            findings = _compare_with(con, db_path, as_of) if db_path.exists() else []
        if any(f.blocking for f in findings):
            return Build(as_of=as_of, findings=findings)
        building.replace(db_path)
    finally:
        building.unlink(missing_ok=True)
    built = _summary(db_path, skipped=False)
    built.findings = findings
    return built


def _create_tables(con: duckdb.DuckDBPyConnection, raw_dir: Path) -> None:
    con.execute(f"""
        CREATE TEMP TABLE all_series AS
        SELECT CAST(substr(tconst, 3) AS INTEGER) AS tid, titleType AS kind, primaryTitle AS title,
               TRY_CAST(startYear AS SMALLINT) AS start_year,
               TRY_CAST(endYear AS SMALLINT) AS end_year, genres
        FROM {read_imdb(raw_dir / BASICS)}
        WHERE titleType IN ('tvSeries', 'tvMiniSeries')""")
    con.execute(f"""
        CREATE TEMP TABLE all_episodes AS
        SELECT CAST(substr(tconst, 3) AS INTEGER) AS tid,
               CAST(substr(parentTconst, 3) AS INTEGER) AS series,
               TRY_CAST(seasonNumber AS SMALLINT) AS season,
               TRY_CAST(episodeNumber AS INTEGER) AS episode
        FROM {read_imdb(raw_dir / EPISODE)}""")
    con.execute(f"""
        CREATE TEMP TABLE all_ratings AS
        SELECT CAST(substr(tconst, 3) AS INTEGER) AS tid,
               CAST(round(CAST(averageRating AS DOUBLE) * 10) AS UTINYINT) AS rating_x10,
               CAST(numVotes AS INTEGER) AS votes
        FROM {read_imdb(raw_dir / RATINGS)}""")
    excluded = "[" + ", ".join(f"'{g}'" for g in EXCLUDED_GENRES) + "]"
    con.execute(f"""
        CREATE TEMP TABLE scope AS
        SELECT e.series AS tid
        FROM all_episodes e
        JOIN all_ratings r USING (tid)
        JOIN all_series s ON s.tid = e.series
        WHERE e.season >= 1 AND e.episode IS NOT NULL
          AND NOT list_has_any(string_split(coalesce(s.genres, ''), ','), {excluded})
        GROUP BY e.series
        HAVING count(*) >= {MIN_RATED_EPISODES}""")
    con.execute(f"""
        CREATE TABLE series AS
        SELECT s.tid, s.title, s.kind, s.start_year, s.end_year, s.genres,
               {SEARCH_KEY.format("s.title")} AS search_key
        FROM all_series s JOIN scope USING (tid)
        ORDER BY s.tid""")
    con.execute("""
        CREATE TABLE episodes AS
        SELECT e.tid, e.series, e.season, e.episode
        FROM all_episodes e JOIN scope s ON s.tid = e.series
        WHERE e.season >= 1 AND e.episode IS NOT NULL
        ORDER BY e.series, e.season, e.episode, e.tid""")
    con.execute("""
        CREATE TABLE ratings AS
        SELECT tid, rating_x10, votes
        FROM all_ratings
        WHERE tid IN (SELECT tid FROM series) OR tid IN (SELECT tid FROM episodes)
        ORDER BY tid""")


def _compare_with(
    con: duckdb.DuckDBPyConnection, db_path: Path, as_of: date | None
) -> list[Finding]:
    """Stop the build if scope or votes moved too far since the database it would replace."""
    try:
        con.execute(f"ATTACH {quote(db_path)} AS previous (READ_ONLY)")
        try:
            old_series = scalar(con, "SELECT count(*) FROM previous.series")
            old_as_of = scalar(con, "SELECT value FROM previous.meta WHERE key = 'as_of'")
            lowered, common = con.execute("""
                SELECT count(*) FILTER (WHERE n.votes < o.votes), count(*)
                FROM ratings n JOIN previous.ratings o USING (tid)""").fetchone() or (0, 0)
        finally:
            con.execute("DETACH previous")
    except duckdb.Error:
        return []  # nothing usable to compare with, so this build stands on its own

    new_series = scalar(con, "SELECT count(*) FROM series")
    days = days_between(as_of, old_as_of)
    found: list[Finding] = []
    if old_series:
        change = new_series / old_series - 1
        allowed = allowance(SCOPE_SIZE_TOLERANCE, days)
        if abs(change) > allowed:
            found.append(
                Finding(
                    "in-scope series",
                    f"count moved {change:+.1%} since the last sync ({old_series:,} to "
                    f"{new_series:,}); the limit is ±{allowed:.0%} for files {apart(days)}",
                )
            )
    if common:
        share = lowered / common
        allowed = allowance(LOST_VOTES_TOLERANCE, days)
        if share > allowed:
            found.append(
                Finding(
                    "ratings",
                    f"titles that lost votes since the last sync: {share:.1%} ({lowered:,} of "
                    f"{common:,}); the limit is {allowed:.0%} for files {apart(days)}",
                )
            )
    return found


def _stamp(db_path: Path) -> dict[str, str]:
    """The build version and IMDb files (by Last-Modified) the database was built from."""
    try:
        with duckdb.connect(str(db_path), read_only=True) as con:
            rows = con.execute(
                "SELECT key, value FROM meta WHERE key = 'build_version' OR key LIKE 'source:%'"
            ).fetchall()
    except duckdb.Error:
        return {}
    return {key: value for key, value in rows}


def _summary(db_path: Path, *, skipped: bool) -> Build:
    with duckdb.connect(str(db_path), read_only=True) as con:
        series = scalar(con, "SELECT count(*) FROM series")
        rated = scalar(con, "SELECT count(*) FROM episodes JOIN ratings USING (tid)")
        as_of = scalar(con, "SELECT value FROM meta WHERE key = 'as_of'")
    return Build(
        series=series,
        rated_episodes=rated,
        as_of=date.fromisoformat(as_of) if as_of else None,
        skipped=skipped,
    )
