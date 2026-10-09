import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from getgood.config import IMDB_BASE_URL, IMDB_FILES, RETRY_WAITS
from getgood.fetch import FetchError, fetch, fetch_all

NAME = "title.ratings.tsv.gz"
BODY = b"\x1f\x8b not really gzip, but bytes all the same"
VALIDATORS = {"etag": '"abc-1"', "last-modified": "Fri, 09 Oct 2026 00:39:31 GMT"}

type Reply = httpx.Response | Exception


def client_for(*replies: Reply, seen: list[httpx.Request] | None = None) -> httpx.Client:
    """A client whose server gives these replies in order."""
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        reply = queue.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    return httpx.Client(transport=httpx.MockTransport(handler))


def ok(body: bytes = BODY) -> httpx.Response:
    return httpx.Response(
        200, headers={**VALIDATORS, "content-length": str(len(body))}, stream=httpx.ByteStream(body)
    )


def no_sleep(seconds: float) -> None:
    pass


def test_first_download_saves_the_file_and_its_validators(tmp_path: Path) -> None:
    d = fetch(client_for(ok()), NAME, tmp_path, sleep=no_sleep)

    assert d.changed
    assert d.size == len(BODY)
    assert d.as_of == date(2026, 10, 9)
    assert (tmp_path / NAME).read_bytes() == BODY
    meta = json.loads((tmp_path / f"{NAME}.meta.json").read_text())
    assert meta == {"etag": '"abc-1"', "last_modified": "Fri, 09 Oct 2026 00:39:31 GMT"}


def test_an_unchanged_file_is_skipped(tmp_path: Path) -> None:
    fetch(client_for(ok()), NAME, tmp_path, sleep=no_sleep)
    seen: list[httpx.Request] = []

    d = fetch(client_for(httpx.Response(304), seen=seen), NAME, tmp_path, sleep=no_sleep)

    assert not d.changed
    assert d.as_of == date(2026, 10, 9)
    assert seen[0].headers["if-none-match"] == '"abc-1"'
    assert seen[0].headers["if-modified-since"] == "Fri, 09 Oct 2026 00:39:31 GMT"
    assert (tmp_path / NAME).read_bytes() == BODY


def test_a_missing_file_is_downloaded_again_even_with_validators(tmp_path: Path) -> None:
    fetch(client_for(ok()), NAME, tmp_path, sleep=no_sleep)
    (tmp_path / NAME).unlink()
    seen: list[httpx.Request] = []

    d = fetch(client_for(ok(), seen=seen), NAME, tmp_path, sleep=no_sleep)

    assert d.changed
    assert "if-none-match" not in seen[0].headers


def test_server_errors_and_dropped_connections_are_retried(tmp_path: Path) -> None:
    waits: list[float] = []
    replies = (httpx.Response(503), httpx.ConnectError("reset"), httpx.Response(429), ok())

    d = fetch(client_for(*replies), NAME, tmp_path, sleep=waits.append)

    assert d.changed
    assert waits == list(RETRY_WAITS)


def test_it_gives_up_after_the_last_retry(tmp_path: Path) -> None:
    replies = [httpx.Response(503) for _ in range(len(RETRY_WAITS) + 1)]

    with pytest.raises(FetchError, match=r"after 3 retries \(HTTP 503\)"):
        fetch(client_for(*replies), NAME, tmp_path, sleep=no_sleep)


def test_other_errors_stop_at_once(tmp_path: Path) -> None:
    waits: list[float] = []

    with pytest.raises(FetchError, match="HTTP 404"):
        fetch(client_for(httpx.Response(404)), NAME, tmp_path, sleep=waits.append)
    assert waits == []


def test_a_short_download_keeps_the_old_copy(tmp_path: Path) -> None:
    fetch(client_for(ok()), NAME, tmp_path, sleep=no_sleep)
    short = httpx.Response(
        200,
        headers={**VALIDATORS, "etag": '"abc-2"', "content-length": "9999"},
        stream=httpx.ByteStream(b"cut off"),
    )

    with pytest.raises(FetchError, match="got 7 of 9,999 bytes"):
        fetch(client_for(short), NAME, tmp_path, sleep=no_sleep)

    assert (tmp_path / NAME).read_bytes() == BODY
    assert not (tmp_path / f"{NAME}.part").exists()
    assert json.loads((tmp_path / f"{NAME}.meta.json").read_text())["etag"] == '"abc-1"'


def test_fetch_all_gets_every_file_in_order(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []
    client = client_for(*(ok() for _ in IMDB_FILES), seen=seen)

    downloads = fetch_all(tmp_path / "raw", client=client, sleep=no_sleep)

    assert [d.name for d in downloads] == list(IMDB_FILES)
    assert [str(r.url) for r in seen] == [IMDB_BASE_URL + name for name in IMDB_FILES]
    assert all((tmp_path / "raw" / name).exists() for name in IMDB_FILES)
