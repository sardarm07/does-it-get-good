"""Paths, sources and tuning values in one place."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("GETGOOD_DATA", "data"))
"""Where everything downloaded from or derived from IMDb lives. Never committed."""

IMDB_BASE_URL = "https://datasets.imdbws.com/"
IMDB_FILES = ("title.basics.tsv.gz", "title.episode.tsv.gz", "title.ratings.tsv.gz")

RETRY_WAITS = (5.0, 30.0, 120.0)
"""Seconds to wait before each retry after a 429, a 5xx or a dropped connection."""
