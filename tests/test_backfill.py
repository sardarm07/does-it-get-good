import gzip
from datetime import UTC, date, datetime
from email.utils import format_datetime
from pathlib import Path

import httpx
import pytest

from getgood import archive
from getgood.backfill import STATE, Backfill, backfill, save_today, span
from getgood.config import CURRENT_DB
from getgood.history import known_days
from getgood.load import build_current
from tests.helpers import RATINGS, downloads, write_fixture

HEADER = "tconst\taverageRating\tnumVotes"


def ratings_file(votes: int, header: str = HEADER) -> bytes:
    rows = [f"tt000000{n}\t8.0\t{votes}" for n in range(1, 6)]
    rows += [f"tt{show}00000{k}\t7.5\t{votes}" for show in (1, 2, 3, 4) for k in range(1, 7)]
    return gzip.compress(("\n".join([header, *rows]) + "\n").encode())


def imdb_date(day: date) -> str:
    return format_datetime(datetime(day.year, day.month, day.day, 13, 15, tzinfo=UTC), usegmt=True)


class FakeArchive:
    """Serves a capture list (or an offline page), redirects for probes, and copies."""

    def __init__(
        self, copies: dict[str, tuple[date, bytes]], *, list_offline: bool = False
    ) -> None:
        self.copies = copies
        self.list_offline = list_offline
        self.downloads: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(archive.CDX_URL):
            if self.list_offline:
                return httpx.Response(200, html="<title>Temporarily Offline</title>")
            rows = [["timestamp", "digest"]] + [[ts, ts] for ts in sorted(self.copies)]
            return httpx.Response(200, json=rows)
        timestamp = url.split("/web/")[1][:14]
        if request.method == "HEAD":
            day = timestamp[:8]
            nearest = [ts for ts in sorted(self.copies) if ts.startswith(day)]
            if not nearest:
                return httpx.Response(404)
            return httpx.Response(
                302, headers={"location": archive.COPY_URL.format(timestamp=nearest[0])}
            )
        self.downloads.append(timestamp)
        day, body = self.copies[timestamp]
        return httpx.Response(
            200,
            headers={
                "x-archive-orig-last-modified": imdb_date(day),
                "content-length": str(len(body)),
            },
            stream=httpx.ByteStream(body),
        )


@pytest.fixture
def data(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_fixture(raw)
    build_current(raw, tmp_path / CURRENT_DB, downloads(raw))
    return tmp_path


def run(data: Path, fake: FakeArchive, until: date = date(2023, 2, 2)) -> Backfill:
    messages: list[str] = []
    with archive.client(httpx.MockTransport(fake)) as http:
        result = backfill(
            http,
            data / "history",
            data / CURRENT_DB,
            data / "archive",
            until=until,
            since=date(2023, 1, 30),
            say=messages.append,
            pause=0,
            sleep=lambda seconds: None,
        )
    return result


def test_each_distinct_day_is_added_once(data: Path) -> None:
    fake = FakeArchive(
        {
            "20230131013404": (date(2023, 1, 30), ratings_file(100)),
            "20230201013406": (date(2023, 1, 31), ratings_file(101)),
            "20230202013411": (date(2023, 1, 31), ratings_file(101)),  # the same IMDb file again
        }
    )

    result = run(data, fake)

    assert result.added == [date(2023, 1, 30), date(2023, 1, 31)]
    assert known_days(data / "history") == {date(2023, 1, 30), date(2023, 1, 31)}
    assert not list((data / "archive").glob("*.gz"))


def test_a_second_backfill_downloads_nothing_again(data: Path) -> None:
    fake = FakeArchive({"20230131013404": (date(2023, 1, 30), ratings_file(100))})
    run(data, fake)

    again = run(data, fake)

    assert again.added == []
    assert fake.downloads == ["20230131013404"]
    assert (data / "archive" / STATE).exists()


def test_without_the_capture_list_it_checks_day_by_day(data: Path) -> None:
    fake = FakeArchive(
        {
            "20230131013404": (date(2023, 1, 30), ratings_file(100)),
            "20230202013411": (date(2023, 2, 1), ratings_file(102)),
        },
        list_offline=True,
    )

    result = run(data, fake)

    assert result.added == [date(2023, 1, 30), date(2023, 2, 1)]


def test_a_copy_that_fails_its_checks_is_skipped_not_fatal(data: Path) -> None:
    fake = FakeArchive(
        {
            "20230131013404": (
                date(2023, 1, 30),
                ratings_file(100, header="tconst\tnumVotes\taverageRating"),
            ),
            "20230201013406": (date(2023, 1, 31), ratings_file(101)),
        }
    )

    result = run(data, fake)

    assert result.added == [date(2023, 1, 31)]
    assert len(result.skipped) == 1 and "columns changed" in result.skipped[0]


def test_a_day_whose_row_count_jumps_is_skipped(data: Path) -> None:
    rows = [f"tt000000{n}\t8.0\t100" for n in range(1, 6)]
    half = gzip.compress(("\n".join([HEADER, *rows]) + "\n").encode())
    fake = FakeArchive(
        {
            "20230131013404": (date(2023, 1, 30), ratings_file(100)),
            "20230201013406": (date(2023, 1, 31), half),
        }
    )

    result = run(data, fake)

    assert result.added == [date(2023, 1, 30)]
    assert "in-scope rows moved" in result.skipped[0]


def test_imdbs_own_file_becomes_todays_history(data: Path) -> None:
    raw = data / "raw"
    (raw / RATINGS).write_bytes(ratings_file(100))

    day = save_today(raw, data / "history", data / CURRENT_DB, downloads(raw))

    assert day == date(2026, 10, 9)
    assert save_today(raw, data / "history", data / CURRENT_DB, downloads(raw)) is None
    assert span(data / "history").days == 1
