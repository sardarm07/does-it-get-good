"""Conditional downloads of IMDb's dataset files."""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

from getgood import __version__
from getgood.config import IMDB_BASE_URL, IMDB_FILES, RETRY_WAITS

RETRYABLE = frozenset({429, 500, 502, 503, 504})
USER_AGENT = f"getgood/{__version__} (personal, non-commercial use)"


class FetchError(Exception):
    """A file couldn't be downloaded."""


@dataclass(frozen=True)
class Download:
    """What a fetch did to one file."""

    name: str
    path: Path
    changed: bool
    size: int
    last_modified: str | None

    @property
    def as_of(self) -> date | None:
        """The date IMDb published the file, from its Last-Modified header."""
        if self.last_modified is None:
            return None
        return parsedate_to_datetime(self.last_modified).date()


def fetch(
    client: httpx.Client, name: str, raw_dir: Path, *, sleep: Callable[[float], None] = time.sleep
) -> Download:
    """Download one file into raw_dir, unless the copy there is still current."""
    path = raw_dir / name
    meta_path = raw_dir / f"{name}.meta.json"
    meta = _read_meta(meta_path) if path.exists() else {}
    headers: dict[str, str] = {}
    if etag := meta.get("etag"):
        headers["If-None-Match"] = etag
    if last_modified := meta.get("last_modified"):
        headers["If-Modified-Since"] = last_modified

    problem = "no attempt made"
    for wait in (0.0, *RETRY_WAITS):
        if wait:
            sleep(wait)
        try:
            with client.stream("GET", IMDB_BASE_URL + name, headers=headers) as response:
                if response.status_code in RETRYABLE:
                    problem = f"HTTP {response.status_code}"
                    continue
                if response.status_code == 304:
                    return Download(
                        name=name,
                        path=path,
                        changed=False,
                        size=path.stat().st_size,
                        last_modified=meta.get("last_modified"),
                    )
                if response.status_code != 200:
                    raise FetchError(f"{name}: HTTP {response.status_code}")
                _save(response, path)
                meta = {
                    "etag": response.headers.get("etag"),
                    "last_modified": response.headers.get("last-modified"),
                }
        except httpx.TransportError as error:
            problem = type(error).__name__
            continue
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        return Download(
            name=name,
            path=path,
            changed=True,
            size=path.stat().st_size,
            last_modified=meta["last_modified"],
        )
    raise FetchError(f"{name}: still failing after {len(RETRY_WAITS)} retries ({problem})")


def fetch_all(
    raw_dir: Path,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Download]:
    """Bring every file the project uses up to date, one at a time."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(30.0, read=120.0),
            follow_redirects=True,
        )
    try:
        return [fetch(client, name, raw_dir, sleep=sleep) for name in IMDB_FILES]
    finally:
        if own_client:
            client.close()


def _read_meta(meta_path: Path) -> dict[str, str | None]:
    try:
        return json.loads(meta_path.read_text())
    except FileNotFoundError, json.JSONDecodeError:
        return {}


def _save(response: httpx.Response, path: Path) -> None:
    """Write the body to a temporary file, then swap it in only once it's complete."""
    part = path.with_name(path.name + ".part")
    expected = response.headers.get("content-length")
    try:
        with part.open("wb") as out:
            for chunk in response.iter_raw():
                out.write(chunk)
        size = part.stat().st_size
        if expected is not None and size != int(expected):
            raise FetchError(f"{path.name}: got {size:,} of {int(expected):,} bytes")
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)
