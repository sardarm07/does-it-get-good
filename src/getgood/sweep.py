"""Review bombs across every show, for getgood bombs."""

from collections.abc import Collection, Sequence
from datetime import date, timedelta

import duckdb

from getgood.analysis.bombs import Event, Flag, daily_flags, group, launch_flags, rank
from getgood.config import BASELINE_DAYS, LAUNCH_DAYS, MIN_BOMB_VOTES
from getgood.report import CREDIT, SERIES_PAGE, what, when
from getgood.search import Match

SWEEP_DAYS = 31
"""Days of daily flags found per query, so a long sweep never holds the whole history."""

VOTED = f"tid IN (SELECT tid FROM ratings WHERE votes >= {MIN_BOMB_VOTES})"
"""Titles with the votes to be judged. Votes only grow, so no other title ever had them."""
VOTED_SEASONS = (
    "tid IN (SELECT tid FROM episodes WHERE series IN ("
    f"SELECT series FROM episodes JOIN ratings USING (tid) WHERE votes >= {MIN_BOMB_VOTES}))"
)
"""Every episode of a series with an episode that can be judged: its siblings count too."""

KIND_NAMES = {"bomb": "Review bomb", "boost": "Boost", "suspicious": "Vote surge"}

SHOWS = "SELECT tid, title, start_year, end_year FROM series WHERE tid IN ({ids})"
EPISODE_LABELS = """
    SELECT tid, season, episode FROM episodes WHERE tid IN ({ids})
    ORDER BY series, season, episode
"""


def sweep(
    con: duckdb.DuckDBPyConnection,
    history: str,
    days: Collection[date],
    *,
    since: date,
    until: date,
) -> list[Event]:
    """Every event across all shows with a flag between since and until, in date order.

    Daily flags are found a month at a time, each month reading only its own days, the 28
    history days before them and the 14 days after, which tell an arrival from a surge;
    months the history doesn't reach are skipped.
    """
    ordered = sorted(days)
    flags: list[Flag] = []
    start = since
    while start <= until:
        end = min(until, start + timedelta(days=SWEEP_DAYS - 1))
        before = [d for d in ordered if d < start]
        if any(start <= d <= end for d in ordered):
            where = f"{VOTED} AND date <= DATE '{end + timedelta(days=LAUNCH_DAYS)}'"
            if len(before) > BASELINE_DAYS:
                where += f" AND date >= DATE '{before[-BASELINE_DAYS - 1].isoformat()}'"
            flags += daily_flags(con, history, "episodes", where=where, since=start, until=end)
        start = end + timedelta(days=1)
    flags += launch_flags(
        con, history, "episodes", days, where=VOTED_SEASONS, since=since, until=until
    )
    return group(flags)


def listing(
    con: duckdb.DuckDBPyConnection,
    events: Sequence[Event],
    *,
    since: date,
    until: date,
    every_kind: bool = False,
    limit: int = 20,
) -> str:
    """The biggest events as text, newest first: review bombs only, unless every_kind."""
    chosen = [e for e in rank(events) if every_kind or e.kind == "bomb"]
    shown = sorted(chosen[:limit], key=lambda e: (e.start, e.end, e.show), reverse=True)
    what_kind = "Review bombs, boosts and vote surges" if every_kind else "Review bombs"
    if not chosen:
        return f"{what_kind} from {since} to {until}: none\n\n{CREDIT}"
    # with every kind, bombs are chosen before boosts and boosts before surges, by size within
    size = "most serious" if every_kind else "biggest"
    which = f"the {limit} {size} of {len(chosen)}, " if len(chosen) > limit else ""
    lines = [f"{what_kind} from {since} to {until}: {which}newest first", ""]
    names = _names(con, [e.show for e in shown])
    labels = _labels(con, shown)
    for e in shown:
        kind = f"{KIND_NAMES[e.kind]}: " if every_kind else ""
        lines += [f"{when(e)}  {names[e.show]}", f"    {kind}{what(e, labels)}"]
    return "\n".join([*lines, "", CREDIT])


def _names(con: duckdb.DuckDBPyConnection, shows: Sequence[int]) -> dict[int, str]:
    found = {
        tid: Match(tid, title, start, end, 0, 0.0)
        for tid, title, start, end in con.execute(
            SHOWS.format(ids=", ".join(str(t) for t in set(shows)))
        ).fetchall()
    }
    return {
        t: f"{m.title} ({m.years}) · {m.imdb_id}" if (m := found.get(t)) else f"tt{t:07d}"
        for t in shows
    }


def _labels(con: duckdb.DuckDBPyConnection, events: Sequence[Event]) -> dict[int, str]:
    """Labels for the events' titles: series pages first, then episodes in order."""
    labels = {e.show: SERIES_PAGE for e in events}
    titles = {t for e in events for t in e.titles if t != e.show}
    if titles:
        for tid, season, number in con.execute(
            EPISODE_LABELS.format(ids=", ".join(str(t) for t in titles))
        ).fetchall():
            labels[tid] = f"S{season}E{number}"
    return labels
