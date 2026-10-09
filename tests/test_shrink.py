import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from getgood.analysis.shrink import damp, show_mean

ratings = st.integers(10, 100).map(lambda tenths: tenths / 10)
votes = st.integers(5, 2_000_000)
episodes = st.lists(st.tuples(ratings, votes), min_size=1, max_size=200)
ks = st.floats(0, 1000)


def split(pairs: list[tuple[float, int]]) -> tuple[list[float], list[int]]:
    return [r for r, _ in pairs], [v for _, v in pairs]


def test_the_mean_is_weighted_by_votes() -> None:
    assert show_mean([8.0, 6.0], [300, 100]) == pytest.approx(7.5)


def test_ten_votes_move_an_episode_halfway_to_the_mean() -> None:
    r, v = [9.0, 7.0], [10, 1_000_000]
    c = show_mean(r, v)

    assert damp(r, v, k=10)[0] == pytest.approx((9.0 + c) / 2)


@given(episodes, ks)
def test_damped_ratings_lie_between_the_raw_rating_and_the_mean(
    pairs: list[tuple[float, int]], k: float
) -> None:
    r, v = split(pairs)
    x, c = damp(r, v, k), show_mean(r, v)

    assert np.all(x >= np.minimum(r, c) - 1e-9)
    assert np.all(x <= np.maximum(r, c) + 1e-9)


@given(episodes, ratings, votes, votes, st.floats(0.1, 1000))
def test_more_votes_means_less_pull(
    pairs: list[tuple[float, int]], rating: float, few: int, many: int, k: float
) -> None:
    few, many = sorted((few, many))
    r, v = split([*pairs, (rating, few), (rating, many)])
    x = damp(r, v, k)

    assert abs(x[-2] - rating) >= abs(x[-1] - rating) - 1e-9


@given(episodes)
def test_k_of_zero_changes_nothing(pairs: list[tuple[float, int]]) -> None:
    r, v = split(pairs)

    assert np.array_equal(damp(r, v, k=0), np.asarray(r))
