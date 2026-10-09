from collections.abc import Iterator

import duckdb
import pytest

from getgood.load import SEARCH_KEY
from getgood.search import find

# Made-up IDs and vote counts; only the titles and years are real.
SHOWS = [
    (1, "Parks and Recreation", 2009, 2015, 300_000),
    (2, "The Office", 2005, 2013, 750_000),
    (3, "The Office", 2001, 2003, 110_000),
    (4, "The Office", 2019, 2019, 900),
    (5, "Agents of S.H.I.E.L.D.", 2013, 2020, 230_000),
    (6, "Friends", 1994, 2004, 1_100_000),
    (7, "Friends", 2011, 2012, 40),
    (8, "Law & Order", 1990, None, 50_000),
    (9, "Grey's Anatomy", 2005, None, 340_000),
    (10, "Parks", 2018, 2018, 2_000),
]


@pytest.fixture
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect() as c:
        c.execute(
            "CREATE TABLE shows (tid INTEGER, title VARCHAR, start_year SMALLINT, "
            "end_year SMALLINT, votes INTEGER)"
        )
        c.executemany("INSERT INTO shows VALUES (?, ?, ?, ?, ?)", SHOWS)
        c.execute(f"""
            CREATE TABLE series AS
            SELECT tid, title, 'tvSeries' AS kind, start_year, end_year, NULL AS genres,
                   {SEARCH_KEY.format("title")} AS search_key
            FROM shows""")
        c.execute(
            "CREATE TABLE ratings AS SELECT tid, 80::UTINYINT AS rating_x10, votes FROM shows"
        )
        yield c


def test_the_start_of_a_title_finds_the_show(con: duckdb.DuckDBPyConnection) -> None:
    found = find(con, "parks and rec")

    assert found.best is not None and found.best.title == "Parks and Recreation"
    assert not found.ambiguous


def test_a_typo_still_finds_the_show(con: duckdb.DuckDBPyConnection) -> None:
    found = find(con, "parks and recration")

    assert found.best is not None and found.best.title == "Parks and Recreation"


def test_the_office_asks_whether_you_meant_the_us_or_uk_show(
    con: duckdb.DuckDBPyConnection,
) -> None:
    found = find(con, "the office")

    assert found.ambiguous
    assert [(m.title, m.years) for m in found.choices] == [
        ("The Office", "2005–2013"),
        ("The Office", "2001–2003"),
    ]


def test_a_year_settles_it(con: duckdb.DuckDBPyConnection) -> None:
    found = find(con, "The Office", year=2001)

    assert found.best is not None and found.best.tid == 3
    assert not found.ambiguous


def test_punctuation_and_ampersands_dont_matter(con: duckdb.DuckDBPyConnection) -> None:
    titles = [
        (best.title if (best := find(con, name).best) else None)
        for name in ("agents of shield", "greys anatomy", "law and order")
    ]

    assert titles == ["Agents of S.H.I.E.L.D.", "Grey's Anatomy", "Law & Order"]


def test_an_obscure_namesake_doesnt_need_a_question(con: duckdb.DuckDBPyConnection) -> None:
    found = find(con, "friends")

    assert found.best is not None and found.best.years == "1994–2004"
    assert not found.ambiguous


def test_an_exact_title_beats_a_longer_one(con: duckdb.DuckDBPyConnection) -> None:
    found = find(con, "parks")

    assert found.best is not None and found.best.title == "Parks"
    assert not found.ambiguous


def test_an_imdb_id_finds_the_show_directly(con: duckdb.DuckDBPyConnection) -> None:
    found = find(con, "tt0000009")

    assert found.best is not None and found.best.title == "Grey's Anatomy"
    assert found.best.imdb_id == "tt0000009"


def test_nothing_close_finds_nothing(con: duckdb.DuckDBPyConnection) -> None:
    assert find(con, "zzqqxx").best is None
    assert find(con, "   ").best is None
