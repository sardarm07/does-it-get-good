"""Tiny files in IMDb's format for tests. They never hold real IMDb data."""

import gzip
from datetime import UTC, date, datetime
from email.utils import format_datetime
from pathlib import Path

from getgood.config import EXPECTED_COLUMNS, IMDB_FILES
from getgood.fetch import Download

TODAY = date(2026, 10, 9)


def write_imdb_file(raw: Path, name: str, rows: list[str], header: str | None = None) -> None:
    """Write a gzipped TSV the way IMDb does: a header line, then one line per row."""
    lines = [header if header is not None else "\t".join(EXPECTED_COLUMNS[name]), *rows]
    with gzip.open(raw / name, "wt", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def downloads(raw: Path, day: date = TODAY) -> list[Download]:
    """What fetch_all would report for files IMDb published on this day."""
    published = datetime(day.year, day.month, day.day, 0, 39, 31, tzinfo=UTC)
    stamp = format_datetime(published, usegmt=True)
    return [Download(name, raw / name, True, 1, stamp) for name in IMDB_FILES]
