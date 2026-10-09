import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from getgood.analysis.pelt import noise, objective, penalty, stretches
from getgood.config import NOISE_FLOOR


def brute_force(x: list[float], pen: float, premieres: list[int], min_size: int = 3) -> float:
    """The lowest objective over every split into stretches of at least min_size."""
    n, best = len(x), math.inf

    def search(start: int, ends: list[int]) -> None:
        nonlocal best
        if start == n:
            best = min(best, objective(x, ends, pen, premieres))
            return
        for end in range(start + min_size, n + 1):
            if end == n or n - end >= min_size:
                search(end, [*ends, end])

    search(0, [])
    return best


def test_a_planted_step_is_found() -> None:
    rng = np.random.default_rng(7)
    x = np.concatenate([np.full(20, 7.0), np.full(20, 8.0)]) + rng.normal(0, 0.1, 40)

    assert stretches(x) == [20, 40]


def test_pure_noise_is_usually_one_stretch() -> None:
    rng = np.random.default_rng(11)
    runs = [stretches(rng.normal(8.0, 0.2, 60)) for _ in range(200)]

    assert sum(r == [60] for r in runs) / len(runs) >= 0.9


def test_cheaper_breaks_at_premieres_still_leave_noise_alone() -> None:
    rng = np.random.default_rng(13)
    premieres = [20, 40]
    runs = [stretches(rng.normal(8.0, 0.2, 60), premieres=premieres) for _ in range(200)]

    assert sum(r == [60] for r in runs) / len(runs) >= 0.9


def test_a_smaller_step_counts_when_it_falls_on_a_premiere() -> None:
    x = [7.4 + (0.2 if i % 2 else -0.2) for i in range(6)]
    x += [7.95 + (0.2 if i % 2 else -0.2) for i in range(30)]

    assert stretches(x) == [36]
    assert stretches(x, premieres=[6]) == [6, 36]


def test_identical_ratings_are_one_stretch() -> None:
    assert stretches([7.5] * 30) == [30]


def test_series_too_short_to_split_are_one_stretch() -> None:
    assert stretches([7.0, 7.1, 9.5, 9.6, 9.4]) == [5]
    assert stretches([]) == []


@settings(max_examples=300)
@given(
    st.lists(st.integers(10, 100).map(lambda t: t / 10), min_size=6, max_size=12),
    st.lists(st.integers(1, 11), max_size=3),
)
def test_it_matches_a_brute_force_search(x: list[float], premieres: list[int]) -> None:
    pen = penalty(x)
    ends = stretches(x, pen, premieres=premieres)

    assert all(end - start >= 3 for start, end in zip([0, *ends], ends, strict=False))
    assert objective(x, ends, pen, premieres) == pytest.approx(
        brute_force(x, pen, premieres), abs=1e-9
    )


def test_noise_comes_from_the_median_jump() -> None:
    x = [7.0, 7.2, 7.0, 7.2, 7.0, 7.2]

    assert noise(x) == pytest.approx(0.2 / (0.6745 * math.sqrt(2)))
    assert noise([8.0] * 10) == 0.05


@pytest.mark.parametrize("x", [[], [7.5]])
def test_too_few_ratings_to_measure_noise_get_the_floor(x: list[float]) -> None:
    assert noise(x) == NOISE_FLOOR
