"""What getgood show says about one series, as data and as text."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import typer

from getgood.analysis.bombs import Event, Flag, find_flags, group
from getgood.analysis.contested import Contested, contested
from getgood.analysis.verdicts import Episode, Verdict, judge
from getgood.duck import scalar
from getgood.history import known_days, source
from getgood.search import Match

CREDIT = "Information courtesy of IMDb (https://www.imdb.com). Used with permission."
EPISODE_COLUMNS = ("season", "episode", "rating_x10", "votes", "damped_x100")
SERIES_PAGE = "series"
"""The label of the series' own page, beside episode labels like S2E1."""
FIELD = 14
"""Width of the field names in the text answer."""
MAX_NAMED = 4
"""An event touching more titles than this counts its episodes instead of naming them."""

EPISODES = """
    SELECT e.season, e.episode, r.rating_x10, r.votes
    FROM episodes e JOIN ratings r USING (tid)
    WHERE e.series = ?
    ORDER BY e.season, e.episode, e.tid
"""
TITLES = "SELECT tid, season, episode FROM episodes WHERE series = ? ORDER BY season, episode"
PAGE_DAYS = """
    SELECT date, rating_x10, votes FROM {history} WHERE series = $series AND tid = $series
    ORDER BY date
"""
PAGE_COLUMNS = ("date", "rating_x10", "votes")


@dataclass(frozen=True)
class History:
    """The days the history holds, and what they show for one series."""

    days: int
    first: date
    last: date
    events: tuple[Event, ...]
    page: tuple[tuple[date, int, int], ...] = ()
    """The series page's date, rating x 10 and votes, for each day the history holds it."""


