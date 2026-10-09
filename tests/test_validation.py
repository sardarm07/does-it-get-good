import re
from datetime import date

import pytest

from getgood.analysis.bombs import Event, Flag, Kind, group
from getgood.analysis.verdicts import judge
from getgood.report import SERIES_PAGE
from getgood.validation import (
    FACTS,
    covered,
    found_bomb,
    load_known_bombs,
    load_labels,
    misses,
    touches,
)
from tests.helpers import day, show


def test_the_labels_file_is_well_formed() -> None:
    labels = load_labels()

    assert len(labels) == 30
    assert len({label["id"] for label in labels}) == 30
    for label in labels:
        assert re.fullmatch(r"tt\d{7,}", label["id"])
        assert set(label) <= {"id", "title", "note", *FACTS}
        assert any(fact in label for fact in FACTS), label["title"]


GETS_GOOD = show((6, 7.0), (20, 8.0), per_season=6)  # gets good at S2E1


@pytest.mark.parametrize(
    ("at", "passes"), [("S2E1", True), ("S2E4", True), ("S1E4", True), ("S2E5", False)]
)
def test_a_turn_may_be_three_episodes_from_its_label(at: str, passes: bool) -> None:
    assert (misses({"gets_good_at": at}, GETS_GOOD, judge(GETS_GOOD)) == []) == passes


def test_a_steady_show_counts_as_good_from_the_start() -> None:
    episodes = show((20, 8.0))

    assert misses({"good_from_start": True}, episodes, judge(episodes)) == []
    assert misses({"good_from_start": True}, GETS_GOOD, judge(GETS_GOOD)) == [
        "expected good from the start, got gets good at S2E1"
    ]


def test_a_slump_must_start_near_its_label() -> None:
    episodes = show((20, 9.0), (10, 8.0))  # slumps from S3E1

    assert misses({"slump_from": "S3E3"}, episodes, judge(episodes)) == []
    assert misses({"slump_from": "S2E1"}, episodes, judge(episodes)) == [
        "expected a slump from S2E1, got slumps: S3E1–S3E10"
    ]


def test_a_low_point_may_be_one_episode_off() -> None:
    episodes = show((10, 8.0), (1, 5.0), (10, 8.0), per_season=30)  # low point S1E11

    assert misses({"low_point": "S1E12"}, episodes, judge(episodes)) == []
    assert misses({"low_point": "S1E13"}, episodes, judge(episodes)) != []


def test_the_known_bombs_file_is_well_formed() -> None:
    bombs = load_known_bombs()

    assert len(bombs) == 10
    for bomb in bombs:
        assert set(bomb) == {"id", "title", "titles", "from", "to", "note", "sources"}
        assert re.fullmatch(r"tt\d{7,}", bomb["id"])
        assert all(re.fullmatch(r"series|S\d+(E\d+)?", t) for t in bomb["titles"])
        assert isinstance(bomb["from"], date) and bomb["from"] <= bomb["to"]
        assert bomb["from"] >= date(2022, 2, 22), "before the archive's first copy"
        assert bomb["sources"] and all(u.startswith("https://") for u in bomb["sources"])


SHOW = 1
LABELS = {SHOW: SERIES_PAGE, 11: "S1E1", 12: "S1E2", 41: "S4E1", 42: "S4E2"}


def event(tid: int, first: int, last: int, kind: Kind = "bomb") -> Event:
    flags = [
        Flag(tid, SHOW, day(n), kind, False, 1_000, 6.0, -0.5, 500.0, z=20.0)
        for n in range(first, last + 1)
    ]
    [e] = group(flags)
    return e


@pytest.mark.parametrize(
    ("tid", "titles", "hit"),
    [
        (SHOW, ["series"], True),
        (12, ["S1E2"], True),
        (42, ["series", "S4"], True),
        (12, ["S4"], False),
        (SHOW, ["S1E1"], False),
    ],
)
def test_an_event_touches_a_series_page_an_episode_or_a_season(
    tid: int, titles: list[str], hit: bool
) -> None:
    assert touches(event(tid, 10, 12), titles, LABELS) is hit


def test_a_known_bomb_needs_a_bomb_event_within_its_dates() -> None:
    known = {"titles": ["series"], "from": day(10), "to": day(20)}

    assert found_bomb(known, [event(SHOW, 18, 25)], LABELS) is not None
    assert found_bomb(known, [event(SHOW, 21, 25)], LABELS) is None
    assert found_bomb(known, [event(SHOW, 12, 14, "suspicious")], LABELS) is None


def test_a_known_bomb_counts_only_if_the_history_saw_its_days() -> None:
    known = {"from": day(10), "to": day(20)}

    assert covered(known, {day(8), day(15)})
    assert not covered(known, {day(15)})  # nothing just before: an arrival is unseen
    assert not covered(known, {day(5), day(25)})
