"""Score getgood's verdicts against hand-labelled turning points: make validate."""

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import duckdb
import yaml

from getgood.analysis.verdicts import Episode, Verdict, judge
from getgood.config import CURRENT_DB, DATA_DIR
from getgood.report import EPISODES

LABELS = Path(__file__).resolve().parents[2] / "validation" / "turning_points.yaml"
FACTS = ("gets_good_at", "good_from_start", "slump_from", "low_point")
TOLERANCE = 3
"""How many episodes a turn or slump may be from its label and still count."""
LOW_POINT_TOLERANCE = 1
TARGET = 0.8
"""The share of labelled shows that must pass: M1's gate is 24 of 30."""


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


def main(data_dir: Path = DATA_DIR) -> int:
    labels = load_labels()
    passed = 0
    with duckdb.connect(str(data_dir / CURRENT_DB), read_only=True) as con:
        for label in labels:
            episodes = episodes_of(con, label["id"])
            if not episodes:
                print(f"FAIL  {label['title']}: not in the current tables")
                continue
            verdict = judge(episodes)
            wrong = misses(label, episodes, verdict)
            passed += not wrong
            summary = describe(verdict)
            if verdict.slumps:
                summary += "; slumps " + ", ".join(f"{s.start}–{s.end}" for s in verdict.slumps)
            print(f"{'pass' if not wrong else 'FAIL'}  {label['title']}: {summary}")
            for miss in wrong:
                print(f"        {miss}")
    print(f"\n{passed}/{len(labels)} labelled shows pass (target {TARGET:.0%})")
    return 0 if passed >= TARGET * len(labels) else 1


if __name__ == "__main__":
    sys.exit(main())