@dataclass(frozen=True)
class Answer:
    as_of: str | None
    series: Match
    kind: str
    episodes: tuple[Episode, ...]
    verdict: Verdict
    contested: tuple[Contested, ...]
    labels: Mapping[int, str]
    """Each title ID's label: SERIES_PAGE, or an episode's like S2E1."""
    history: History | None
    """None until the history holds a day."""

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

    def label(self, tid: int) -> str:
        return label(self.labels, tid)

    def to_json(self) -> dict[str, Any]:
        v = self.verdict
        label = [e.label for e in self.episodes]
        h = self.history
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
                "headline": self.headline,
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
            "contested": [
                {
                    "episode": c.episode,
                    "votes": c.votes,
                    "rating": c.rating,
                    "neighbour_votes": c.neighbour_votes,
                    "neighbour_rating": c.neighbour_rating,
                }
                for c in self.contested
            ],
            "history": None
            if h is None
            else {
                "days": h.days,
                "first": h.first.isoformat(),
                "last": h.last.isoformat(),
                "events": [self._event_json(e) for e in h.events],
                "page_columns": list(PAGE_COLUMNS),
                "page": [[d.isoformat(), r, v] for d, r, v in h.page],
            },
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

    def _event_json(self, e: Event) -> dict[str, Any]:
        return {
            "kind": e.kind,
            "from": e.start.isoformat(),
            "to": e.end.isoformat(),
            "titles": [self.label(t) for t in in_order(e.titles, self.labels)],
            "summary": what(e, self.labels),
            "series_wide": e.series_wide,
            "extra_votes": round(e.extra_votes),
            "flags": [self._flag_json(f) for f in e.flags],
        }

    def _flag_json(self, f: Flag) -> dict[str, Any]:
        return {
            "title": self.label(f.tid),
            "day": f.day.isoformat(),
            "check": f.check,
            "votes": f.votes,
            "rating": f.rating,
            "rating_change": f.rating_change,
            "extra_votes": round(f.extra_votes),
            "z": None if f.z is None else round(f.z, 1),
            "ratio": None if f.ratio is None else round(f.ratio, 2),
            "new_votes_rating": None
            if f.new_votes_rating is None
            else round(f.new_votes_rating, 1),
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
        contested_episodes = [
            f"{c.episode}, {c.vote_ratio:.1f}× its neighbours' votes, "
            f"rated {-c.rating_gap:.1f} below them"
            for c in self.contested
        ]
        lines = [
            f"{s.title} ({s.years}) · {s.imdb_id} · {len(self.episodes)} rated episodes · {files}",
            "",
            typer.style(self.headline, bold=True) + f" ({v.confidence} confidence)",
            v.reason,
            "",
            *_field("Slumps", slumps),
            *_field("Low points", list(v.low_points)),
            *_field("Contested", contested_episodes),
            *self._history_text(),
            "",
            CREDIT,
        ]
        return "\n".join(lines)

    def _history_text(self) -> list[str]:
        h = self.history
        if h is None:
            return _field("Review bombs", ["unknown: the history is empty until getgood sync"])
        by_kind: dict[str, list[str]] = defaultdict(list)
        for e in h.events:
            by_kind[e.kind].append(f"{when(e)}, {what(e, self.labels)}")
        lines = _field("Review bombs", by_kind["bomb"])
        if by_kind["boost"]:
            lines += _field("Boosts", by_kind["boost"])
        if by_kind["suspicious"]:
            lines += _field("Vote surges", by_kind["suspicious"])
        return [*lines, *_field("History", [f"{h.days:,} days from {h.first} to {h.last}"])]


def label(labels: Mapping[int, str], tid: int) -> str:
    """A title's label: SERIES_PAGE, an episode's like S2E1, or its IMDb ID if unknown."""
    return labels.get(tid, f"tt{tid:07d}")


def in_order(titles: Iterable[int], labels: Mapping[int, str]) -> list[int]:
    """Titles in the order the labels list them: series pages, then by season and episode."""
    place = {tid: i for i, tid in enumerate(labels)}
    return sorted(titles, key=lambda t: place.get(t, len(place)))


def when(e: Event) -> str:
    """An event's day, or its first and last."""
    return str(e.start) if e.start == e.end else f"{e.start} to {e.end}"


def what(e: Event, labels: Mapping[int, str]) -> str:
    """The titles an event touched and what happened to them, in one line."""
    effects: list[str] = []
    page = [f for f in e.flags if f.check == "page"]
    if page:
        gap = min(f.rating_change for f in page)
        excess = max(f.extra_votes for f in page)
        effects.append(
            f"at launch, rated up to {-gap:.1f} below its own episodes, "
            f"as if {excess:,.0f} low votes had been added"
        )
    launch = [f for f in e.flags if f.check == "launch"]
    if launch:
        ratio = max(f.ratio or 0.0 for f in launch)
        gap = min(f.rating_change for f in launch)
        effects.append(
            f"at launch, up to {ratio:.1f}× the votes of its season's other episodes "
            f"and {-gap:.1f} below their rating"
        )
    daily = [f for f in e.flags if f.check == "daily"]
    if daily:
        change: dict[int, float] = defaultdict(float)
        for f in daily:
            change[f.tid] += f.rating_change
        # what the event is named for: a bomb's biggest drop, a boost's biggest rise
        if e.kind == "bomb":
            biggest = min(change.values())
        elif e.kind == "boost":
            biggest = max(change.values())
        else:
            biggest = max(change.values(), key=abs)
        moved = f", rating {biggest:+.1f}" if abs(biggest) >= 0.05 else ", rating unmoved"
        extra = sum(f.extra_votes for f in daily)
        effects.append(f"{extra:,.0f} more votes than usual{moved}")
    return f"{_titles(e, labels)}: " + "; ".join(effects)


def _titles(e: Event, labels: Mapping[int, str]) -> str:
    names = [
        "series page" if label(labels, t) == SERIES_PAGE else label(labels, t)
        for t in in_order(e.titles, labels)
    ]
    if len(names) <= MAX_NAMED:
        return ", ".join(names)
    counted = f"{len([t for t in e.titles if t != e.show])} episodes"
    return f"series page and {counted}" if e.show in e.titles else counted


def _field(name: str, items: list[str]) -> list[str]:
    """A named field of the text answer, one item per line."""
    head = f"{name}:".ljust(FIELD)
    if not items:
        return [head + "none"]
    return [head + items[0], *(" " * FIELD + item for item in items[1:])]


def answer(con: duckdb.DuckDBPyConnection, match: Match, history: Path | None = None) -> Answer:
    """Judge one series from the current tables and, when there is one, the history."""
    episodes = tuple(
        Episode(season, number, rating_x10 / 10, votes)
        for season, number, rating_x10, votes in con.execute(EPISODES, [match.tid]).fetchall()
    )
    labels = labels_of(con, match.tid)
    return Answer(
        as_of=scalar(con, "SELECT value FROM meta WHERE key = 'as_of'") or None,
        series=match,
        kind=scalar(con, "SELECT kind FROM series WHERE tid = ?", [match.tid]),
        episodes=episodes,
        verdict=judge(episodes),
        contested=contested(episodes),
        labels=labels,
        history=None if history is None else history_of(con, history, match.tid),
    )


def labels_of(con: duckdb.DuckDBPyConnection, series: int) -> dict[int, str]:
    """Labels for a series' titles, in its order: the series page, then its episodes."""
    return {series: SERIES_PAGE} | {
        tid: f"S{season}E{number}"
        for tid, season, number in con.execute(TITLES, [series]).fetchall()
    }


def history_of(con: duckdb.DuckDBPyConnection, history: Path, series: int) -> History | None:
    """The events the history shows for a series, or None while it's empty."""
    relation = source(history)
    days = known_days(history)
    if relation is None or not days:
        return None
    # The checks need only the show's own rows, which sit together in each month's file.
    own = f"(SELECT tid, date, rating_x10, votes FROM {relation} WHERE series = {series})"
    flags = find_flags(con, own, "episodes", days)
    page = con.execute(PAGE_DAYS.format(history=relation), {"series": series}).fetchall()
    return History(len(days), min(days), max(days), tuple(group(flags)), tuple(page))
