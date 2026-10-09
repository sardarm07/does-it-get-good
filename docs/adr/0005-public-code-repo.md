# 5. Publish the code, never the data

Accepted, 2026-10-09.

**Context.** The code is meant to be read and reused, but the data can't be shared (0004).

**Decision.** The repository is public and MIT-licensed, for the code only. `data/` and
every IMDb file type are git-ignored, and a pre-commit hook refuses `.tsv.gz`, `.parquet`
and `.duckdb` files. Tests use tiny hand-written files that only imitate IMDb's format;
examples use a made-up show.

**Consequences.** Anyone can run the tool, but must sync IMDb's data themselves. Validation
labels (turning points, documented bombs) are hand-written facts about shows, not IMDb
data, so they live in the repository.
