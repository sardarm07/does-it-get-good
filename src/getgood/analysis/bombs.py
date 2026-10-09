"""Review bombs: bursts of votes that move a rating, found in the history.

Two checks, both in SQL over the history, so one show and every show use the same code:

- Daily: a title with 500+ votes, at least 14 days into the history, is compared with its
  own pace over its last 28 history days (a robust z-score of new votes per day). A surge
  that drags the rating down is a bomb, one that lifts it is a boost, and one that leaves
  it where it was is suspicious.
- Launch: an episode in its first 14 days has no pace of its own yet, so it's compared with
  its season's other episodes at the same age. Far more votes and a far lower rating is a
  bomb.

Flags on one show within 2 days of each other form one event.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

import duckdb

from getgood.config import (
    BASELINE_DAYS,
    EVENT_DAYS,
    LAUNCH_DAYS,
    LAUNCH_DROP,
    LAUNCH_RATIO,
    MAX_GAP_DAYS,
    MIN_BASELINE_DAYS,
    MIN_BOMB_VOTES,
    NEW_VOTES_ERROR,
    SERIES_WIDE_EPISODES,
    SHOCK_DROP,
    SURGE_MIN_SHARE,
    SURGE_MIN_VOTES,
    SURGE_Z,
)

type Kind = Literal["bomb", "boost", "suspicious"]
KINDS: tuple[Kind, ...] = ("bomb", "boost", "suspicious")
SHOCK_X10 = round(SHOCK_DROP * 10)

# Ratings are compared in tenths, as integers, so 8.3 - 8.5 is exactly -0.2.
# {history}: (tid, date, rating_x10, votes); {episodes}: (tid, series, season);
# {titles}: a condition on tid.
DAILY = f"""
    WITH h AS (
        SELECT tid, date, CAST(rating_x10 AS INTEGER) AS rating_x10,
               CAST(votes AS BIGINT) AS votes
        FROM {{history}}
        WHERE {{titles}}
    ),
    steps AS (
        SELECT tid, date, rating_x10, votes,
               min(date) OVER (PARTITION BY tid) AS first_day,
               lag(date) OVER w AS prev_date,
               lag(rating_x10) OVER w AS prev_rating_x10,
               lag(votes) OVER w AS prev_votes
        FROM h
        WINDOW w AS (PARTITION BY tid ORDER BY date)
    ),
    changes AS (
        SELECT tid, date, rating_x10, votes, first_day,
               date - prev_date AS gap,
               (votes - prev_votes) / (date - prev_date) AS dv,
               rating_x10 - prev_rating_x10 AS dr_x10,
               CASE WHEN votes > prev_votes THEN
                   (rating_x10 * votes - prev_rating_x10 * prev_votes)
                   / (votes - prev_votes) / 10
               END AS new_votes_rating,
               CASE WHEN votes > prev_votes THEN
                   0.05 * (votes + prev_votes) / (votes - prev_votes)
               END AS new_votes_error
        FROM steps
        WHERE prev_date IS NOT NULL
    ),
    scored AS (
        SELECT *,
               median(dv) OVER b AS base,
               mad(dv) OVER b AS spread,
               count(*) OVER b AS base_days
        FROM changes
        WINDOW b AS (PARTITION BY tid ORDER BY date
                     ROWS BETWEEN {BASELINE_DAYS} PRECEDING AND 1 PRECEDING)
    )
    SELECT s.tid, coalesce(e.series, s.tid) AS show, s.date, s.votes, s.rating_x10, s.dr_x10,
           (s.dv - s.base) * s.gap AS extra,
           (s.dv - s.base) / (1.4826 * s.spread + 1) AS z,
           s.new_votes_rating, s.new_votes_error
    FROM scored s LEFT JOIN {{episodes}} e USING (tid)
    WHERE s.votes >= {MIN_BOMB_VOTES}
      AND s.base_days >= {MIN_BASELINE_DAYS}
      AND s.date - s.first_day >= {LAUNCH_DAYS}
      AND (s.dv - s.base) / (1.4826 * s.spread + 1) >= {SURGE_Z}
      AND s.dv >= greatest({SURGE_MIN_VOTES}, {SURGE_MIN_SHARE} * s.votes)
      AND ($since IS NULL OR s.date >= $since)
      AND ($until IS NULL OR s.date <= $until)
"""

# $days: every day the history holds.
LAUNCH = f"""
    WITH h AS (
        SELECT tid, date, CAST(rating_x10 AS INTEGER) AS rating_x10,
               CAST(votes AS BIGINT) AS votes
        FROM {{history}}
        WHERE {{titles}}
    ),
    first_seen AS (SELECT tid, min(date) AS first_day FROM h GROUP BY tid),
    observed AS (
        -- the history saw the episode arrive: it holds a day shortly before the first one
        SELECT f.tid, f.first_day
        FROM first_seen f
        WHERE EXISTS (
            SELECT 1 FROM (SELECT unnest(CAST($days AS DATE[])) AS date) d
            WHERE d.date < f.first_day AND d.date >= f.first_day - {MAX_GAP_DAYS}
        )
    ),
    aged AS (
        SELECT h.tid, e.series, e.season, h.date, h.rating_x10, h.votes,
               h.date - o.first_day AS age
        FROM h JOIN observed o USING (tid) JOIN {{episodes}} e USING (tid)
        WHERE h.date - o.first_day BETWEEN 1 AND {LAUNCH_DAYS - 1}
    ),
    compared AS (
        SELECT a.tid, a.series, a.date, a.votes, a.rating_x10,
               median(b.votes) AS siblings_votes,
               median(b.rating_x10) AS siblings_rating_x10
        FROM aged a
        JOIN aged b ON b.series = a.series AND b.season = a.season
                   AND b.tid <> a.tid AND b.age = a.age
        GROUP BY ALL
    )
    SELECT tid, series, date, votes, rating_x10, siblings_votes, siblings_rating_x10
    FROM compared
    WHERE votes >= {MIN_BOMB_VOTES}
      AND votes >= {LAUNCH_RATIO} * siblings_votes
      AND rating_x10 <= siblings_rating_x10 - {round(LAUNCH_DROP * 10)}
      AND ($since IS NULL OR date >= $since)
      AND ($until IS NULL OR date <= $until)
