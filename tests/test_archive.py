from datetime import date
from pathlib import Path

import httpx
import pytest

from getgood.archive import (
    USER_AGENT,
    ArchiveError,
    Capture,
    client,
    days_between,
    download,
    list_captures,
    probe,
    probe_days,
)
from getgood.config import ARCHIVE_WAITS

COPY = "https://web.archive.org/web/{}id_/https://datasets.imdbws.com/title.ratings.tsv.gz"
BODY = b"\x1f\x8b archived bytes"

type Reply = httpx.Response | Exception


def archive_for(*replies: Reply, seen: list[httpx.Request] | None = None) -> httpx.Client:
    """A client whose archive gives these replies in order."""
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return client(httpx.MockTransport(handler))


def copy_reply(body: bytes = BODY, extra: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        200,
        headers={
            "x-archive-orig-last-modified": "Mon, 30 Jan 2023 13:15:52 GMT",
            "x-archive-orig-etag": '"abc-1"',
            "content-length": str(len(body)),
            **(extra or {}),
        },
        stream=httpx.ByteStream(body),
    )


def no_sleep(seconds: float) -> None:
    pass


def test_the_capture_list_gives_one_entry_per_distinct_file() -> None:
    seen: list[httpx.Request] = []
    rows = [["timestamp", "digest"], ["20230131013404", "AAA"], ["20230201013406", "BBB"]]

    captures = list_captures(
        archive_for(httpx.Response(200, json=rows), seen=seen), date(2022, 2, 22)
    )

    assert captures == [Capture("20230131013404", "AAA"), Capture("20230201013406", "BBB")]
    params = seen[0].url.params
    assert (params["collapse"], params["from"], params["filter"]) == (
        "digest",
        "20220222",
        "statuscode:200",
    )
    assert seen[0].headers["user-agent"] == USER_AGENT


def test_an_offline_capture_list_is_an_error_after_one_wait() -> None:
    offline = httpx.Response(200, html="<title>Internet Archive: Temporarily Offline</title>")
    waits: list[float] = []

    with pytest.raises(ArchiveError, match="offline page"):
        list_captures(archive_for(offline, offline), date(2022, 2, 22), sleep=waits.append)
    assert waits == [ARCHIVE_WAITS[0]]


def test_a_probe_reads_the_redirect_to_the_nearest_copy() -> None:
    redirect = httpx.Response(302, headers={"location": COPY.format("20230131013404")})

    assert probe(archive_for(redirect), date(2023, 1, 31)) == Capture("20230131013404")
    assert probe(archive_for(httpx.Response(404)), date(2023, 1, 31)) is None


def test_probing_days_skips_a_copy_already_found_and_pauses_between_requests() -> None:
    first = httpx.Response(302, headers={"location": COPY.format("20230131013404")})
    same = httpx.Response(302, headers={"location": COPY.format("20230131013404")})
    second = httpx.Response(302, headers={"location": COPY.format("20230202013411")})
    pauses: list[float] = []
    days = list(days_between(date(2023, 1, 31), date(2023, 2, 2)))

    captures = list(
        probe_days(archive_for(first, same, second), days, pause=2.0, sleep=pauses.append)
    )

    assert captures == [Capture("20230131013404"), Capture("20230202013411")]
    assert pauses == [2.0, 2.0, 2.0]


def test_a_copy_is_dated_by_imdbs_own_date(tmp_path: Path) -> None:
    copy = download(archive_for(copy_reply()), Capture("20230131013404"), tmp_path)

    assert copy.day == date(2023, 1, 30)
    assert copy.etag == '"abc-1"'
    assert copy.path.read_bytes() == BODY


def test_a_429_waits_before_trying_again(tmp_path: Path) -> None:
    waits: list[float] = []

    copy = download(
        archive_for(httpx.Response(429), copy_reply()),
        Capture("20230131013404"),
        tmp_path,
        sleep=waits.append,
    )

    assert copy.day == date(2023, 1, 30)
    assert waits == [ARCHIVE_WAITS[0]]


def test_a_copy_that_keeps_coming_up_short_leaves_nothing_behind(tmp_path: Path) -> None:
    short = [copy_reply(extra={"content-length": "9999"}) for _ in range(len(ARCHIVE_WAITS) + 1)]

    with pytest.raises(ArchiveError, match="got 17 of 9,999 bytes"):
        download(archive_for(*short), Capture("20230131013404"), tmp_path, sleep=no_sleep)
    assert list(tmp_path.iterdir()) == []


def test_days_between_includes_both_ends() -> None:
    assert list(days_between(date(2024, 2, 28), date(2024, 3, 1))) == [
        date(2024, 2, 28),
        date(2024, 2, 29),
        date(2024, 3, 1),
    ]
