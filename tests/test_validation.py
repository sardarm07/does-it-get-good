import re

import pytest

from getgood.analysis.verdicts import judge
from getgood.validation import FACTS, load_labels, misses
from tests.helpers import show


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
