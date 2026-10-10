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
ARCHIVE_PAUSE = 5.0
"""Seconds between requests to the Internet Archive, a non-profit."""
ARCHIVE_WAITS = (60.0, 300.0, 900.0)
"""Seconds to wait before each retry after a 429, a 5xx, an offline page or a dropped
connection to the archive."""
PROBE_SETTLE_DAYS = 7
"""Probes of days this recent aren't remembered: the archive may not have their copies yet."""

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

MIN_BOMB_VOTES = 500
"""Titles with fewer votes are too thin to judge for bombs or contested episodes."""
SURGE_Z = 8.0
"""A surge: new votes per day this many robust standard deviations above the title's norm..."""
SURGE_MIN_VOTES = 50
SURGE_MIN_SHARE = 0.02
"""...and at least the larger of 50 votes or 2% of the title's total, per day."""
BASELINE_DAYS = 28
"""History days before each day that set a title's normal pace."""
MIN_BASELINE_DAYS = 7
"""Fewer earlier days than this, and a title isn't judged against its own pace yet."""
LAUNCH_DAYS = 14
"""A title this new is judged against its siblings, not its own pace."""
ARRIVAL_GROWTH = 5.0
"""A title whose votes grow this many times over within LAUNCH_DAYS either side of a day is
arriving that day, like a show rated before its release and then released: its own past
pace says nothing about what's normal, so it isn't judged against it. Releases measured
7 to 450 times over; the biggest bomb on a small show, 3."""
SHOCK_DROP = 0.2
"""A surge is a bomb if the rating falls at least this much that day, a boost if it rises."""
NEW_VOTES_ERROR = 1.0
"""The new votes' average is shown only when IMDb's rounding leaves it good to this many
points. It can't find bombs the rating change misses: being 3 points off the old rating
within 1 point of error already moves the rating by 0.3."""
LAUNCH_RATIO = 2.0
"""A launch surge: this many times the median votes of the season's other episodes at the
same age, the bar a contested episode clears..."""
LAUNCH_FINALE_RATIO = 3.0
"""...or this many for a season's last episode, which draws extra votes anyway..."""
LAUNCH_DROP = 0.5
"""...with a rating at least this far below theirs."""
PAGE_DROP = 0.5
"""A series page at launch flagged when it rates at least this far below its own episodes..."""
PAGE_EXCESS = 10_000
"""...and that gap takes at least this many low votes: the 1s it would take to drag the page
from its episodes' rating to its own. Episode ratings come mostly from fans, so most pages
sit below their episodes; it takes a crowd that rated the page without the episodes to
open a gap this wide on this many votes. Of 120 launches with 8,000 page votes in their first
two weeks, the five the press documented as bombs needed 12,800 to 40,400; no other, 6,000."""
EVENT_DAYS = 2
"""Flags on one show this close together are one event."""
RECENT_DAYS = 30
"""getgood bombs looks back this many days from the history's last day, unless told."""
SERIES_WIDE_EPISODES = 3
"""An event touching this many episodes, or the series page, is series-wide."""

CONTESTED_RATIO = 2.0
"""A contested episode has at least this many times its neighbours' median votes..."""
CONTESTED_EDGE_RATIO = 3.0
"""...or this many for a season premiere or finale, which draw extra votes anyway."""
CONTESTED_DROP = 0.5
"""...and rates at least this far below its neighbours' median."""
CONTESTED_NEIGHBOUR_VOTES = 200
"""Neighbours need this many median votes, so an established audience is being compared."""

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
