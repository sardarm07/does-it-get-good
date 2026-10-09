# 3. Rebuild the rating history from the Internet Archive

Accepted, 2026-10-09.

**Context.** IMDb publishes only today's ratings, but review bombs are about change over
days. The Wayback Machine has saved IMDb's `title.ratings.tsv.gz` on most days since
2022-02-22.

**Decision.** `getgood sync` backfills the history from those copies: one request at a
time, a few seconds apart, waiting minutes after any sign of overload. Each copy is dated
by IMDb's own Last-Modified header, not the capture time, and checked like IMDb's own
files before it's kept. `--no-history` leaves the archive alone.

**Consequences.** More than four years of history on the first sync, at the price of about
10 GB of downloads over several hours, resumable at any point. Days the archive missed are
gaps, so changes are divided by the days between copies. Using the copies sits in a gray
area of IMDb's terms ("taken only from the datasets made available") and the archive's
("scholarship and research purposes"); the README says so.
