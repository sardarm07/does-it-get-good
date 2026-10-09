"""Score getgood against hand-labelled turning points and documented review bombs:
make validate."""

import argparse
import json
import random
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
from getgood.history import known_days, source
from getgood.report import EPISODES, history_of, label, labels_of, what, when
from getgood.sweep import sweep

LABELS = Path(__file__).resolve().parents[2] / "validation" / "turning_points.yaml"
KNOWN_BOMBS = LABELS.with_name("known_bombs.yaml")
REVIEWED = LABELS.with_name("reviewed_events.yaml")
FACTS = ("gets_good_at", "good_from_start", "slump_from", "low_point")
TOLERANCE = 3
"""How many episodes a turn or slump may be from its label and still count."""
LOW_POINT_TOLERANCE = 1
TARGET = 0.8
"""The share of labelled shows that must pass: M1's gate is 24 of 30."""
BOMB_TARGET = 0.8
"""The share of known bombs the history covers that must be found: M3's gate is 8 of 10."""
SEASON = re.compile(r"S\d+")
PRECISION_TARGET = 0.7
"""The share of reviewed review-bomb events, still found, that must be real: M3's gate."""
REVIEW_COUNT = 30
"""Events each `make review` adds to the list."""
REVIEW_HEADER = """\
# Review-bomb events getgood found, drawn at random from the whole history and marked by
# hand, to measure how many are real. `make validate` reports the share marked real among
# the events the detector still finds; `make review` draws more.
#
#   verdict  real: a burst of votes the show's ordinary viewing doesn't explain, such as a
#              campaign the press reported or a pile of 1s landing on an old title
#            misread: ordinary viewing taken for a bomb, such as an episode airing, a season
#              arriving on a new service, or a glitch in the data
#            unsure: can't tell either way; not scored
#            blank until reviewed
"""


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


def load_reviewed(path: Path = REVIEWED) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    entries: list[dict[str, Any]] | None = yaml.safe_load(path.read_text())
    return entries or []


def write_reviewed(entries: Sequence[Mapping[str, Any]], path: Path = REVIEWED) -> None:
    """Write the review list by hand, so it reads as written, header and all."""
    blocks = [REVIEW_HEADER]
    for e in entries:
        blocks.append(
            f"- id: {e['id']}\n"
            f"  title: {json.dumps(e['title'], ensure_ascii=False)}\n"
            f"  from: {e['from']}\n"
            f"  to: {e['to']}\n"
            f"  summary: {json.dumps(e['summary'], ensure_ascii=False)}\n"
            f"  verdict: {e.get('verdict') or ''}\n"
            f"  note: {json.dumps(e.get('note') or '', ensure_ascii=False)}\n"
        )
    path.write_text("\n".join(blocks))


def same_event(entry: Mapping[str, Any], event: Event) -> bool:
    """Whether a listed event and a found one are the same: one show, overlapping days."""
    return (
        entry["id"] == f"tt{event.show:07d}"
        and event.start <= entry["to"]
        and event.end >= entry["from"]
    )


def draw_for_review(
    data_dir: Path, count: int = REVIEW_COUNT, path: Path = REVIEWED, seed: int = 0
) -> int:
    """Add up to `count` review-bomb events, drawn at random from the whole history, to the
    review list. Returns how many were added."""
    history = data_dir / "history"
    relation, days = source(history), known_days(history)
    if relation is None or not days:
        print("No history yet: run getgood sync first.")
        return 0
    entries = load_reviewed(path)
    with duckdb.connect(str(data_dir / CURRENT_DB), read_only=True) as con:
        found = sweep(con, relation, days, since=min(days), until=max(days))
        fresh = [
            e
            for e in found
            if e.kind == "bomb" and not any(same_event(entry, e) for entry in entries)
        ]
        random.Random(seed + len(entries)).shuffle(fresh)
        chosen = fresh[:count]
        for e in chosen:
            title = con.execute("SELECT title FROM series WHERE tid = ?", [e.show]).fetchone()
            entries.append(
                {
                    "id": f"tt{e.show:07d}",
                    "title": title[0] if title else f"tt{e.show:07d}",
                    "from": e.start,
                    "to": e.end,
                    "summary": what(e, labels_of(con, e.show)),
                }
            )
    entries.sort(key=lambda entry: (entry["from"], entry["id"]))
    write_reviewed(entries, path)
    print(
        f"Added {len(chosen)} events to {path.name}; "
        f"{len(fresh) - len(chosen)} more review bombs are unlisted."
    )
    return len(chosen)


def score_review(data_dir: Path, path: Path = REVIEWED) -> bool:
    marked = [e for e in load_reviewed(path) if e.get("verdict") in ("real", "misread")]
    if not marked:
        print("No events reviewed yet: make review draws some to mark.")
        return True
    history = data_dir / "history"
    real = found = 0
    with duckdb.connect(str(data_dir / CURRENT_DB), read_only=True) as con:
        for entry in marked:
            name = f"{entry['title']}, {entry['from']} to {entry['to']}"
            shown = history_of(con, history, labels_of(con, int(entry["id"].removeprefix("tt"))))
            events = shown.events if shown else ()
            if not any(e.kind == "bomb" and same_event(entry, e) for e in events):
                print(f"gone    {name}: no longer found")
                continue
            found += 1
            real += entry["verdict"] == "real"
            print(f"{entry['verdict']:7} {name}")
    print(f"\n{real}/{found} reviewed review bombs are real (target {PRECISION_TARGET:.0%})")
    return found == 0 or real >= PRECISION_TARGET * found


def main(argv: Sequence[str] | None = None, data_dir: Path = DATA_DIR) -> int:
    parser = argparse.ArgumentParser(prog="python -m getgood.validation")
    commands = parser.add_subparsers(dest="command")
    review = commands.add_parser("review", help="draw review-bomb events to mark by hand")
    review.add_argument("--count", type=int, default=REVIEW_COUNT)
    args = parser.parse_args(argv)
    if args.command == "review":
        draw_for_review(data_dir, args.count)
        return 0
    turning_points = score_turning_points(data_dir)
    print()
    bombs = score_bombs(data_dir)
    print()
    precision = score_review(data_dir)
    return 0 if turning_points and bombs and precision else 1


if __name__ == "__main__":
    sys.exit(main())
