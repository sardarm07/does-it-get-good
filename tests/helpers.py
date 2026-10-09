"""Tiny files in IMDb's format for tests. They never hold real IMDb data."""

import gzip
from datetime import UTC, date, datetime
from email.utils import format_datetime
from pathlib import Path

from getgood.analysis.verdicts import Episode
from getgood.config import EXPECTED_COLUMNS, IMDB_FILES
from getgood.fetch import Download

TODAY = date(2026, 10, 9)
BASICS, EPISODE, RATINGS = IMDB_FILES


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
