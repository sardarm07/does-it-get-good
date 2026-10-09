"""Copies of IMDb's ratings file saved by the Internet Archive's Wayback Machine.

The archive has captured title.ratings.tsv.gz on about 1,400 days since 2022-02-22. This
module finds those copies and downloads them one request at a time, waiting minutes after
any sign of overload: the archive is a non-profit, and a full backfill is about 10 GB.
"""

import re
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from getgood import __version__
from getgood.config import ARCHIVE_PAUSE, ARCHIVE_WAITS, IMDB_BASE_URL

RATINGS_URL = IMDB_BASE_URL + "title.ratings.tsv.gz"
CDX_URL = "https://web.archive.org/cdx/search/cdx"
COPY_URL = "https://web.archive.org/web/{timestamp}id_/" + RATINGS_URL
USER_AGENT = (
    f"getgood/{__version__} (personal research; https://github.com/sardarm07/does-it-get-good)"
)
RETRYABLE = frozenset({429, 500, 502, 503, 504})
COPY_TIMESTAMP = re.compile(r"/web/(\d{14})id_/")

type Sleep = Callable[[float], None]


class ArchiveError(Exception):
    """The archive couldn't be reached, even after waiting."""


@dataclass(frozen=True)
class Capture:
    """A copy the archive saved, by when it saved it."""

    timestamp: str
    digest: str | None = None

    @property
    def captured(self) -> date:
        return date(int(self.timestamp[:4]), int(self.timestamp[4:6]), int(self.timestamp[6:8]))


@dataclass(frozen=True)
class Copy:
    """A downloaded copy, dated by IMDb's own Last-Modified header."""

    capture: Capture
    path: Path
    day: date | None
    etag: str | None


def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    """A client that names the project to the archive."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=httpx.Timeout(30.0, read=300.0),
        transport=transport,
    )


def list_captures(client: httpx.Client, since: date, *, sleep: Sleep = time.sleep) -> list[Capture]:
    """Every distinct copy captured since a date, from the archive's capture list.

    Raises ArchiveError if the list is unavailable, so the caller can probe day by day.
    """
    params = {
        "url": RATINGS_URL,
        "output": "json",
        "fl": "timestamp,digest",
        "filter": "statuscode:200",
        "collapse": "digest",
        "from": since.strftime("%Y%m%d"),
    }
    response = _request(
        client, "GET", CDX_URL, params=params, json=True, waits=ARCHIVE_WAITS[:1], sleep=sleep
    )
    try:
        rows: list[list[str]] = response.json()
    except ValueError as error:
        raise ArchiveError("the capture list didn't come back as JSON") from error
    return [Capture(timestamp, digest) for timestamp, digest in rows[1:]]


def probe(client: httpx.Client, day: date, *, sleep: Sleep = time.sleep) -> Capture | None:
    """The copy captured nearest to midday on `day`, from the archive's redirect to it."""
    url = COPY_URL.format(timestamp=day.strftime("%Y%m%d") + "120000")
    response = _request(client, "HEAD", url, sleep=sleep)
    if response.status_code == 404:
        return None
    if response.is_redirect and (found := COPY_TIMESTAMP.search(response.headers["location"])):
        return Capture(found.group(1))
    if response.status_code == 200 and "memento-datetime" in response.headers:
        saved = parsedate_to_datetime(response.headers["memento-datetime"])
        return Capture(saved.strftime("%Y%m%d%H%M%S"))
    raise ArchiveError(f"unexpected answer for {day}: HTTP {response.status_code}")


def probe_days(
    client: httpx.Client,
    days: Iterable[date],
    *,
    pause: float = ARCHIVE_PAUSE,
    sleep: Sleep = time.sleep,
) -> Iterator[Capture]:
    """Each distinct copy nearest to the given days, for when the capture list is down."""
    seen: set[str] = set()
    for day in days:
        capture = probe(client, day, sleep=sleep)
        sleep(pause)
        if capture is not None and capture.timestamp not in seen:
            seen.add(capture.timestamp)
            yield capture


def download(
    client: httpx.Client, capture: Capture, dest_dir: Path, *, sleep: Sleep = time.sleep
) -> Copy:
    """Save one copy into dest_dir and date it by IMDb's original Last-Modified header."""
    url = COPY_URL.format(timestamp=capture.timestamp)
    path = dest_dir / f"title.ratings.{capture.timestamp}.tsv.gz"
    part = path.with_name(path.name + ".part")
    problem = ""
    for wait in (0.0, *ARCHIVE_WAITS):
        if wait:
            sleep(wait)
        try:
            with client.stream("GET", url, follow_redirects=True) as response:
                if response.status_code in RETRYABLE:
                    problem = f"HTTP {response.status_code}"
                    continue
                if response.status_code != 200:
                    raise ArchiveError(f"copy {capture.timestamp}: HTTP {response.status_code}")
                with part.open("wb") as out:
                    for chunk in response.iter_raw():
                        out.write(chunk)
                expected = response.headers.get("content-length")
                if expected is not None and part.stat().st_size != int(expected):
                    problem = f"got {part.stat().st_size:,} of {int(expected):,} bytes"
                    continue
                part.replace(path)
                last_modified = response.headers.get("x-archive-orig-last-modified")
                return Copy(
                    capture=capture,
                    path=path,
                    day=parsedate_to_datetime(last_modified).date() if last_modified else None,
                    etag=response.headers.get("x-archive-orig-etag"),
                )
        except httpx.TransportError as error:
            problem = type(error).__name__
        finally:
            part.unlink(missing_ok=True)
    raise ArchiveError(f"copy {capture.timestamp}: still failing after waiting ({problem})")


def days_between(first: date, last: date) -> Iterator[date]:
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    json: bool = False,
    waits: tuple[float, ...] = ARCHIVE_WAITS,
    sleep: Sleep = time.sleep,
) -> httpx.Response:
    """One request, retried after each wait on a 429, a 5xx, a dropped connection, or an HTML
    page (the archive's "temporarily offline" notice) where JSON was expected."""
    problem = ""
    for wait in (0.0, *waits):
        if wait:
            sleep(wait)
        try:
            response = client.request(method, url, params=params)
        except httpx.TransportError as error:
            problem = type(error).__name__
            continue
        offline = json and "text/html" in response.headers.get("content-type", "")
        if response.status_code in RETRYABLE or offline:
            problem = f"HTTP {response.status_code}" + (", offline page" if offline else "")
            continue
        return response
    raise ArchiveError(f"{url}: still failing after waiting ({problem})")
