"""Damp low-vote ratings toward the show's vote-weighted mean.

An episode with 12 votes says far less than one with 12,000, so each rating is pulled
toward the show's mean C, harder when votes are few:

    x = (v * r + k * C) / (v + k)

With k = 10, an episode with 10 votes moves halfway to C, while one with 1,000 barely moves.
"""

import numpy as np
from numpy.typing import ArrayLike, NDArray

from getgood.config import DAMPING_K


def show_mean(ratings: ArrayLike, votes: ArrayLike) -> float:
    """C: the show's mean rating, weighted by each episode's votes."""
    r = np.asarray(ratings, dtype=np.float64)
    v = np.asarray(votes, dtype=np.float64)
    total = v.sum()
    if total == 0:
        return float(r.mean())
    return float((v * r).sum() / total)


def damp(ratings: ArrayLike, votes: ArrayLike, k: float = DAMPING_K) -> NDArray[np.float64]:
    """Each rating pulled toward the show's mean, by k votes' worth of it."""
    r = np.asarray(ratings, dtype=np.float64)
    v = np.asarray(votes, dtype=np.float64)
    if k == 0:
        return r.copy()
    c = show_mean(r, v)
    return (v * r + k * c) / (v + k)
