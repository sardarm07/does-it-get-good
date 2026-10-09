"""Contested episodes: far more votes than their neighbours, and a much lower rating.

Today's numbers alone show where votes piled up on one episode. That works for any show,
with or without history, but it can't date anything or tell a review bomb from honest
backlash, so such an episode is called contested, never bombed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import groupby
from statistics import median

from getgood.analysis.verdicts import Episode
from getgood.config import (
    CONTESTED_DROP,
    CONTESTED_EDGE_RATIO,
    CONTESTED_NEIGHBOUR_VOTES,
    CONTESTED_RATIO,
    MIN_BOMB_VOTES,
)

NEIGHBOURS = 3
"""Episodes compared on each side, within the same season."""


@dataclass(frozen=True)
class Contested:
    episode: str
    votes: int
    rating: float
    neighbour_votes: float
    neighbour_rating: float

    @property
    def vote_ratio(self) -> float:
        return self.votes / self.neighbour_votes

    @property
    def rating_gap(self) -> float:
        return self.rating - self.neighbour_rating


def contested(episodes: Sequence[Episode]) -> tuple[Contested, ...]:
    """Every contested episode of one show, in order."""
    found: list[Contested] = []
    for _, group in groupby(episodes, key=lambda e: e.season):
        season = list(group)
        for j, e in enumerate(season):
            near = season[max(0, j - NEIGHBOURS) : j] + season[j + 1 : j + 1 + NEIGHBOURS]
            if e.votes < MIN_BOMB_VOTES or len(near) < 2:
                continue
            near_votes = median(n.votes for n in near)
            near_rating = median(n.rating for n in near)
            edge = j in (0, len(season) - 1)
            bar = CONTESTED_EDGE_RATIO if edge else CONTESTED_RATIO
            if (
                near_votes >= CONTESTED_NEIGHBOUR_VOTES
                and e.votes >= bar * near_votes
                and e.rating - near_rating <= -CONTESTED_DROP
            ):
                found.append(Contested(e.label, e.votes, e.rating, near_votes, near_rating))
    return tuple(found)
