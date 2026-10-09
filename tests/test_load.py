from datetime import timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from getgood.load import build_current
from tests.helpers import TODAY, downloads, write_fixture

TOMORROW = TODAY + timedelta(days=1)


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
