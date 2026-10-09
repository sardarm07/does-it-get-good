"""Paths, sources and tuning values in one place."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("GETGOOD_DATA", "data"))
"""Where everything downloaded from or derived from IMDb lives. Never committed."""

IMDB_BASE_URL = "https://datasets.imdbws.com/"
IMDB_FILES = ("title.basics.tsv.gz", "title.episode.tsv.gz", "title.ratings.tsv.gz")

RETRY_WAITS = (5.0, 30.0, 120.0)
"""Seconds to wait before each retry after a 429, a 5xx or a dropped connection."""

EXPECTED_COLUMNS = {
    "title.basics.tsv.gz": (
        "tconst",
        "titleType",
        "primaryTitle",
        "originalTitle",
        "isAdult",
        "startYear",
        "endYear",
        "runtimeMinutes",
        "genres",
    ),
    "title.episode.tsv.gz": ("tconst", "parentTconst", "seasonNumber", "episodeNumber"),
    "title.ratings.tsv.gz": ("tconst", "averageRating", "numVotes"),
}
"""Each file's header, in order. Any change stops the sync."""

ROW_COUNT_TOLERANCE = 0.02
"""How far a file's row count may move from the last good file, per ROW_COUNT_PERIOD_DAYS."""
ROW_COUNT_PERIOD_DAYS = 30

MAX_UNPARSED_NUMBERS = 0.001
"""Share of season and episode numbers that may fail to parse before the sync stops."""

MIN_VOTES = 5
"""IMDb leaves out titles with fewer votes. Seeing any means its cut-off changed."""

STALE_AFTER_DAYS = 3
"""Warn when IMDb's newest file is older than this."""
