# 2. DuckDB for all the data work

Accepted, 2026-10-09.

**Context.** IMDb's three files hold about 30 million rows of gzipped TSV, and the history
adds about 700,000 rows a day. Lookups for one show must answer in under 2 seconds.

**Decision.** DuckDB reads IMDb's files directly, builds `current.duckdb`, writes and reads
the history's Parquet files, and runs the bomb checks as SQL. Python handles only the
per-show analysis (damping, PELT and the verdict rules).

**Consequences.** No server and no ORM: a sync rebuilds the tables in about 5 seconds, and
one show's whole history reads in milliseconds. The bomb checks are SQL with window
functions, so the same query serves one show and every show. DuckDB spills to disk when a
query outgrows memory, so queries over every show work a month at a time (see 0006).
