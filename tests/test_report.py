from getgood.analysis.bombs import Flag, Kind, group
from getgood.analysis.verdicts import judge
from getgood.report import SERIES_PAGE, Answer, History
from getgood.search import Match
from tests.helpers import day, show

SHOW = 1
EPISODES = tuple(show((12, 8.0)))
LABELS = {SHOW: SERIES_PAGE} | {100 + i: e.label for i, e in enumerate(EPISODES, 1)}


def surge(
    tid: int, n: int, kind: Kind = "bomb", *, extra: float = 1_000, change: float = -0.3
) -> Flag:
    return Flag(
        tid=tid,
        show=SHOW,
        day=day(n),
        kind=kind,
        launch=False,
        votes=20_000,
        rating=7.5,
        rating_change=change,
        extra_votes=extra,
        z=40.0,
    )


def fields(*flags: Flag) -> list[str]:
    """The answer's lines from Review bombs on, for a history with these flags."""
    answer = Answer(
        as_of="2026-10-09",
        series=Match(SHOW, "Example Show", 2015, 2021, 20_000, 4.0),
        kind="tvSeries",
        episodes=EPISODES,
        verdict=judge(EPISODES),
        contested=(),
        labels=LABELS,
        history=History(60, day(0), day(59), tuple(group(flags))),
    )
    lines = answer.to_text().splitlines()
    return lines[lines.index(next(x for x in lines if x.startswith("Review bombs:"))) : -2]


def test_a_daily_bomb_names_its_titles_in_the_show_s_order() -> None:
    assert fields(surge(102, 20, extra=700), surge(SHOW, 21, extra=500, change=-0.2)) == [
        "Review bombs: 2023-01-21 to 2023-01-22, series page, S1E2: "
        "1,200 more votes than usual, rating -0.3",
        "History:      60 days from 2023-01-01 to 2023-03-01",
    ]


def test_a_title_s_rating_changes_add_up_across_the_event() -> None:
    lines = fields(surge(SHOW, 20, change=-0.3), surge(SHOW, 21, change=-0.4))

    assert lines[0].endswith("2,000 more votes than usual, rating -0.7")


def test_a_big_event_counts_its_episodes() -> None:
    lines = fields(surge(SHOW, 20), *(surge(101 + k, 20) for k in range(5)))

    assert lines[0].startswith("Review bombs: 2023-01-21, series page and 5 episodes: ")


def test_boosts_and_surges_get_their_own_lines_when_there_are_any() -> None:
    lines = fields(
        surge(101, 10, "boost", change=0.4),
        surge(102, 30, "suspicious", change=0.0),
        surge(103, 40, "suspicious", change=0.1),
    )

    assert lines == [
        "Review bombs: none",
        "Boosts:       2023-01-11, S1E1: 1,000 more votes than usual, rating +0.4",
        "Vote surges:  2023-01-31, S1E2: 1,000 more votes than usual, rating unmoved",
        "              2023-02-10, S1E3: 1,000 more votes than usual, rating +0.1",
        "History:      60 days from 2023-01-01 to 2023-03-01",
    ]


def test_a_mixed_event_is_named_for_its_kind() -> None:
    lines = fields(surge(SHOW, 20, change=0.3), surge(102, 20, change=-0.4))

    assert lines[0].endswith("2,000 more votes than usual, rating -0.4")
