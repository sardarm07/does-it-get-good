"""Find a series by the name someone types, or by its IMDb ID."""

import re
from dataclasses import dataclass

import duckdb

from getgood.config import ASK_RATIO, MIN_SIMILARITY, SIMILAR_WITHIN
from getgood.load import SEARCH_KEY

IMDB_ID = re.compile(r"^(?:tt)?(\d{5,9})$")

# Scores: 4 exact title, 3 start of the title, 2 a whole word or words inside it, 1 any part
# of it, and below 1 the Jaro-Winkler similarity of a near miss such as a typo. Spaces are
# also ignored, so "agents of shield" is an exact match for "Agents of S.H.I.E.L.D.".
QUERY = f"""
    WITH typed AS (SELECT {SEARCH_KEY.format("$name")} AS key),
    scored AS (
        SELECT s.tid, s.title, s.start_year, s.end_year, coalesce(r.votes, 0) AS votes,
               CASE
                   WHEN replace(s.search_key, ' ', '') = replace(t.key, ' ', '') THEN 4
                   WHEN starts_with(replace(s.search_key, ' ', ''), replace(t.key, ' ', ''))
                       THEN 3
                   WHEN contains(' ' || s.search_key || ' ', ' ' || t.key || ' ') THEN 2
                   WHEN contains(s.search_key, t.key) THEN 1
                   ELSE jaro_winkler_similarity(s.search_key, t.key)
               END AS score
        FROM series s LEFT JOIN ratings r USING (tid), typed t
        WHERE t.key <> ''
    )
    SELECT tid, title, start_year, end_year, votes, score
    FROM scored
    WHERE score >= $min_similarity
    ORDER BY score DESC, votes DESC, tid
    LIMIT 20
"""

BY_ID = """
    SELECT s.tid, s.title, s.start_year, s.end_year, coalesce(r.votes, 0), 4.0
    FROM series s LEFT JOIN ratings r USING (tid)
    WHERE s.tid = $tid
"""


@dataclass(frozen=True)
class Match:
    tid: int
    title: str
    start_year: int | None
    end_year: int | None
    votes: int
    score: float

    @property
    def imdb_id(self) -> str:
        return f"tt{self.tid:07d}"

    @property
    def years(self) -> str:
        if self.start_year is None:
            return "year unknown"
        if self.end_year is None:
            return f"{self.start_year}–"
        if self.end_year == self.start_year:
            return str(self.start_year)
        return f"{self.start_year}–{self.end_year}"


@dataclass(frozen=True)
class Found:
    """The best match, plus every match close enough to it that the user should choose."""

    best: Match | None
    choices: tuple[Match, ...] = ()

    @property
    def ambiguous(self) -> bool:
        return len(self.choices) > 1


def find(con: duckdb.DuckDBPyConnection, name: str, *, year: int | None = None) -> Found:
    """The series meant by `name`, ranked by how well the title matches, then by votes."""
    text = name.strip()
    if found_id := IMDB_ID.match(text):
        rows = con.execute(BY_ID, {"tid": int(found_id.group(1))}).fetchall()
    else:
        rows = con.execute(QUERY, {"name": text, "min_similarity": MIN_SIMILARITY}).fetchall()
    matches = [Match(*row) for row in rows]
    if year is not None:
        matches = [m for m in matches if m.start_year == year]
    if not matches:
        return Found(None)
    best = matches[0]
    close = tuple(m for m in matches if _close(m, best))[:5]
    return Found(best, close)


def _close(m: Match, best: Match) -> bool:
    """As good a match as the best, and not a namesake almost nobody watches."""
    if m.votes < ASK_RATIO * best.votes:
        return False
    if best.score >= 1:
        return int(m.score) == int(best.score)
    return m.score >= best.score - SIMILAR_WITHIN
