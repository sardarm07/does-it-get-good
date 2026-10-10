# 6. Store the history as one Parquet file per month

Accepted, 2026-10-10. Its sort order is replaced by [0007](0007-history-sorted-by-series.md).

**Context.** The history was first planned as one file per year. Folding new days into a
year meant re-sorting up to 250 million rows, and dropping duplicate days with a window over
every row: on 52 days of real data that spilled 3 GB to disk and ran for minutes.

**Decision.** Each sync writes new days to `data/history/days/`, then folds them into
`<year>-<month>.parquet`, sorted by title and then date. A day its month already holds is
skipped rather than deduplicated. Each month's file lists its days in its Parquet metadata.

**Consequences.** A month re-sorts in about a second, and the whole backfill compacts in
about a minute. Listing the history's days reads only file footers, and one show's history
still reads in milliseconds. Sorted by title, the history takes a fifth of the space of the
day files, under 1 GB in all.
