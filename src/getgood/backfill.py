"""Fill the rating history: IMDb's own file for today, then the archive's copies of past days."""

import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from getgood.archive import ArchiveError, Capture, days_between, download, list_captures, probe_days
from getgood.config import ARCHIVE_PAUSE, HISTORY_START, PROBE_SETTLE_DAYS, ROW_COUNT_TOLERANCE
from getgood.fetch import Download
from getgood.history import compact, gaps, known_days, write_day
from getgood.validate import allowance, check_copy

STATE = "captures.json"
"""What happened to each archived copy, by capture time, so a backfill never repeats work."""
PROBED = "probed.json"
"""The copy the archive pointed to for each day probed, so a resumed backfill skips the days
it has settled."""

type Say = Callable[[str], None]


@dataclass
class Backfill:
    added: list[date] = field(default_factory=list[date])
    skipped: list[str] = field(default_factory=list[str])
    stopped: str | None = None


@dataclass(frozen=True)
class Span:
    days: int
    first: date | None
    last: date | None
    gaps: list[tuple[date, date]]


def save_today(
    raw_dir: Path, history: Path, current_db: Path, downloads: Iterable[Download]
) -> date | None:
    """Keep IMDb's own ratings file as its day's history, if that day isn't there yet."""
    ratings = next((d for d in downloads if d.name == "title.ratings.tsv.gz"), None)
    if ratings is None or ratings.as_of is None or ratings.as_of in known_days(history):
        return None
    write_day(raw_dir / ratings.name, ratings.as_of, history, current_db)
    return ratings.as_of


def backfill(
    client: httpx.Client,
    history: Path,
    current_db: Path,
    archive_dir: Path,
    *,
    until: date,
    since: date = HISTORY_START,
    say: Say = print,
    pause: float = ARCHIVE_PAUSE,
    sleep: Callable[[float], None] = time.sleep,
) -> Backfill:
    """Fetch the archived days the history lacks, one copy at a time, then fold them in.

    Stops early, keeping what it has, if the archive stays unreachable.
    """
    archive_dir.mkdir(parents=True, exist_ok=True)
    state: dict[str, dict[str, Any]] = _read_json(archive_dir / STATE)
    probed: dict[str, str | None] = _read_json(archive_dir / PROBED)
    known = known_days(history)
    result = Backfill()

    def save() -> None:
        _write_json(archive_dir / STATE, state)
        recent = (until - timedelta(days=PROBE_SETTLE_DAYS)).isoformat()
        _write_json(archive_dir / PROBED, {d: ts for d, ts in probed.items() if d < recent})

    def wait(seconds: float) -> None:
        if seconds >= 60:
            say(f"The archive asked us to slow down; waiting {seconds / 60:.0f} min.")
        sleep(seconds)

    try:
        try:
            captures: Iterable[Capture] = list_captures(client, since, sleep=wait)
        except ArchiveError:
            say("The archive's capture list is unavailable; checking day by day instead.")
            # settled: the archive had no copy, or the copy it pointed to has been dealt with
            settled = {d for d, ts in probed.items() if ts is None or ts in state}
            missing = [
                d
                for d in days_between(since, until)
                if d not in known and d.isoformat() not in settled
            ]
            captures = probe_days(client, missing, pause=pause, sleep=wait, found=probed)
        for capture in captures:
            if capture.timestamp in state:
                continue
            state[capture.timestamp] = _take(
                client, capture, history, current_db, archive_dir, known, state, wait
            )
            save()
            outcome = state[capture.timestamp]
            if outcome["status"] == "kept":
                result.added.append(date.fromisoformat(outcome["day"]))
                if len(result.added) % 25 == 0:
                    say(
                        f"Archive: {len(result.added)} days added so far (latest {outcome['day']})."
                    )
            elif outcome["status"] == "failed":
                result.skipped.append(f"copy {capture.timestamp}: {outcome['reason']}")
            sleep(pause)
    except ArchiveError as error:
        result.stopped = str(error)
    finally:
        save()
        compact(history)
    return result


def span(history: Path) -> Span:
    days = sorted(known_days(history))
    return Span(len(days), days[0] if days else None, days[-1] if days else None, gaps(days))


def _take(
    client: httpx.Client,
    capture: Capture,
    history: Path,
    current_db: Path,
    archive_dir: Path,
    known: set[date],
    state: dict[str, dict[str, Any]],
    wait: Callable[[float], None],
) -> dict[str, Any]:
    """Download one copy and keep it as a history day if it's new and passes the checks."""
    copy = download(client, capture, archive_dir, sleep=wait)
    try:
        if copy.day is None:
            return {"status": "failed", "reason": "no Last-Modified date from IMDb"}
        if copy.day in known:
            return {"status": "duplicate", "day": copy.day.isoformat()}
        if problems := check_copy(copy.path):
            return {"status": "failed", "reason": "; ".join(p.message for p in problems)}
        rows = write_day(copy.path, copy.day, history, current_db)
        if reason := _row_count_jump(copy.day, rows, state):
            (history / "days" / f"{copy.day.isoformat()}.parquet").unlink(missing_ok=True)
            return {"status": "failed", "reason": reason}
        known.add(copy.day)
        return {"status": "kept", "day": copy.day.isoformat(), "rows": rows}
    finally:
        copy.path.unlink(missing_ok=True)


def _row_count_jump(day: date, rows: int, state: dict[str, dict[str, Any]]) -> str | None:
    """Compare the kept rows with the nearest earlier kept day, allowing for the days between."""
    earlier = [
        (date.fromisoformat(v["day"]), v["rows"])
        for v in state.values()
        if v.get("status") == "kept" and date.fromisoformat(v["day"]) < day
    ]
    if not earlier:
        return None
    previous_day, previous_rows = max(earlier)
    if not previous_rows:
        return None
    days = (day - previous_day).days
    change = rows / previous_rows - 1
    allowed = allowance(ROW_COUNT_TOLERANCE, days)
    if abs(change) <= allowed:
        return None
    return f"in-scope rows moved {change:+.1%} from {previous_day} ({days} days earlier)"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError, json.JSONDecodeError:
        return {}


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)
