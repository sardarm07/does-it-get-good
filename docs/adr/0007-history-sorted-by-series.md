# 7. Sort the history by series

Accepted, 2026-10-10.

**Context.** Sorted by title, a month's file can skip every row group but a few for a show
whose episodes have neighbouring IDs. A show added to IMDb over decades has IDs spread
across the whole range: on the full history (1,352 days, 803 million rows), reading Days of
Our Lives' 15,478 episodes meant reading every row, and `getgood show` took 7 seconds.

**Decision.** Every row names its series, a series page naming itself, and each month's
file is sorted by series, then title, then date. A show's checks read its rows by series.
`getgood sync` gives older files the column once, from the current tables.

**Consequences.** Any show's rows read in about 30 ms, however long it ran, and
`getgood show` answers in under a second. The history is no bigger. An episode IMDb moves
to another series keeps its old series in the months written before the move.
