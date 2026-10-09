from datetime import timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from getgood.config import IMDB_FILES
from getgood.load import build_current
from tests.helpers import TODAY, downloads, write_imdb_file

BASICS, EPISODE, RATINGS = IMDB_FILES
TOMORROW = TODAY + timedelta(days=1)


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


def rows(db: Path, sql: str) -> list[tuple[Any, ...]]:
    with duckdb.connect(str(db), read_only=True) as con:
        return con.execute(sql).fetchall()


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    write_fixture(tmp_path)
    return tmp_path


def test_only_in_scope_series_are_kept(raw: Path) -> None:
    db = raw / "current.duckdb"
    built = build_current(raw, db, downloads(raw))

    assert built.ok and not built.skipped
    assert (built.series, built.rated_episodes, built.as_of) == (2, 12, TODAY)
    assert rows(db, "SELECT tid, title, kind, start_year, end_year, search_key FROM series") == [
        (1, "Grey's Anatomy", "tvSeries", 2005, None, "grey s anatomy"),
        (4, "Café Noir", "tvMiniSeries", 2020, 2020, "cafe noir"),
    ]


def test_episodes_need_a_season_from_1_and_a_number(raw: Path) -> None:
    db = raw / "current.duckdb"
    build_current(raw, db, downloads(raw))

    assert rows(
        db, "SELECT series, count(*), min(season), max(episode) FROM episodes GROUP BY 1"
    ) == [
        (1, 6, 1, 6),
        (4, 6, 1, 6),
    ]


def test_ratings_are_stored_as_integers_times_ten(raw: Path) -> None:
    db = raw / "current.duckdb"
    build_current(raw, db, downloads(raw))

    assert rows(db, "SELECT tid, rating_x10, votes FROM ratings WHERE tid IN (1, 1000003)") == [
        (1, 80, 100),
        (1000003, 73, 100),
    ]
    assert rows(db, "SELECT count(*) FROM ratings") == [(14,)]
    assert rows(db, "SELECT DISTINCT typeof(tid) FROM ratings") == [("INTEGER",)]


def test_the_same_files_are_not_built_twice(raw: Path) -> None:
    db = raw / "current.duckdb"
    build_current(raw, db, downloads(raw))

    again = build_current(raw, db, downloads(raw))

    assert again.skipped
    assert (again.series, again.rated_episodes) == (2, 12)


def test_building_twice_gives_the_same_tables(raw: Path) -> None:
    db = raw / "current.duckdb"
    tables = ("series", "episodes", "ratings")
    build_current(raw, db, downloads(raw))
    first = {t: rows(db, f"SELECT * FROM {t}") for t in tables}

    rebuilt = build_current(raw, db, downloads(raw, TOMORROW))

    assert not rebuilt.skipped
    assert {t: rows(db, f"SELECT * FROM {t}") for t in tables} == first


def test_a_big_drop_in_scope_keeps_the_old_tables(raw: Path) -> None:
    db = raw / "current.duckdb"
    build_current(raw, db, downloads(raw))
    write_fixture(raw, cafe_genres="News")

    stopped = build_current(raw, db, downloads(raw, TOMORROW))

    assert [f"{f.file}: {f.message}" for f in stopped.findings] == [
        "in-scope series: count moved -50.0% since the last sync (2 to 1); "
        "the limit is ±3% for files 1 day apart"
    ]
    assert rows(db, "SELECT count(*) FROM series") == [(2,)]
    assert not (raw / "current.duckdb.building").exists()


def test_widespread_vote_losses_keep_the_old_tables(raw: Path) -> None:
    db = raw / "current.duckdb"
    build_current(raw, db, downloads(raw))
    write_fixture(raw, votes=50)

    stopped = build_current(raw, db, downloads(raw, TOMORROW))

    assert [f"{f.file}: {f.message}" for f in stopped.findings] == [
        "ratings: titles that lost votes since the last sync: 100.0% (14 of 14); "
        "the limit is 1% for files 1 day apart"
    ]
    assert rows(db, "SELECT DISTINCT votes FROM ratings") == [(100,)]
