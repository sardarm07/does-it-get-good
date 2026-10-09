"""Split a show's ratings into flat stretches with PELT.

A stretch costs the sum of squared distances of its ratings from the stretch's mean, and
each extra break costs a fixed penalty of 3 * sigma^2 * ln(n), so noise alone doesn't
create breaks. Sigma, the episode-to-episode noise, comes from the median jump between
neighbouring episodes. PELT (Killick, Fearnhead and Eckley, 2012) finds the split with the
lowest total exactly, while dropping start points that can no longer win.
"""

import math

import numpy as np
from numpy.typing import ArrayLike, NDArray

from getgood.config import MIN_STRETCH, NOISE_FLOOR, PENALTY_FACTOR

# For Gaussian noise with spread sigma, the median absolute difference between neighbours
# is 0.6745 * sqrt(2) * sigma.
MEDIAN_JUMP_TO_SIGMA = 1 / (0.6745 * math.sqrt(2))


def noise(x: ArrayLike) -> float:
    """Sigma: the typical episode-to-episode noise, never below NOISE_FLOOR."""
    v = np.asarray(x, dtype=np.float64)
    if len(v) < 2:
        return NOISE_FLOOR
    return max(NOISE_FLOOR, float(np.median(np.abs(np.diff(v)))) * MEDIAN_JUMP_TO_SIGMA)


def penalty(x: ArrayLike) -> float:
    """The cost of one extra break: PENALTY_FACTOR * sigma^2 * ln(n)."""
    v = np.asarray(x, dtype=np.float64)
    sigma = noise(v)
    return PENALTY_FACTOR * sigma * sigma * math.log(max(len(v), 2))


def stretches(x: ArrayLike, pen: float | None = None, *, min_size: int = MIN_STRETCH) -> list[int]:
    """The end (exclusive) of each flat stretch, the last being len(x)."""
    v = np.asarray(x, dtype=np.float64)
    n = len(v)
    if n < 2 * min_size:
        return [n] if n else []
    pen = penalty(v) if pen is None else pen
    s1 = np.concatenate(([0.0], np.cumsum(v)))
    s2 = np.concatenate(([0.0], np.cumsum(v * v)))

    def cost(starts: NDArray[np.int64], end: int) -> NDArray[np.float64]:
        total = s1[end] - s1[starts]
        return (s2[end] - s2[starts]) - total * total / (end - starts)

    never = np.iinfo(np.int64).max
    best = np.full(n + 1, np.inf)
    best[0] = -pen
    previous = np.zeros(n + 1, dtype=np.int64)
    starts = np.array([0], dtype=np.int64)  # where the last stretch may begin
    expires = np.array([never], dtype=np.int64)  # when PELT may drop each start
    for t in range(min_size, n + 1):
        alive = expires > t
        starts, expires = starts[alive], expires[alive]
        ready = t - starts >= min_size
        totals = best[starts[ready]] + cost(starts[ready], t)
        i = int(np.argmin(totals))
        best[t] = totals[i] + pen
        previous[t] = starts[ready][i]
        # A start that can't beat ending a stretch at t never wins once t itself can start
        # a stretch, min_size episodes from now. Dropping it any sooner could lose the best.
        beaten = np.zeros(len(starts), dtype=bool)
        beaten[ready] = totals > best[t]
        expires[beaten] = np.minimum(expires[beaten], t + min_size)
        starts = np.append(starts, t)
        expires = np.append(expires, never)

    ends: list[int] = []
    t = n
    while t > 0:
        ends.append(t)
        t = int(previous[t])
    return ends[::-1]


def objective(x: ArrayLike, ends: list[int], pen: float) -> float:
    """What PELT minimises: each stretch's squared spread, plus pen for every break."""
    v = np.asarray(x, dtype=np.float64)
    total, start = 0.0, 0
    for end in ends:
        part = v[start:end]
        total += float(((part - part.mean()) ** 2).sum())
        start = end
    return total + pen * (len(ends) - 1)
