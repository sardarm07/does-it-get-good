"""Tiny files in IMDb's format for tests. They never hold real IMDb data."""

import gzip
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import duckdb

from getgood.analysis.verdicts import Episode
from getgood.config import CURRENT_DB, EXPECTED_COLUMNS, IMDB_FILES
from getgood.duck import quote
from getgood.fetch import Download
from getgood.history import DAYS, compact
from getgood.load import build_current

TODAY = date(2026, 10, 9)
BASICS, EPISODE, RATINGS = IMDB_FILES
HISTORY_START = date(2023, 1, 1)

type Row = tuple[int, date, float, int]
"""A title's rating and votes on one day of a made-up history."""


def write_imdb_file(raw: Path, name: str, rows: list[str], header: str | None = None) -> None:
    """Write a gzipped TSV the way IMDb does: a header line, then one line per row."""
    lines = [header if header is not None else "\t".join(EXPECTED_COLUMNS[name]), *rows]
    with gzip.open(raw / name, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def downloads(raw: Path, day: date = TODAY) -> list[Download]:
    """What fetch_all would report for files IMDb published on this day."""
    published = datetime(day.year, day.month, day.day, 0, 39, 31, tzinfo=UTC)
    stamp = format_datetime(published, usegmt=True)
    return [Download(name, raw / name, True, 1, stamp) for name in IMDB_FILES]


def write_fixture(raw: Path, *, cafe_genres: str = "Crime,Drama", votes: int = 100) -> None:
    """Five titles, one per scope rule.

    1 Grey's Anatomy: in scope, 6 rated episodes
    2 Short Run: out, only 5 of its 6 episodes are rated
    3 Island Life: out, Reality-TV
    4 Café Noir: in scope; its special (season 0) and unnumbered episode are left out
    5 A Film: out, not a series
    """
    write_imdb_file(
        raw,
        BASICS,
        [
            "tt0000001\ttvSeries\tGrey's Anatomy\tGrey's Anatomy\t0\t2005\t\\N\t41\tDrama,Romance",
            "tt0000002\ttvSeries\tShort Run\tShort Run\t0\t2010\t2010\t22\tComedy",
            "tt0000003\ttvSeries\tIsland Life\tIsland Life\t0\t2012\t2014\t44\tReality-TV",
            f"tt0000004\ttvMiniSeries\tCafé Noir\tCafé Noir\t0\t2020\t2020\t50\t{cafe_genres}",
            "tt0000005\tmovie\tA Film\tA Film\t0\t2001\t\\N\t95\tDrama",
        ],
    )
    episodes: list[str] = []
    ratings = [f"tt000000{n}\t8.0\t{votes}" for n in range(1, 6)]
    for show in (1, 2, 3, 4):
        for k in range(1, 7):
            episodes.append(f"tt{show}00000{k}\ttt000000{show}\t1\t{k}")
            if not (show == 2 and k == 6):
                ratings.append(f"tt{show}00000{k}\t{7 + k / 10:.1f}\t{votes}")
    episodes += ["tt4000007\ttt0000004\t0\t1", "tt4000008\ttt0000004\t\\N\t\\N"]
    ratings += [f"tt4000007\t9.0\t{votes}", f"tt4000008\t9.0\t{votes}"]
    write_imdb_file(raw, EPISODE, episodes)
    write_imdb_file(raw, RATINGS, ratings)


def show(
    *runs: tuple[int, float], per_season: int = 10, votes: int = 10_000, ripple: float = 0.2
) -> list[Episode]:
    """Episodes in order: each run is (count, level), with ratings alternating +-ripple."""
    levels = [level for count, level in runs for _ in range(count)]
    return [
        Episode(
            i // per_season + 1, i % per_season + 1, level + (ripple if i % 2 else -ripple), votes
        )
        for i, level in enumerate(levels)
    ]


def day(n: int) -> date:
    """Day n of a made-up history."""
    return HISTORY_START + timedelta(days=n)


def steady(tid: int, days: Iterable[int], *, votes: int, pace: int, rating: float) -> list[Row]:
    """A title gaining `pace` votes a day from `votes` on its first day, at one rating."""
    days = list(days)
    return [(tid, day(n), rating, votes + pace * (n - days[0])) for n in days]


def burst(rows: list[Row], at: int, extra: int, rating: float) -> list[Row]:
    """The same title with `extra` votes arriving on day `at`, after which it rates `rating`."""
    return [(t, d, rating, v + extra) if d >= day(at) else (t, d, r, v) for t, d, r, v in rows]


def season(show: int, episodes: Sequence[int], bombed: int, *, rating: float = 7.0) -> list[Row]:
    """A series page and weekly episodes from day 10, all watched through day 59.

    The episode with ID `bombed` draws over three times its siblings' votes at `rating`; the
    others rate 8.7 upward, in order.
    """
    rows = steady(show, range(60), votes=50_000, pace=100, rating=8.5)
    for k, tid in enumerate(episodes):
        first = 10 + 7 * k
        if tid == bombed:
            rows += steady(tid, range(first, 60), votes=3_000, pace=2_000, rating=rating)
        else:
            rows += steady(tid, range(first, 60), votes=1_000, pace=500, rating=8.7 + k / 10)
    return rows


def write_history(history: Path, rows: Sequence[Row]) -> None:
    """Save rows as one file per day, then fold them into months, as a sync does."""
    by_day: dict[date, list[Row]] = defaultdict(list)
    for r in rows:
        by_day[r[1]].append(r)
    (history / DAYS).mkdir(parents=True, exist_ok=True)
    with duckdb.connect() as con:
        for d, day_rows in by_day.items():
            con.execute(
                "CREATE OR REPLACE TABLE d AS SELECT CAST(unnest($tid) AS INTEGER) AS tid, "
                "CAST(unnest($date) AS DATE) AS date, "
                "CAST(unnest($rating) AS UTINYINT) AS rating_x10, "
                "CAST(unnest($votes) AS INTEGER) AS votes",
                {
                    "tid": [r[0] for r in day_rows],
                    "date": [r[1] for r in day_rows],
                    "rating": [round(r[2] * 10) for r in day_rows],
                    "votes": [r[3] for r in day_rows],
                },
            )
            dest = history / DAYS / f"{d.isoformat()}.parquet"
            con.execute(f"COPY (SELECT * FROM d ORDER BY tid) TO {quote(dest)} (FORMAT parquet)")
    compact(history)


def two_bombs(data_dir: Path) -> Path:
    """Tables where every title has 1,000 votes, and a history with two review bombs on
    Grey's Anatomy: S1E3 at launch, from day 25 to 37, and a burst of low votes on the
    series page on day 50."""
    raw = data_dir / "raw"
    raw.mkdir(parents=True)
    write_fixture(raw, votes=1_000)
    build_current(raw, data_dir / CURRENT_DB, downloads(raw))
    rows = season(1, [1_000_001 + k for k in range(6)], bombed=1_000_003)
    page = burst([r for r in rows if r[0] == 1], at=50, extra=5_000, rating=8.2)
    write_history(data_dir / "history", page + [r for r in rows if r[0] != 1])
    return data_dir
