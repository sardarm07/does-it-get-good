"""A line per sync in data/runs.jsonl: when it ran, how long it took, and what it did."""

import json
from pathlib import Path
from typing import Any

RUNS = "runs.jsonl"


def log_run(data_dir: Path, run: dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / RUNS).open("a", encoding="utf-8") as f:
        f.write(json.dumps(run, ensure_ascii=False, default=str) + "\n")


def recent_runs(data_dir: Path, count: int = 10) -> list[dict[str, Any]]:
    """The last `count` syncs, oldest first; unreadable lines are skipped."""
    try:
        lines = (data_dir / RUNS).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    runs: list[dict[str, Any]] = []
    for line in lines[-count:]:
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return runs
