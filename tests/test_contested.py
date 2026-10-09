from getgood.analysis.contested import contested
from getgood.analysis.verdicts import Episode


def season(*changes: tuple[int, int, float], length: int = 9, votes: int = 1000) -> list[Episode]:
    """One season of `length` episodes at 8.0 with `votes` each, except (episode, votes, rating)."""
    special = {number: (v, r) for number, v, r in changes}
    return [
        Episode(1, n, special.get(n, (votes, 8.0))[1], special.get(n, (votes, 8.0))[0])
        for n in range(1, length + 1)
    ]


def test_a_pile_of_votes_and_a_low_rating_is_contested() -> None:
    found = contested(season((5, 3000, 7.0)))

    assert [(c.episode, c.vote_ratio, c.rating_gap) for c in found] == [("S1E5", 3.0, -1.0)]


def test_more_votes_alone_or_a_small_dip_is_not() -> None:
    assert contested(season((5, 1500, 7.0))) == ()
    assert contested(season((5, 3000, 7.7))) == ()


def test_premieres_and_finales_need_three_times_the_votes() -> None:
    assert contested(season((1, 2500, 7.0))) == ()
    assert [c.episode for c in contested(season((9, 3500, 7.0)))] == ["S1E9"]


def test_thin_audiences_are_not_judged() -> None:
    assert contested(season((5, 450, 6.0), votes=100)) == ()
    assert contested(season((5, 600, 6.0), votes=150)) == ()


def test_neighbours_come_from_the_same_season_only() -> None:
    next_season = [Episode(2, n, 8.0, 50_000) for n in range(1, 5)]

    assert [c.episode for c in contested([*season((5, 3000, 7.0)), *next_season])] == ["S1E5"]