"""


@dataclass(frozen=True)
class Flag:
    """One title on one day that looks unusual."""

    tid: int
    show: int
    """The series the title belongs to: its own ID for the series page."""
    day: date
    kind: Kind
    launch: bool
    votes: int
    rating: float
    rating_change: float
    """Daily: since the previous history day. Launch: against its siblings' median."""
    extra_votes: float
    """Daily: votes above the title's usual pace. Launch: above its siblings' median."""
    z: float | None = None
    """Daily: how many robust standard deviations the day's pace is above the usual."""
    ratio: float | None = None
    """Launch: its votes over its siblings' median."""
    new_votes_rating: float | None = None
    """Daily: the new votes' average rating, when the rounding of IMDb's ratings leaves
    that estimate good to NEW_VOTES_ERROR points."""


@dataclass(frozen=True)
class Event:
    """Flags on one show close together in time."""

    show: int
    start: date
    end: date
    kind: Kind
    titles: tuple[int, ...]
    series_wide: bool
    extra_votes: float
    """Votes beyond the usual across the event's titles, for ranking."""
    flags: tuple[Flag, ...]


def find_flags(
    con: duckdb.DuckDBPyConnection,
    history: str,
    episodes: str,
    days: Collection[date],
    *,
    titles: str = "true",
    since: date | None = None,
    until: date | None = None,
) -> list[Flag]:
    """Every daily and launch flag between since and until, for the titles the filter keeps.

    The history and the episodes (tid, series, season) are SQL relations; days are every
    day the history holds. Each title's baseline and first day come from its whole history,
    not just the days asked about.
    """
    params: dict[str, object] = {"since": since, "until": until}
    found: list[Flag] = []
    daily = DAILY.format(history=history, episodes=episodes, titles=titles)
    for tid, show, day, votes, rating_x10, dr_x10, extra, z, new_rating, error in con.execute(
        daily, params
    ).fetchall():
        kind: Kind = (
            "bomb" if dr_x10 <= -SHOCK_X10 else "boost" if dr_x10 >= SHOCK_X10 else "suspicious"
        )
        found.append(
            Flag(
                tid=tid,
                show=show,
                day=day,
                kind=kind,
                launch=False,
                votes=votes,
                rating=rating_x10 / 10,
                rating_change=dr_x10 / 10,
                extra_votes=extra,
                z=z,
                new_votes_rating=new_rating if error <= NEW_VOTES_ERROR else None,
            )
        )
    launch = LAUNCH.format(history=history, episodes=episodes, titles=titles)
    for tid, show, day, votes, rating_x10, siblings_votes, siblings_x10 in con.execute(
        launch, params | {"days": sorted(days)}
    ).fetchall():
        found.append(
            Flag(
                tid=tid,
                show=show,
                day=day,
                kind="bomb",
                launch=True,
                votes=votes,
                rating=rating_x10 / 10,
                rating_change=(rating_x10 - siblings_x10) / 10,
                extra_votes=votes - siblings_votes,
                ratio=votes / siblings_votes,
            )
        )
    return sorted(found, key=lambda f: (f.day, f.show, f.tid))


def group(flags: Iterable[Flag]) -> list[Event]:
    """Flags on one show no more than EVENT_DAYS apart form one event, in date order."""
    by_show: dict[int, list[Flag]] = defaultdict(list)
    for f in flags:
        by_show[f.show].append(f)
    events: list[Event] = []
    for show, show_flags in by_show.items():
        run: list[Flag] = []
        for f in sorted(show_flags, key=lambda f: (f.day, f.tid)):
            if run and (f.day - run[-1].day).days > EVENT_DAYS:
                events.append(_event(show, run))
                run = []
            run.append(f)
        events.append(_event(show, run))
    return sorted(events, key=lambda e: (e.start, e.show))


def rank(events: Iterable[Event]) -> list[Event]:
    """Bombs first, then boosts, then the merely suspicious; the biggest first within each."""
    return sorted(events, key=lambda e: (KINDS.index(e.kind), -e.extra_votes, e.start))


def _event(show: int, flags: list[Flag]) -> Event:
    present: set[Kind] = {f.kind for f in flags}
    kind: Kind = next(k for k in KINDS if k in present)
    titles = tuple(dict.fromkeys(f.tid for f in flags))
    episodes = [t for t in titles if t != show]
    # A day's surge adds to the next day's; a launch flag repeats the same lead each day.
    daily = sum(f.extra_votes for f in flags if not f.launch)
    launch: dict[int, float] = defaultdict(float)
    for f in flags:
        if f.launch:
            launch[f.tid] = max(launch[f.tid], f.extra_votes)
    return Event(
        show=show,
        start=flags[0].day,
        end=flags[-1].day,
        kind=kind,
        titles=titles,
        series_wide=show in titles or len(episodes) >= SERIES_WIDE_EPISODES,
        extra_votes=daily + sum(launch.values()),
        flags=tuple(flags),
    )
