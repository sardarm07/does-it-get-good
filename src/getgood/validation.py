"""Score getgood against hand-labelled turning points and documented review bombs:
make validate."""

import re
import sys
from collections.abc import Collection, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb
import yaml

from getgood.analysis.bombs import Event
from getgood.analysis.verdicts import Episode, Verdict, judge
from getgood.config import CURRENT_DB, DATA_DIR, MAX_GAP_DAYS
from getgood.history import known_days
from getgood.report import EPISODES, history_of, label, labels_of, what, when

LABELS = Path(__file__).resolve().parents[2] / "validation" / "turning_points.yaml"
KNOWN_BOMBS = LABELS.with_name("known_bombs.yaml")
FACTS = ("gets_good_at", "good_from_start", "slump_from", "low_point")
TOLERANCE = 3
"""How many episodes a turn or slump may be from its label and still count."""
LOW_POINT_TOLERANCE = 1
TARGET = 0.8
"""The share of labelled shows that must pass: M1's gate is 24 of 30."""
BOMB_TARGET = 0.8
"""The share of known bombs the history covers that must be found: M3's gate is 8 of 10."""
SEASON = re.compile(r"S\d+")


def load_labels(path: Path = LABELS) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = yaml.safe_load(path.read_text())
    return labels


def describe(verdict: Verdict) -> str:
    if verdict.kind == "gets_good":
        return f"gets good at {verdict.at}"
    return verdict.kind.replace("_", " ")


def misses(label: dict[str, Any], episodes: Sequence[Episode], verdict: Verdict) -> list[str]:
    """The labelled facts the verdict gets wrong; none means the show passes."""
    position = {e.label: i for i, e in enumerate(episodes)}

    def near(a: str, b: str, tolerance: int) -> bool:
        return abs(position[a] - position[b]) <= tolerance

    found: list[str] = []
    at = label.get("gets_good_at")
    if at and (
        verdict.kind != "gets_good" or not verdict.at or not near(verdict.at, at, TOLERANCE)
    ):
        found.append(f"expected gets good at {at}, got {describe(verdict)}")
    if label.get("good_from_start") and verdict.kind not in ("good_from_start", "steady"):
        found.append(f"expected good from the start, got {describe(verdict)}")
    start = label.get("slump_from")
    if start and not any(near(s.start, start, TOLERANCE) for s in verdict.slumps):
        got = ", ".join(f"{s.start}–{s.end}" for s in verdict.slumps) or "none"
        found.append(f"expected a slump from {start}, got slumps: {got}")
    low = label.get("low_point")
    if low and not any(near(p, low, LOW_POINT_TOLERANCE) for p in verdict.low_points):
        got = ", ".join(verdict.low_points) or "none"
        found.append(f"expected a low point at {low}, got low points: {got}")
    return found


def episodes_of(con: duckdb.DuckDBPyConnection, imdb_id: str) -> list[Episode]:
    rows = con.execute(EPISODES, [int(imdb_id.removeprefix("tt"))]).fetchall()
    return [
        Episode(season, number, rating_x10 / 10, votes)
        for season, number, rating_x10, votes in rows
    ]


def load_known_bombs(path: Path = KNOWN_BOMBS) -> list[dict[str, Any]]:
    bombs: list[dict[str, Any]] = yaml.safe_load(path.read_text())
    return bombs


def touches(event: Event, titles: Collection[str], labels: Mapping[int, str]) -> bool:
    """Whether an event hit one of these titles: "series", an episode, or a whole season."""
    for t in event.titles:
        name = label(labels, t)
        for wanted in titles:
            if name == wanted or (SEASON.fullmatch(wanted) and name.startswith(wanted + "E")):
                return True
    return False


def found_bomb(
    known: Mapping[str, Any], events: Sequence[Event], labels: Mapping[int, str]
) -> Event | None:
    """The first review-bomb event on the known bomb's titles within its dates."""
    for e in events:
        if (
            e.kind == "bomb"
            and e.start <= known["to"]
            and e.end >= known["from"]
            and touches(e, known["titles"], labels)
        ):
            return e
    return None


def covered(known: Mapping[str, Any], days: Collection[date]) -> bool:
    """Whether the history holds a day within the bomb's dates, and one shortly before them
    to see it arrive."""
    start: date = known["from"]
    before = start - timedelta(days=MAX_GAP_DAYS)
    return any(start <= d <= known["to"] for d in days) and any(before <= d < start for d in days)


def score_turning_points(data_dir: Path) -> bool:
    labels = load_labels()
    passed = 0
    with duckdb.connect(str(data_dir / CURRENT_DB), read_only=True) as con:
        for entry in labels:
            episodes = episodes_of(con, entry["id"])
            if not episodes:
                print(f"FAIL  {entry['title']}: not in the current tables")
                continue
            verdict = judge(episodes)
            wrong = misses(entry, episodes, verdict)
            passed += not wrong
            summary = describe(verdict)
            if verdict.slumps:
                summary += "; slumps " + ", ".join(f"{s.start}–{s.end}" for s in verdict.slumps)
            print(f"{'pass' if not wrong else 'FAIL'}  {entry['title']}: {summary}")
            for miss in wrong:
                print(f"        {miss}")
    print(f"\n{passed}/{len(labels)} labelled shows pass (target {TARGET:.0%})")
    return passed >= TARGET * len(labels)


def score_bombs(data_dir: Path) -> bool:
    known = load_known_bombs()
    history = data_dir / "history"
    days = known_days(history)
    found = scored = 0
    with duckdb.connect(str(data_dir / CURRENT_DB), read_only=True) as con:
        for k in known:
            name = f"{k['title']}, {'/'.join(k['titles'])}, {k['from']} to {k['to']}"
            if not covered(k, days):
                print(f"skip  {name}: not covered by the history")
                continue
            scored += 1
            labels = labels_of(con, int(k["id"].removeprefix("tt")))
            shown = history_of(con, history, labels)
            hit = found_bomb(k, shown.events if shown else (), labels)
            found += hit is not None
            print(f"{'found' if hit else 'MISS '} {name}")
            if hit:
                print(f"        {when(hit)}, {what(hit, labels)}")
    skipped = len(known) - scored
    print(
        f"\n{found}/{scored} known bombs found (target {BOMB_TARGET:.0%})"
        + (f"; {skipped} not covered by the history" if skipped else "")
    )
    return found >= BOMB_TARGET * scored


def main(data_dir: Path = DATA_DIR) -> int:
    turning_points = score_turning_points(data_dir)
    print()
    bombs = score_bombs(data_dir)
    return 0 if turning_points and bombs else 1


if __name__ == "__main__":
    sys.exit(main())
