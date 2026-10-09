"""DuckDB helpers shared by the checks and the build."""

from pathlib import Path
from typing import Any

import duckdb

CSV_OPTIONS = "delim='\\t', header=true, nullstr='\\N', quote='', escape='', all_varchar=true"


def quote(path: Path) -> str:
    """A path as a SQL string literal."""
    return "'" + str(path).replace("'", "''") + "'"


def read_imdb(path: Path) -> str:
    """SQL that reads one of IMDb's gzipped TSV files, with every column as text."""
    return f"read_csv({quote(path)}, {CSV_OPTIONS})"


def scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> Any:
    """The first column of the first row, or None."""
    row = con.execute(sql, params).fetchone()
    return None if row is None else row[0]
