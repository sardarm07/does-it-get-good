"""Review bombs: bursts of votes that move a rating, found in the history.

Three checks, all in SQL over the history, so one show and every show use the same code:

- Daily: a title with 500+ votes, at least 14 days into the history and not arriving (its
  votes don't grow fivefold within 14 days either side), is compared with its own pace over
  its last 28 history days (a robust z-score of new votes per day), on days the history
  reached within 3 days of the last. A surge that drags the rating down on votes far below
  it is a bomb, one that lifts it is a boost, and any other is suspicious.
- Launch: an episode in its first 14 days has no pace of its own yet, so it's compared with
  its season's other episodes at the same age, when they have an audience of their own (a
  median of 200 votes). Twice their votes (three times for a season finale) and a far lower
  rating is a bomb. Season premieres are left out on both sides:
  they always draw extra votes, and lower ratings, from people who don't go on.
- Page: a series page in its first 14 days is compared with its own episodes. Bombers rate
  the page without watching, so it falls below the episodes; it's a bomb when the gap is
  wide and takes a crowd of low votes to explain.

Flags on one show within 2 days of each other form one event.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

import duckdb

from getgood.config import (
    ARRIVAL_GROWTH,
    BASELINE_DAYS,
    BOMB_GAP,
    CONTESTED_NEIGHBOUR_VOTES,
    EVENT_DAYS,
    LAUNCH_DAYS,
    LAUNCH_DROP,
    LAUNCH_FINALE_RATIO,
    LAUNCH_RATIO,
    MAX_GAP_DAYS,
    MIN_BASELINE_DAYS,
    MIN_BOMB_VOTES,
    NEW_VOTES_ERROR,
    PAGE_DROP,
    PAGE_EXCESS,
    SERIES_WIDE_EPISODES,
    SHOCK_DROP,
    SURGE_MIN_SHARE,
    SURGE_MIN_VOTES,
    SURGE_Z,
)

type Kind = Literal["bomb", "boost", "suspicious"]
KINDS: tuple[Kind, ...] = ("bomb", "boost", "suspicious")
type Check = Literal["daily", "launch", "page"]
SHOCK_X10 = round(SHOCK_DROP * 10)
BOMB_GAP_X10 = round(BOMB_GAP * 10)

# Ratings are compared in tenths, as integers, so 8.3 - 8.5 is exactly -0.2.
# {history}: (tid, date, rating_x10, votes); {episodes}: (tid, series, season, episode);
# {where}: a condition on the history's rows.
DAILY = f"""
    WITH h AS (
        SELECT tid, date, CAST(rating_x10 AS INTEGER) AS rating_x10,
               CAST(votes AS BIGINT) AS votes
        FROM {{history}}
        WHERE {{where}}
    ),
    steps AS (
        SELECT tid, date, rating_x10, votes,
               min(date) OVER (PARTITION BY tid) AS first_day,
               min(votes) OVER around AS around_low,
               max(votes) OVER around AS around_high,
               lag(date) OVER w AS prev_date,
               lag(rating_x10) OVER w AS prev_rating_x10,
               lag(votes) OVER w AS prev_votes
        FROM h
        WINDOW w AS (PARTITION BY tid ORDER BY date),
               around AS (PARTITION BY tid ORDER BY date
                          RANGE BETWEEN INTERVAL {LAUNCH_DAYS} DAYS PRECEDING
                          AND INTERVAL {LAUNCH_DAYS} DAYS FOLLOWING)
    ),
    changes AS (
        SELECT tid, date, rating_x10, votes, first_day,
               -- the day before the window counts too, when the history skipped days
               around_high >= {ARRIVAL_GROWTH} * least(around_low, prev_votes) AS arriving,
               date - prev_date AS gap,
               (votes - prev_votes) / (date - prev_date) AS dv,
               rating_x10 - prev_rating_x10 AS dr_x10,
               CASE WHEN votes > prev_votes THEN
                   (rating_x10 * votes - prev_rating_x10 * prev_votes)
                   / (votes - prev_votes) / 10
               END AS new_votes_rating,
               CASE WHEN votes > prev_votes THEN
                   0.05 * (votes + prev_votes) / (votes - prev_votes)
               END AS new_votes_error,
               -- how far below the rating before them the new votes average, in tenths
               CASE WHEN votes > prev_votes THEN
                   (prev_rating_x10 - rating_x10) * votes / (votes - prev_votes)
               END AS new_votes_below_x10
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
           s.new_votes_rating, s.new_votes_error, s.new_votes_below_x10
    FROM scored s LEFT JOIN {{episodes}} e USING (tid)
    WHERE s.votes >= {MIN_BOMB_VOTES}
      AND s.base_days >= {MIN_BASELINE_DAYS}
      AND s.date - s.first_day >= {LAUNCH_DAYS}
      AND s.gap <= {MAX_GAP_DAYS}
      AND NOT s.arriving
      AND (s.dv - s.base) / (1.4826 * s.spread + 1) >= {SURGE_Z}
      AND s.dv >= greatest({SURGE_MIN_VOTES}, {SURGE_MIN_SHARE} * s.votes)
      AND ($since IS NULL OR s.date >= $since)
      AND ($until IS NULL OR s.date <= $until)
"""

# The history is read twice rather than through one shared CTE, which DuckDB would hold in
# memory whole when sweeping every show. $days: every day the history holds.
LAUNCH = f"""
    WITH first_seen AS (
        SELECT tid, min(date) AS first_day FROM {{history}} WHERE {{where}} GROUP BY tid
    ),
    observed AS (
        -- the history saw the episode arrive: it holds a day shortly before the first one
        SELECT f.tid, f.first_day
        FROM first_seen f
        WHERE EXISTS (
            SELECT 1 FROM (SELECT unnest(CAST($days AS DATE[])) AS date) d
            WHERE d.date < f.first_day AND d.date >= f.first_day - {MAX_GAP_DAYS}
        )
    ),
    finales AS (
        -- the season's last episode listed, so a season still airing has its finale ahead
        SELECT series, season, max(episode) AS episode FROM {{episodes}} GROUP BY ALL
    ),
    aged AS (
        SELECT h.tid, e.series, e.season, h.date,
               CAST(h.rating_x10 AS INTEGER) AS rating_x10, CAST(h.votes AS BIGINT) AS votes,
               h.date - o.first_day AS age, e.episode = f.episode AS finale
        FROM {{history}} h JOIN observed o USING (tid) JOIN {{episodes}} e USING (tid)
        JOIN finales f ON f.series = e.series AND f.season = e.season
        WHERE h.date - o.first_day BETWEEN 1 AND {LAUNCH_DAYS - 1} AND e.episode > 1
    ),
    compared AS (
        SELECT a.tid, a.series, a.date, a.votes, a.rating_x10, a.finale,
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
      AND siblings_votes >= {CONTESTED_NEIGHBOUR_VOTES}
      AND votes >= CASE WHEN finale THEN {LAUNCH_FINALE_RATIO} ELSE {LAUNCH_RATIO} END
                   * siblings_votes
      AND rating_x10 <= siblings_rating_x10 - {round(LAUNCH_DROP * 10)}
      AND ($since IS NULL OR date >= $since)
      AND ($until IS NULL OR date <= $until)
"""

# Series pages the history saw arrive, against their episodes' vote-weighted rating on the
# same day. The excess is the 1s it would take to drag the page from the episodes' rating
# to its own: votes x (episodes - page) / (episodes - 1), the ratings in tenths.
PAGE = f"""
    WITH pages AS (
        SELECT tid, min(date) AS first_day
        FROM {{history}}
        WHERE {{where}} AND tid IN (SELECT series FROM {{episodes}})
        GROUP BY tid
    ),
    observed AS (
        SELECT p.tid, p.first_day
        FROM pages p
        WHERE EXISTS (
            SELECT 1 FROM (SELECT unnest(CAST($days AS DATE[])) AS date) d
            WHERE d.date < p.first_day AND d.date >= p.first_day - {MAX_GAP_DAYS}
        )
    ),
    page_days AS (
        SELECT h.tid, h.date, CAST(h.rating_x10 AS INTEGER) AS rating_x10,
               CAST(h.votes AS BIGINT) AS votes
        FROM {{history}} h JOIN observed o USING (tid)
        WHERE h.date - o.first_day BETWEEN 1 AND {LAUNCH_DAYS - 1}
    ),
    episode_days AS (
        SELECT e.series AS tid, h.date,
               sum(CAST(h.rating_x10 AS BIGINT) * h.votes) / sum(h.votes) AS rating_x10,
               sum(h.votes) AS votes
        FROM {{history}} h
        JOIN {{episodes}} e ON e.tid = h.tid
        JOIN observed o ON o.tid = e.series
        WHERE h.date - o.first_day BETWEEN 1 AND {LAUNCH_DAYS - 1}
        GROUP BY ALL
    )
    SELECT p.tid, p.date, p.votes, p.rating_x10, e.rating_x10 AS episodes_x10,
           p.votes * (e.rating_x10 - p.rating_x10) / (e.rating_x10 - 10) AS excess
    FROM page_days p JOIN episode_days e USING (tid, date)
    WHERE p.votes >= {MIN_BOMB_VOTES}
      AND e.votes >= {CONTESTED_NEIGHBOUR_VOTES}
      AND p.rating_x10 <= e.rating_x10 - {round(PAGE_DROP * 10)}
      AND p.votes * (e.rating_x10 - p.rating_x10) / (e.rating_x10 - 10) >= {PAGE_EXCESS}
      AND ($since IS NULL OR p.date >= $since)
      AND ($until IS NULL OR p.date <= $until)
"""


@dataclass(frozen=True)
class Flag:
    """One title on one day that looks unusual."""

    tid: int
    show: int
    """The series the title belongs to: its own ID for the series page."""
    day: date
    kind: Kind
    check: Check
    votes: int
    rating: float
    rating_change: float
    """Daily: since the previous history day. Launch: against its siblings' median. Page:
    against its own episodes' rating."""
    extra_votes: float
    """Daily: votes above the title's usual pace. Launch: above its siblings' median. Page:
    the low votes it would take to open its gap below its episodes."""
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
    where: str = "true",
    since: date | None = None,
    until: date | None = None,
) -> list[Flag]:
    """Every daily, launch and page flag between since and until, in date order.

    The history and the episodes (tid, series, season, episode) are SQL relations; days are
    every day the history holds. `where` must keep whole titles' histories: each title's
    baseline and first day come from all of it, not just the days asked about.
    """
    found = daily_flags(con, history, episodes, where=where, since=since, until=until)
    found += launch_flags(con, history, episodes, days, where=where, since=since, until=until)
    found += page_flags(con, history, episodes, days, where=where, since=since, until=until)
    return sorted(found, key=lambda f: (f.day, f.show, f.tid))


def daily_flags(
    con: duckdb.DuckDBPyConnection,
    history: str,
    episodes: str,
    *,
    where: str = "true",
    since: date | None = None,
    until: date | None = None,
) -> list[Flag]:
    """Each day a title's new votes surged against its own pace, between since and until.

    A day is judged against the title's 28 history days before it, so a `where` that limits
    dates must keep those.
    """
    found: list[Flag] = []
    sql = DAILY.format(history=history, episodes=episodes, where=where)
    for (
        tid,
        show,
        day,
        votes,
        rating_x10,
        dr_x10,
        extra,
        z,
        new_rating,
        error,
        below,
    ) in con.execute(sql, {"since": since, "until": until}).fetchall():
        # when the new votes are a small share, the drop alone puts them far below; when
        # they're a large share, their own average is known well enough to check
        kind: Kind = (
            "bomb"
            if dr_x10 <= -SHOCK_X10 and below >= BOMB_GAP_X10
            else "boost"
            if dr_x10 >= SHOCK_X10
            else "suspicious"
        )
        found.append(
            Flag(
                tid=tid,
                show=show,
                day=day,
                kind=kind,
                check="daily",
                votes=votes,
                rating=rating_x10 / 10,
                rating_change=dr_x10 / 10,
                extra_votes=extra,
                z=z,
                new_votes_rating=new_rating if error <= NEW_VOTES_ERROR else None,
            )
        )
    return found


def launch_flags(
    con: duckdb.DuckDBPyConnection,
    history: str,
    episodes: str,
    days: Collection[date],
    *,
    where: str = "true",
    since: date | None = None,
    until: date | None = None,
) -> list[Flag]:
    """Each day of an episode's first two weeks that it drew far more votes than its season's
    other episodes at the same age, and a far lower rating.

    `where` must keep whole titles' histories, and every episode of a season it keeps: an
    episode cut short looks newer than it is, and a missing one changes its siblings' median.
    """
    found: list[Flag] = []
    sql = LAUNCH.format(history=history, episodes=episodes, where=where)
    for tid, show, day, votes, rating_x10, siblings_votes, siblings_x10 in con.execute(
        sql, {"since": since, "until": until, "days": sorted(days)}
    ).fetchall():
        found.append(
            Flag(
                tid=tid,
                show=show,
                day=day,
                kind="bomb",
                check="launch",
                votes=votes,
                rating=rating_x10 / 10,
                rating_change=(rating_x10 - siblings_x10) / 10,
                extra_votes=votes - siblings_votes,
                ratio=votes / siblings_votes,
            )
        )
    return found


def page_flags(
    con: duckdb.DuckDBPyConnection,
    history: str,
    episodes: str,
    days: Collection[date],
    *,
    where: str = "true",
    since: date | None = None,
    until: date | None = None,
) -> list[Flag]:
    """Each day of a series page's first two weeks that it rated far below its own episodes,
    by a gap only a crowd of low votes explains.

    `where` must keep the series pages' whole histories; their episodes are read whole.
    """
    found: list[Flag] = []
    sql = PAGE.format(history=history, episodes=episodes, where=where)
    for tid, day, votes, rating_x10, episodes_x10, excess in con.execute(
        sql, {"since": since, "until": until, "days": sorted(days)}
    ).fetchall():
        found.append(
            Flag(
                tid=tid,
                show=tid,
                day=day,
                kind="bomb",
                check="page",
                votes=votes,
                rating=rating_x10 / 10,
                rating_change=(rating_x10 - episodes_x10) / 10,
                extra_votes=excess,
            )
        )
    return found


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
    # A day's surge adds to the next day's; launch and page flags repeat one lead each day.
    daily = sum(f.extra_votes for f in flags if f.check == "daily")
    lead: dict[int, float] = defaultdict(float)
    for f in flags:
        if f.check != "daily":
            lead[f.tid] = max(lead[f.tid], f.extra_votes)
    return Event(
        show=show,
        start=flags[0].day,
        end=flags[-1].day,
        kind=kind,
        titles=titles,
        series_wide=show in titles or len(episodes) >= SERIES_WIDE_EPISODES,
        extra_votes=daily + sum(lead.values()),
        flags=tuple(flags),
    )
