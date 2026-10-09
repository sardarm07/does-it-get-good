"""What getgood show says about one series, as data and as text."""

from dataclasses import dataclass
from typing import Any

import duckdb
import typer

from getgood.analysis.verdicts import Episode, Verdict, judge
from getgood.duck import scalar
from getgood.search import Match

CREDIT = "Information courtesy of IMDb (https://www.imdb.com). Used with permission."
EPISODE_COLUMNS = ("season", "episode", "rating_x10", "votes", "damped_x100")

EPISODES = """
    SELECT e.season, e.episode, r.rating_x10, r.votes
    FROM episodes e JOIN ratings r USING (tid)
    WHERE e.series = ?
    ORDER BY e.season, e.episode, e.tid
"""


@dataclass(frozen=True)
class Answer:
    as_of: str | None
    series: Match
    kind: str
    episodes: tuple[Episode, ...]
    verdict: Verdict

    @property
    def headline(self) -> str:
        v = self.verdict
        if v.kind == "gets_good":
            return f"Gets good at {v.at}"
        if v.kind == "good_from_start":
            return "Good from the start" + (f", even better from {v.at}" if v.at else "")
        if v.kind == "steady":
            return "Steady from start to finish"
        return "No clear turn"

    def to_json(self) -> dict[str, Any]:
        v = self.verdict
        label = [e.label for e in self.episodes]
        return {
            "as_of": self.as_of,
            "series": {
                "id": self.series.imdb_id,
                "title": self.series.title,
                "kind": self.kind,
                "years": self.series.years,
                "start_year": self.series.start_year,
                "end_year": self.series.end_year,
                "votes": self.series.votes,
            },
            "verdict": {
                "kind": v.kind,
                "at": v.at,
                "confidence": v.confidence,
                "reason": v.reason,
                "median": round(v.median, 2),
                "sigma": round(v.sigma, 2),
            },
            "slumps": [
                {"from": s.start, "to": s.end, "delta": round(s.delta, 2), "recovered": s.recovered}
                for s in v.slumps
            ],
            "low_points": list(v.low_points),
            "stretches": [
                {
                    "from": label[p.start],
                    "to": label[p.end - 1],
                    "episodes": p.end - p.start,
                    "level": round(p.level, 2),
                }
                for p in v.stretches
            ],
            "episode_columns": list(EPISODE_COLUMNS),
            "episodes": [
                [e.season, e.number, round(e.rating * 10), e.votes, round(x * 100)]
                for e, x in zip(self.episodes, v.damped, strict=True)
            ],
            "credit": CREDIT,
        }

    def to_text(self) -> str:
        v = self.verdict
        s = self.series
        files = f"IMDb's files of {self.as_of}" if self.as_of else "IMDb's files"
        slumps = [
            f"{x.start}–{x.end}, {-x.delta:.1f} below its usual level"
            + ("" if x.recovered else ", no recovery")
            for x in v.slumps
        ]
        lines = [
            f"{s.title} ({s.years}) · {s.imdb_id} · {len(self.episodes)} rated episodes · {files}",
            "",
            typer.style(self.headline, bold=True) + f" ({v.confidence} confidence)",
            v.reason,
            "",
            "Slumps:     " + ("\n            ".join(slumps) if slumps else "none"),
            "Low points: " + (", ".join(v.low_points) if v.low_points else "none"),
            "",
            CREDIT,
        ]
        return "\n".join(lines)


def answer(con: duckdb.DuckDBPyConnection, match: Match) -> Answer:
    """Judge one series from the current tables."""
    episodes = tuple(
        Episode(season, number, rating_x10 / 10, votes)
        for season, number, rating_x10, votes in con.execute(EPISODES, [match.tid]).fetchall()
    )
    return Answer(
        as_of=scalar(con, "SELECT value FROM meta WHERE key = 'as_of'") or None,
        series=match,
        kind=scalar(con, "SELECT kind FROM series WHERE tid = ?", [match.tid]),
        episodes=episodes,
        verdict=judge(episodes),
    )
