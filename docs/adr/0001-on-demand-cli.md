# 1. Answer questions on demand from a local CLI

Accepted, 2026-10-09.

**Context.** The first plan was a daily GitHub Actions job that snapshotted IMDb's ratings
into cloud storage and published a static site. Nothing could be answered until months of
snapshots had piled up, and it needed a cloud account, a site and a job to watch.

**Decision.** A command-line tool, `getgood`, that downloads IMDb's files when asked
(`getgood sync`) and answers about one show at a time (`getgood show`), from local data.
Past days come from the Internet Archive instead of waiting for snapshots (see 0003).

**Consequences.** Answers about review bombs are available on the first day, back to
February 2022. There is nothing to host or monitor and no cost. Bombs are found when a show
is looked up, not as they happen: live alerts are a non-goal.
