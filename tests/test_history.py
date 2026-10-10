from datetime import date
from pathlib import Path

import duckdb
import pytest

from getgood.config import CURRENT_DB
from getgood.history import DAYS, compact, gaps, known_days, source, upgrade, write_day
from getgood.load import build_current
from tests.helpers import RATINGS, downloads, write_fixture, write_imdb_file


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Raw files, the current tables built from them, and an empty history folder."""
    raw = tmp_path / "raw"
    raw.mkdir()
    write_fixture(raw)
    build_current(raw, tmp_path / CURRENT_DB, downloads(raw))
    return raw, tmp_path / CURRENT_DB, tmp_path / "history"


def ratings_on(raw: Path, votes: int) -> Path:
    """A ratings file where every title (in scope or not) has these votes."""
    rows = [f"tt000000{n}\t8.0\t{votes}" for n in range(1, 6)]
    rows += [f"tt{show}00000{k}\t7.5\t{votes}" for show in (1, 2, 3, 4) for k in range(1, 7)]
    write_imdb_file(raw, RATINGS, rows)
    return raw / RATINGS


def rows(sql: str) -> list[tuple[object, ...]]:
    with duckdb.connect() as con:
        return con.execute(sql).fetchall()


def test_a_day_keeps_only_in_scope_titles(setup: tuple[Path, Path, Path]) -> None:
    raw, current, history = setup

    kept = write_day(ratings_on(raw, 100), date(2023, 1, 30), history, current)

    # in scope: series 1 and 4 with their 6 numbered episodes each
    assert kept == 14
    day_file = history / DAYS / "2023-01-30.parquet"
    assert rows(f"SELECT DISTINCT date FROM '{day_file}'") == [(date(2023, 1, 30),)]
    assert rows(f"SELECT count(*) FROM '{day_file}' WHERE tid IN (2, 3, 5)") == [(0,)]
    assert list((history / DAYS).iterdir()) == [day_file]


def test_every_row_names_its_series(setup: tuple[Path, Path, Path]) -> None:
    raw, current, history = setup

    write_day(ratings_on(raw, 100), date(2023, 1, 30), history, current)

    # a series page names itself; episode tt{show}00000{k} belongs to series tt000000{show}
    day_file = history / DAYS / "2023-01-30.parquet"
    misplaced = (
        f"SELECT count(*) FROM '{day_file}' "
        "WHERE series <> CASE WHEN tid < 1000000 THEN tid ELSE tid // 1000000 END"
    )
    assert rows(misplaced) == [(0,)]
    assert rows(f"SELECT DISTINCT series FROM '{day_file}' ORDER BY 1") == [(1,), (4,)]


def test_days_fold_into_their_months_sorted_by_series(setup: tuple[Path, Path, Path]) -> None:
    raw, current, history = setup
    for day, votes in ((date(2023, 12, 31), 100), (date(2024, 1, 1), 110), (date(2023, 12, 2), 90)):
        write_day(ratings_on(raw, votes), day, history, current)

    assert compact(history) == ["2023-12", "2024-01"]

    assert sorted(p.name for p in history.glob("*.parquet")) == [
        "2023-12.parquet",
        "2024-01.parquet",
    ]
    assert list((history / DAYS).iterdir()) == []
    ordered = rows(f"SELECT series, tid, date FROM '{history / '2023-12.parquet'}'")
    assert ordered == sorted(ordered)
    assert known_days(history) == {date(2023, 12, 2), date(2023, 12, 31), date(2024, 1, 1)}


def test_a_later_compaction_adds_to_the_month(setup: tuple[Path, Path, Path]) -> None:
    raw, current, history = setup
    write_day(ratings_on(raw, 100), date(2023, 1, 30), history, current)
    compact(history)
    write_day(ratings_on(raw, 120), date(2023, 1, 31), history, current)

    assert compact(history) == ["2023-01"]

    assert rows(f"SELECT date, max(votes) FROM {source(history)} GROUP BY 1 ORDER BY 1") == [
        (date(2023, 1, 30), 100),
        (date(2023, 1, 31), 120),
    ]
    assert known_days(history) == {date(2023, 1, 30), date(2023, 1, 31)}


def test_a_day_already_held_keeps_its_first_copy(setup: tuple[Path, Path, Path]) -> None:
    raw, current, history = setup
    write_day(ratings_on(raw, 100), date(2023, 1, 30), history, current)
    compact(history)
    write_day(ratings_on(raw, 120), date(2023, 1, 30), history, current)

    assert compact(history) == []

    assert list((history / DAYS).iterdir()) == []
    assert rows(f"SELECT date, count(*), max(votes) FROM {source(history)} GROUP BY 1") == [
        (date(2023, 1, 30), 14, 100)
    ]


def test_days_waiting_to_be_folded_are_read_too(setup: tuple[Path, Path, Path]) -> None:
    raw, current, history = setup
    write_day(ratings_on(raw, 100), date(2023, 1, 30), history, current)
    compact(history)
    write_day(ratings_on(raw, 120), date(2023, 2, 1), history, current)

    assert known_days(history) == {date(2023, 1, 30), date(2023, 2, 1)}
    assert rows(f"SELECT count(DISTINCT date) FROM {source(history)}") == [(2,)]


def test_files_from_before_rows_named_their_series_are_upgraded(
    setup: tuple[Path, Path, Path],
) -> None:
    raw, current, history = setup
    write_day(ratings_on(raw, 100), date(2023, 1, 30), history, current)
    compact(history)
    write_day(ratings_on(raw, 120), date(2023, 1, 31), history, current)
    month, day_file = history / "2023-01.parquet", history / DAYS / "2023-01-31.parquet"
    with duckdb.connect() as con:  # as they were: no series, sorted by title
        for path, listed in ((month, "2023-01-30"), (day_file, None)):
            metadata = f", KV_METADATA {{getgood_days: '{listed}'}}" if listed else ""
            con.execute(
                f"COPY (SELECT tid, date, rating_x10, votes FROM '{path}' ORDER BY tid, date) "
                f"TO '{path}.old' (FORMAT parquet{metadata})"
            )
            Path(f"{path}.old").replace(path)

    assert upgrade(history, current) == ["2023-01.parquet", "2023-01-31.parquet"]

    assert known_days(history) == {date(2023, 1, 30), date(2023, 1, 31)}
    ordered = rows(f"SELECT series, tid, date FROM '{month}'")
    assert ordered == sorted(ordered)
    assert {series for series, _, _ in ordered} == {1, 4}
    assert upgrade(history, current) == []
    assert compact(history) == ["2023-01"]
    assert rows(f"SELECT count(*) FROM {source(history)}") == [(28,)]


def test_an_empty_history_has_no_source(tmp_path: Path) -> None:
    assert source(tmp_path / "history") is None
    assert known_days(tmp_path / "history") == set()


def test_gaps_longer_than_three_days_are_listed() -> None:
    days = [date(2024, 6, 1), date(2024, 6, 4), date(2024, 6, 30), date(2024, 7, 1)]

    assert gaps(days) == [(date(2024, 6, 4), date(2024, 6, 30))]
