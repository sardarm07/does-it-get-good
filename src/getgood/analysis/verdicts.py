"""Turn a show's flat stretches into a verdict: where it gets good, slumps and low points."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from getgood.analysis.pelt import noise, stretches
from getgood.analysis.shrink import damp
from getgood.config import (
    GOOD_BAR,
    HIGH_CONFIDENCE_VOTES,
    LOW_POINT_SIGMAS,
    MEDIUM_CONFIDENCE_VOTES,
    MIN_TURN_EPISODES,
    NEAR_MEDIAN,
    RISE,
    SLUMP_DROP,
)

type Kind = Literal["steady", "good_from_start", "gets_good", "no_clear_turn"]
type Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class Episode:
    season: int
    number: int
    rating: float
    votes: int

    @property
    def label(self) -> str:
        return f"S{self.season}E{self.number}"


@dataclass(frozen=True)
class Stretch:
    """Episodes start to end - 1 in the show's order, at one level of damped rating."""

    start: int
    end: int
    level: float


@dataclass(frozen=True)
class Slump:
    start: str
    end: str
    delta: float
    """The slump's level minus the show's level before it."""
    recovered: bool


@dataclass(frozen=True)
class Verdict:
    kind: Kind
    at: str | None
    """Where it gets good, or where a show good from the start gets even better."""
    confidence: Confidence
    reason: str
    median: float
    sigma: float
    stretches: tuple[Stretch, ...]
    slumps: tuple[Slump, ...]
    low_points: tuple[str, ...]
    damped: tuple[float, ...]
    """Each episode's rating after damping, in the same order."""


def judge(episodes: Sequence[Episode]) -> Verdict:
    """The verdict for one show, from its episodes in season and episode order."""
    x = damp([e.rating for e in episodes], [e.votes for e in episodes])
    sigma = noise(x)
    median = float(np.median(x))
    premieres = [i for i in range(1, len(episodes)) if episodes[i].season != episodes[i - 1].season]
    ends = stretches(x, premieres=premieres)
    parts = tuple(
        Stretch(start, end, float(x[start:end].mean()))
        for start, end in zip([0, *ends[:-1]], ends, strict=True)
    )
    kind, at, confidence, reason = _turn(episodes, x, parts, median, sigma)
    return Verdict(
        kind=kind,
        at=at,
        confidence=confidence,
        reason=reason,
        median=median,
        sigma=sigma,
        stretches=parts,
        slumps=_slumps(episodes, x, parts),
        low_points=_low_points(episodes, x, parts, sigma),
        damped=tuple(float(v) for v in x),
    )


def _turn(
    episodes: Sequence[Episode],
    x: NDArray[np.float64],
    parts: tuple[Stretch, ...],
    median: float,
    sigma: float,
) -> tuple[Kind, str | None, Confidence, str]:
    label = [e.label for e in episodes]
    first = parts[0]
    overall = _by_votes([e.votes for e in episodes])

    if len(parts) == 1:
        return (
            "steady",
            None,
            overall,
            (f"All {len(x)} episodes form one stretch averaging {first.level:.1f}."),
        )

    if first.level >= median - NEAR_MEDIAN or first.level > GOOD_BAR:
        reason = (
            f"{label[0]}–{label[first.end - 1]} average {first.level:.1f}, "
            f"against the show's median of {median:.1f}."
        )
        for i, part in enumerate(parts[1:], start=1):
            best_before = max(p.level for p in parts[:i])
            held = _held(parts, i, best_before + RISE)
            if held >= MIN_TURN_EPISODES:
                after = float(x[part.start : part.start + held].mean())
                reason += (
                    f" From {label[part.start]} the next {held} episodes "
                    f"average {after:.1f} ({after - best_before:+.1f})."
                )
                return "good_from_start", label[part.start], overall, reason
        return "good_from_start", None, overall, reason

    for i, part in enumerate(parts[1:], start=1):
        jump = part.level - parts[i - 1].level
        if jump < RISE or part.level < median - NEAR_MEDIAN:
            continue
        held = _held(parts, i, parts[i - 1].level + RISE)
        if held < MIN_TURN_EPISODES:
            continue
        before = float(x[: part.start].mean())
        after = float(x[part.start : part.start + held].mean())
        votes_before = float(np.median([e.votes for e in episodes[: part.start]]))
        if jump >= 2 * sigma and votes_before >= HIGH_CONFIDENCE_VOTES:
            confidence: Confidence = "high"
        elif jump >= sigma:
            confidence = "medium"
        else:
            confidence = "low"
        reason = (
            f"{label[0]}–{label[part.start - 1]} average {before:.1f}. "
            f"From {label[part.start]} the next {held} episodes "
            f"average {after:.1f} ({after - before:+.1f})."
        )
        return "gets_good", label[part.start], confidence, reason

    return (
        "no_clear_turn",
        None,
        overall,
        (
            f"It opens at {first.level:.1f}, below the show's median of {median:.1f}, "
            f"and never steps up {RISE} or more to it."
        ),
    )


def _held(parts: tuple[Stretch, ...], i: int, floor: float) -> int:
    """Episodes in the run of stretches from i on that stays at or above floor."""
    held = 0
    for part in parts[i:]:
        if part.level < floor:
            break
        held += part.end - part.start
    return held


def _slumps(
    episodes: Sequence[Episode], x: NDArray[np.float64], parts: tuple[Stretch, ...]
) -> tuple[Slump, ...]:
    """Later stretches well below the show's level before them: the mean of every earlier
    episode, so a decline that fills most of a run still counts. Back-to-back slumping
    stretches are one slump, measured from the level before it began."""
    slumping = [
        i
        for i, part in enumerate(parts)
        if i > 0 and part.level <= float(x[: part.start].mean()) - SLUMP_DROP
    ]
    runs: list[list[int]] = []
    for i in slumping:
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])

    found: list[Slump] = []
    for run in runs:
        start, end = parts[run[0]].start, parts[run[-1]].end
        before = float(x[:start].mean())
        found.append(
            Slump(
                start=episodes[start].label,
                end=episodes[end - 1].label,
                delta=float(x[start:end].mean()) - before,
                recovered=any(p.level >= before - NEAR_MEDIAN for p in parts[run[-1] + 1 :]),
            )
        )
    return tuple(found)


def _low_points(
    episodes: Sequence[Episode], x: NDArray[np.float64], parts: tuple[Stretch, ...], sigma: float
) -> tuple[str, ...]:
    return tuple(
        episodes[i].label
        for part in parts
        for i in range(part.start, part.end)
        if x[i] < part.level - LOW_POINT_SIGMAS * sigma
    )


def _by_votes(votes: Sequence[int]) -> Confidence:
    """Confidence for a verdict without a jump, from the show's median votes per episode."""
    typical = float(np.median(votes))
    if typical >= HIGH_CONFIDENCE_VOTES:
        return "high"
    if typical >= MEDIUM_CONFIDENCE_VOTES:
        return "medium"
    return "low"
