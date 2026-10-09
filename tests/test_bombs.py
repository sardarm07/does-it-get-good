from collections.abc import Iterable, Iterator
from datetime import date

import duckdb
import numpy as np
import pytest

from getgood.analysis.bombs import Flag, Kind, find_flags, group, rank
from tests.helpers import Row, burst, day, season, steady

SHOW = 1


def five_episodes(
    bombed: int, *, rating: float = 7.0
) -> tuple[list[Row], list[tuple[int, int, int]]]:
    """A series page and five weekly episodes from day 10; episode `bombed` draws a crowd."""
    tids = [101, 102, 103, 104, 105]
    rows = season(SHOW, tids, bombed=100 + bombed, rating=rating)
    return rows, [(t, SHOW, 1) for t in tids]


@pytest.fixture
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    with duckdb.connect() as c:
        yield c


def flags(
    con: duckdb.DuckDBPyConnection,
    rows: list[Row],
    episodes: Iterable[tuple[int, int, int]] = (),
    *,
    since: date | None = None,
    until: date | None = None,
) -> list[Flag]:
    """Load a history and its episodes (tid, series, season), then look for flags."""
    con.execute("CREATE OR REPLACE TABLE hist (tid INT, date DATE, rating_x10 UTINYINT, votes INT)")
    con.execute(
        "INSERT INTO hist SELECT unnest($tid), unnest($date), unnest($rating), unnest($votes)",
        {
            "tid": [r[0] for r in rows],
            "date": [r[1] for r in rows],
            "rating": [round(r[2] * 10) for r in rows],
            "votes": [r[3] for r in rows],
        },
    )
    con.execute("CREATE OR REPLACE TABLE eps (tid INT, series INT, season INT)")
    for episode in episodes:
        con.execute("INSERT INTO eps VALUES (?, ?, ?)", episode)
    days = {r[1] for r in rows}
    return find_flags(con, "hist", "eps", days, since=since, until=until)


def flag(
    tid: int,
    n: int,
    kind: Kind = "bomb",
    *,
    show: int = SHOW,
    launch: bool = False,
    extra: float = 100,
) -> Flag:
    return Flag(
        tid=tid,
        show=show,
        day=day(n),
        kind=kind,
        launch=launch,
        votes=1_000,
        rating=7.0,
        rating_change=-0.5,
        extra_votes=extra,
    )


def test_a_burst_of_low_votes_is_a_bomb(con: duckdb.DuckDBPyConnection) -> None:
    rows = steady(101, range(61), votes=1_000, pace=10, rating=8.5)

    [found] = flags(con, burst(rows, at=40, extra=600, rating=8.0))

    assert (found.tid, found.show, found.day, found.kind) == (101, 101, day(40), "bomb")
    assert not found.launch
    assert found.rating_change == -0.5
    assert found.extra_votes == 600  # 610 that day against its usual 10
    assert found.z == 600
    # 2,000 votes at 8.0 after 1,390 at 8.5: the 610 new ones average about 6.9
    assert found.new_votes_rating == pytest.approx(6.86, abs=0.01)


@pytest.mark.parametrize(
    ("before", "after", "kind"),
    [(8.5, 8.3, "bomb"), (7.0, 7.5, "boost"), (7.0, 7.2, "boost"), (8.5, 8.4, "suspicious")],
)
def test_the_rating_change_on_the_day_decides_the_kind(
    con: duckdb.DuckDBPyConnection, before: float, after: float, kind: Kind
) -> None:
    rows = steady(101, range(61), votes=1_000, pace=10, rating=before)

    [found] = flags(con, burst(rows, at=40, extra=600, rating=after))

    assert found.kind == kind
    assert found.rating_change == round(after - before, 1)


def test_ordinary_ups_and_downs_raise_no_flags(con: duckdb.DuckDBPyConnection) -> None:
    rng = np.random.default_rng(7)
    votes = 2_000 + np.cumsum(rng.poisson(30, 365))
    ratings = 8.0 + rng.choice([-0.1, 0.0, 0.1], 365)
    rows = [
        (101, day(n), float(r), int(v)) for n, (r, v) in enumerate(zip(ratings, votes, strict=True))
    ]

    assert flags(con, rows) == []


def test_the_first_two_weeks_are_left_to_the_launch_check(con: duckdb.DuckDBPyConnection) -> None:
    rows = steady(101, range(61), votes=1_000, pace=10, rating=8.5)

    assert flags(con, burst(rows, at=10, extra=600, rating=8.0)) == []
    assert len(flags(con, burst(rows, at=20, extra=600, rating=8.0))) == 1


@pytest.mark.parametrize(("votes", "flagged"), [(200, False), (400, True)])
def test_titles_under_500_votes_are_too_thin_to_judge(
    con: duckdb.DuckDBPyConnection, votes: int, flagged: bool
) -> None:
    rows = steady(101, range(61), votes=votes, pace=2, rating=8.5)

    found = flags(con, burst(rows, at=40, extra=150, rating=8.0))

    assert bool(found) is flagged


