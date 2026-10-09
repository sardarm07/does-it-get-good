"""Paths, sources and tuning values in one place."""

import os
from datetime import date
from pathlib import Path

DATA_DIR = Path(os.environ.get("GETGOOD_DATA", "data"))
"""Where everything downloaded from or derived from IMDb lives. Never committed."""

IMDB_BASE_URL = "https://datasets.imdbws.com/"
IMDB_FILES = ("title.basics.tsv.gz", "title.episode.tsv.gz", "title.ratings.tsv.gz")

RETRY_WAITS = (5.0, 30.0, 120.0)
"""Seconds to wait before each retry after a 429, a 5xx or a dropped connection."""

HISTORY_START = date(2022, 2, 22)
"""The Internet Archive's near-daily copies of IMDb's ratings file begin here."""
MAX_GAP_DAYS = 3
"""History days further apart than this are reported as a gap."""
ARCHIVE_PAUSE = 2.0
"""Seconds between requests to the Internet Archive, a non-profit."""
ARCHIVE_WAITS = (60.0, 300.0, 900.0)
"""Seconds to wait before each retry after a 429, a 5xx, an offline page or a dropped
connection to the archive."""

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

CURRENT_DB = "current.duckdb"
"""Today's in-scope series, episodes and ratings, rebuilt by each sync."""

MIN_RATED_EPISODES = 6
"""A series needs this many rated, numbered episodes to be in scope."""
EXCLUDED_GENRES = ("Talk-Show", "News", "Reality-TV", "Game-Show")
"""Shows where "gets good" means little."""

DAMPING_K = 10.0
"""Votes' worth of the show's mean added to each episode: 10 votes moves an episode halfway."""

MIN_STRETCH = 3
"""Episodes in the shortest flat stretch PELT may find."""
PENALTY_FACTOR = 3.0
"""Each extra break costs PENALTY_FACTOR * sigma^2 * ln(n), so noise alone makes no breaks."""
PREMIERE_DISCOUNT = 0.5
"""A break where a season begins costs this share of the usual penalty: shows change most
between seasons. Tuned on the validation set; pure noise still stays one stretch 9 times in 10."""
NOISE_FLOOR = 0.05
"""Smallest episode-to-episode noise assumed; ratings are rounded to 0.1."""

GOOD_BAR = 8.1
"""A show opening above this is good from the start: the 75th percentile of show medians."""
RISE = 0.3
"""A step up at least this big, to the show's level, is where it gets good."""
MIN_TURN_EPISODES = 6
"""A step up must hold for this many episodes to count: a short peak isn't a turn."""
NEAR_MEDIAN = 0.1
"""Within this of the show's median counts as its usual level."""
SLUMP_DROP = 0.4
"""A later stretch at least this far below the show's level before it is a slump."""
LOW_POINT_SIGMAS = 3.0
"""A single episode this many noise widths below its stretch is a low point."""
HIGH_CONFIDENCE_VOTES = 100
"""Median votes per episode behind a high-confidence verdict."""
MEDIUM_CONFIDENCE_VOTES = 20

MIN_SIMILARITY = 0.88
"""Jaro-Winkler similarity a typed name needs to match a title it doesn't contain."""
SIMILAR_WITHIN = 0.03
"""Typo matches this close to the best one are worth asking about."""
ASK_RATIO = 0.05
"""Ask which show was meant when an equally good match has this share of the best one's votes."""

SCOPE_SIZE_TOLERANCE = 0.03
"""How far the number of in-scope series may move between syncs, per ROW_COUNT_PERIOD_DAYS."""
LOST_VOTES_TOLERANCE = 0.01
"""Share of titles that may lose votes between syncs, per ROW_COUNT_PERIOD_DAYS."""
