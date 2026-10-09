import gzip
import json
from datetime import UTC, date, datetime
from email.utils import format_datetime
from pathlib import Path

import pytest

from getgood.config import EXPECTED_COLUMNS, IMDB_FILES
from getgood.fetch import Download
from getgood.validate import LAST_GOOD, Report, check_files, remember_good

BASICS, EPISODE, RATINGS = IMDB_FILES
TODAY = date(2026, 10, 9)

GOOD_ROWS = {
    BASICS: [
        "tt0000001\ttvSeries\tA Show\tA Show\t0\t2020\t\\N\t30\tDrama",
        "tt0000002\ttvEpisode\tPilot\tPilot\t0\t2020\t\\N\t30\tDrama",
        "tt0000003\ttvEpisode\tSecond\tSecond\t0\t2020\t\\N\t30\tDrama",
    ],
    EPISODE: ["tt0000002\ttt0000001\t1\t1", "tt0000003\ttt0000001\t1\t2"],
    RATINGS: ["tt0000001\t8.1\t1200", "tt0000002\t7.5\t600", "tt0000003\t7.9\t550"],
}


def write(raw: Path, name: str, rows: list[str], header: str | None = None) -> None:
    lines = [header if header is not None else "\t".join(EXPECTED_COLUMNS[name]), *rows]
    with gzip.open(raw / name, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def downloads(raw: Path, day: date = TODAY) -> list[Download]:
    stamp = format_datetime(
        datetime(day.year, day.month, day.day, 0, 39, 31, tzinfo=UTC), usegmt=True
    )
    return [Download(name, raw / name, True, 1, stamp) for name in IMDB_FILES]


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    for name, rows in GOOD_ROWS.items():
        write(tmp_path, name, rows)
    return tmp_path


def blocking(report: Report) -> list[str]:
    return [f"{f.file}: {f.message}" for f in report.findings if f.blocking]


def warnings(report: Report) -> list[str]:
    return [f"{f.file}: {f.message}" for f in report.findings if not f.blocking]


def test_good_files_pass_and_their_row_counts_are_kept(raw: Path) -> None:
    report = check_files(raw, downloads(raw), today=TODAY)

    assert report.ok
    assert report.findings == []
    assert report.rows == {BASICS: 3, EPISODE: 2, RATINGS: 3}


def test_changed_columns_stop_the_sync(raw: Path) -> None:
    write(raw, RATINGS, GOOD_ROWS[RATINGS], header="tconst\tnumVotes\taverageRating")

    report = check_files(raw, downloads(raw), today=TODAY)

    assert blocking(report) == [
        f"{RATINGS}: columns changed from tconst, averageRating, numVotes "
        "to tconst, numVotes, averageRating"
    ]


def test_a_file_that_isnt_gzip_stops_the_sync(raw: Path) -> None:
    (raw / EPISODE).write_bytes(b"<html>Service Unavailable</html>")

    report = check_files(raw, downloads(raw), today=TODAY)

    assert len(blocking(report)) == 1
    assert blocking(report)[0].startswith(f"{EPISODE}: can't be read")


def test_duplicate_ids_stop_the_sync(raw: Path) -> None:
    write(raw, RATINGS, [*GOOD_ROWS[RATINGS], "tt0000002\t7.4\t610"])

    assert blocking(check_files(raw, downloads(raw), today=TODAY)) == [
        f"{RATINGS}: IDs that appear more than once: 1"
    ]


def test_ratings_outside_the_scale_stop_the_sync(raw: Path) -> None:
    write(raw, RATINGS, ["tt0000001\t11.0\t1200", "tt0000002\tn/a\t600", "tt0000003\t7.9\t550"])

    assert blocking(check_files(raw, downloads(raw), today=TODAY)) == [
        f"{RATINGS}: ratings outside 1.0 to 10.0: 2"
    ]


def test_vote_counts_that_arent_whole_numbers_stop_the_sync(raw: Path) -> None:
    write(raw, RATINGS, ["tt0000001\t8.1\t1.2k", "tt0000002\t7.5\t600", "tt0000003\t7.9\t550"])

    assert blocking(check_files(raw, downloads(raw), today=TODAY)) == [
        f"{RATINGS}: vote counts that aren't whole numbers: 1"
    ]


def test_a_few_unparsed_episode_numbers_are_tolerated(raw: Path) -> None:
    rows = [f"tt1{i:06}\ttt0000001\t1\t{i}" for i in range(600)] + ["tt2000000\ttt0000001\tone\t1"]
    write(raw, EPISODE, rows)

    assert check_files(raw, downloads(raw), today=TODAY).ok


def test_many_unparsed_episode_numbers_stop_the_sync(raw: Path) -> None:
    write(raw, EPISODE, ["tt0000002\ttt0000001\tS1\tE1", "tt0000003\ttt0000001\t1\t2"])

    assert blocking(check_files(raw, downloads(raw), today=TODAY)) == [
        f"{EPISODE}: season and episode numbers that fail to parse: 50.00% (the limit is 0.1%)"
    ]


def remember(raw: Path, rows: dict[str, int], day: date) -> None:
    report = Report(rows=rows)
    remember_good(raw, downloads(raw, day), report)


def test_a_big_jump_in_row_count_stops_the_sync(raw: Path) -> None:
    remember(raw, {BASICS: 300, EPISODE: 2, RATINGS: 3}, date(2026, 10, 8))

    assert blocking(check_files(raw, downloads(raw), today=TODAY)) == [
        f"{BASICS}: row count moved -99.0% since the last good file (300 to 3); "
        "the limit is ±2% for files 1 day apart"
    ]


def test_the_row_count_allowance_grows_with_the_days_between_files(raw: Path) -> None:
    rows = [f"tt3{i:06}\ttt0000001\t1\t{i}" for i in range(105)]
    write(raw, EPISODE, rows)

    remember(raw, {BASICS: 3, EPISODE: 100, RATINGS: 3}, date(2026, 7, 11))
    assert check_files(raw, downloads(raw), today=TODAY).ok

    remember(raw, {BASICS: 3, EPISODE: 100, RATINGS: 3}, date(2026, 9, 29))
    assert not check_files(raw, downloads(raw), today=TODAY).ok


def test_files_already_checked_are_not_read_again(raw: Path) -> None:
    remember(raw, {BASICS: 3, EPISODE: 2, RATINGS: 3}, TODAY)
    (raw / EPISODE).write_bytes(b"not read again")

    report = check_files(raw, downloads(raw), today=TODAY)

    assert report.ok
    assert report.already_checked == list(IMDB_FILES)
    assert report.rows == {BASICS: 3, EPISODE: 2, RATINGS: 3}


def test_old_files_only_warn(raw: Path) -> None:
    report = check_files(raw, downloads(raw, date(2026, 10, 4)), today=TODAY)

    assert report.ok
    assert warnings(report) == [f"{name}: IMDb's newest file is 5 days old" for name in IMDB_FILES]


def test_ratings_with_too_few_votes_only_warn(raw: Path) -> None:
    write(raw, RATINGS, ["tt0000001\t8.1\t1200", "tt0000002\t7.5\t3", "tt0000003\t7.9\t550"])

    report = check_files(raw, downloads(raw), today=TODAY)

    assert report.ok
    assert warnings(report) == [
        f"{RATINGS}: ratings with fewer than 5 votes: 1 (IMDb may have changed its cut-off)"
    ]


def test_remember_good_saves_counts_and_dates(raw: Path) -> None:
    report = check_files(raw, downloads(raw), today=TODAY)
    remember_good(raw, downloads(raw), report)

    saved = json.loads((raw / LAST_GOOD).read_text())
    assert saved[RATINGS] == {
        "rows": 3,
        "as_of": "2026-10-09",
        "last_modified": "Fri, 09 Oct 2026 00:39:31 GMT",
    }


def test_a_failed_report_cannot_be_remembered(raw: Path) -> None:
    write(raw, RATINGS, GOOD_ROWS[RATINGS], header="wrong")
    report = check_files(raw, downloads(raw), today=TODAY)

    with pytest.raises(ValueError, match="blocking"):
        remember_good(raw, downloads(raw), report)
