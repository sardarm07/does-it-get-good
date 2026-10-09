import pytest

from getgood.analysis.verdicts import Slump, judge
from tests.helpers import show


def test_one_stretch_is_steady() -> None:
    v = judge(show((20, 8.0)))

    assert (v.kind, v.at, v.confidence) == ("steady", None, "high")
    assert v.reason == "All 20 episodes form one stretch averaging 8.0."


def test_six_identical_episodes_are_steady() -> None:
    assert judge(show((6, 7.0), ripple=0)).kind == "steady"


def test_a_step_up_to_the_shows_level_is_where_it_gets_good() -> None:
    v = judge(show((6, 7.0), (20, 8.0), per_season=6))

    assert (v.kind, v.at, v.confidence) == ("gets_good", "S2E1", "high")
    assert v.reason == "S1E1–S1E6 average 7.0. From S2E1 the next 20 episodes average 8.0 (+1.0)."


def test_a_rise_that_stays_below_the_shows_level_is_not_the_turn() -> None:
    v = judge(show((8, 4.0), (8, 5.0), (24, 7.0), per_season=8))

    assert (v.kind, v.at) == ("gets_good", "S3E1")


def test_a_show_that_opens_at_its_level_is_good_from_the_start() -> None:
    v = judge(show((10, 9.0), (10, 8.0)))

    assert (v.kind, v.at) == ("good_from_start", None)
    level_before = v.stretches[0].level
    assert v.slumps == (
        Slump("S2E1", "S2E10", v.stretches[1].level - level_before, recovered=False),
    )


def test_a_lasting_rise_makes_it_even_better() -> None:
    v = judge(show((10, 8.5), (10, 9.2)))

    assert (v.kind, v.at) == ("good_from_start", "S2E1")
    assert v.reason.endswith("From S2E1 the next 10 episodes average 9.2 (+0.7).")


def test_a_short_peak_is_not_a_turn() -> None:
    v = judge(show((10, 8.5), (4, 9.8), (10, 8.5)))

    assert [(s.start, s.end) for s in v.stretches] == [(0, 10), (10, 14), (14, 24)]
    assert (v.kind, v.at) == ("good_from_start", None)


def test_a_rise_that_falls_back_within_six_episodes_is_not_the_turn() -> None:
    v = judge(show((10, 6.0), (4, 8.0), (10, 6.0), (20, 7.5), per_season=44))

    assert (v.kind, v.at) == ("gets_good", "S1E25")


@pytest.mark.parametrize(("votes", "confidence"), [(10, "low"), (50, "medium"), (500, "high")])
def test_without_a_jump_confidence_comes_from_the_votes(votes: int, confidence: str) -> None:
    assert judge(show((20, 8.0), votes=votes)).confidence == confidence


def test_a_small_rise_is_no_clear_turn() -> None:
    v = judge(show((100, 6.0), (100, 6.25)))

    assert len(v.stretches) == 2
    assert v.kind == "no_clear_turn"


def test_a_slump_that_climbs_back_is_recovered() -> None:
    v = judge(show((10, 8.0), (5, 7.0), (10, 8.0)))

    assert [(s.start, s.end, s.recovered) for s in v.slumps] == [("S2E1", "S2E5", True)]


def test_one_awful_episode_is_a_low_point_not_a_stretch() -> None:
    v = judge(show((10, 8.0), (1, 5.0), (10, 8.0), per_season=30))

    assert v.kind == "steady"
    assert v.low_points == ("S1E11",)


def test_few_votes_before_the_turn_lower_confidence() -> None:
    assert judge(show((6, 7.0), (20, 8.0), per_season=6, votes=50)).confidence == "medium"


def test_a_rise_smaller_than_the_noise_has_low_confidence() -> None:
    v = judge(show((400, 7.5), (400, 7.9), ripple=0.5))

    assert (v.kind, v.confidence) == ("gets_good", "low")


def test_back_to_back_slumping_stretches_are_one_slump() -> None:
    v = judge(show((20, 8.6), (10, 7.8), (10, 6.8)))

    assert [(s.start, s.end, s.recovered) for s in v.slumps] == [("S3E1", "S4E10", False)]
    assert v.slumps[0].delta == pytest.approx((7.8 + 6.8) / 2 - 8.6, abs=0.01)