@pytest.mark.parametrize(("extra", "flagged"), [(1_000, False), (3_000, True)])
def test_a_surge_must_be_a_real_share_of_the_votes(
    con: duckdb.DuckDBPyConnection, extra: int, flagged: bool
) -> None:
    rows = steady(101, range(61), votes=100_000, pace=20, rating=8.5)

    # 1,000 is 50 times the usual pace, but only 1% of the title's votes
    found = flags(con, burst(rows, at=40, extra=extra, rating=8.3))

    assert bool(found) is flagged


def test_new_votes_are_spread_over_missing_days(con: duckdb.DuckDBPyConnection) -> None:
    rows = [
        r
        for r in steady(101, range(61), votes=1_000, pace=10, rating=8.5)
        if r[1] not in (day(38), day(39))
    ]

    assert flags(con, rows) == []
    [found] = flags(con, burst(rows, at=40, extra=600, rating=8.0))
    assert found.extra_votes == 600


def test_since_and_until_choose_the_days_but_not_the_baseline(
    con: duckdb.DuckDBPyConnection,
) -> None:
    rows = steady(101, range(121), votes=1_000, pace=10, rating=8.5)
    rows = burst(burst(rows, at=40, extra=600, rating=8.0), at=80, extra=600, rating=7.6)

    assert [f.day for f in flags(con, rows)] == [day(40), day(80)]
    assert [f.day for f in flags(con, rows, since=day(60))] == [day(80)]
    assert [f.day for f in flags(con, rows, until=day(60))] == [day(40)]
    # judged against the days before, and 40 days after the title's first day
    assert [f.day for f in flags(con, rows, since=day(40), until=day(40))] == [day(40)]


def test_an_episode_far_ahead_of_its_season_at_launch_is_a_bomb(
    con: duckdb.DuckDBPyConnection,
) -> None:
    rows, episodes = five_episodes(bombed=3)

    found = flags(con, rows, episodes)

    # episode 3 arrives on day 24 and is compared at ages 1 to 13
    assert [f.day for f in found] == [day(n) for n in range(25, 38)]
    assert {(f.tid, f.show, f.kind, f.launch) for f in found} == {(103, SHOW, "bomb", True)}
    first = found[0]
    assert first.votes == 5_000
    assert first.ratio == pytest.approx(5_000 / 1_500)
    assert first.extra_votes == 3_500
    assert first.rating_change == pytest.approx(7.0 - 8.9)


def test_a_crowd_for_a_better_rated_episode_is_no_bomb(con: duckdb.DuckDBPyConnection) -> None:
    rows, episodes = five_episodes(bombed=3, rating=9.5)

    assert flags(con, rows, episodes) == []


def test_an_episode_that_arrived_unseen_is_not_compared(con: duckdb.DuckDBPyConnection) -> None:
    rows, episodes = five_episodes(bombed=3)
    # the history misses days 20 to 23, so episode 3 might have arrived any time after day 19
    rows = [r for r in rows if not day(20) <= r[1] <= day(23)]

    assert flags(con, rows, episodes) == []


def test_flags_close_together_on_one_show_are_one_event() -> None:
    events = group([flag(101, 10), flag(102, 12), flag(101, 15), flag(201, 11, show=2)])

    assert [(e.show, e.start, e.end, e.titles) for e in events] == [
        (SHOW, day(10), day(12), (101, 102)),
        (2, day(11), day(11), (201,)),
        (SHOW, day(15), day(15), (101,)),
    ]


@pytest.mark.parametrize(
    ("tids", "series_wide"), [((101, 102), False), ((101, 102, 103), True), ((SHOW,), True)]
)
def test_three_episodes_or_the_series_page_make_an_event_series_wide(
    tids: tuple[int, ...], series_wide: bool
) -> None:
    [event] = group([flag(t, 10) for t in tids])

    assert event.series_wide is series_wide


def test_an_event_takes_its_most_serious_kind() -> None:
    [mixed] = group([flag(101, 10, "suspicious"), flag(102, 10, "boost"), flag(103, 11)])
    [no_bomb] = group([flag(101, 10, "suspicious"), flag(102, 10, "boost")])

    assert (mixed.kind, no_bomb.kind) == ("bomb", "boost")


def test_daily_surges_add_up_and_a_launch_lead_counts_once() -> None:
    daily = [flag(101, 20, extra=300), flag(101, 21, extra=200)]
    launch = [flag(102, n, launch=True, extra=1_000 + n) for n in (20, 21, 22)]

    [event] = group(daily + launch)

    assert event.extra_votes == 300 + 200 + 1_022


def test_bombs_rank_first_and_bigger_before_smaller() -> None:
    events = group(
        [
            flag(101, 10, "boost", extra=5_000),
            flag(201, 10, show=2, extra=100),
            flag(301, 10, show=3, extra=900),
        ]
    )

    assert [e.show for e in rank(events)] == [3, 2, SHOW]
