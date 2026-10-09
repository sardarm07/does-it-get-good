# Changelog

Notable changes, newest first. Versions follow [semantic versioning](https://semver.org/), and each milestone ends with a release.

## 0.1.0 (2026-10-09)

Verdicts in the terminal: milestone M1.

### Features

- `getgood sync` downloads IMDb's `title.basics`, `title.episode` and `title.ratings` with conditional requests, so unchanged files are skipped. A download replaces the old copy only once it's complete, and 429s, 5xx errors and dropped connections are retried.
- Every sync checks the files before using them: header columns, row counts against the last good file, rating and vote ranges, duplicate IDs and unparseable episode numbers. Old files and suspicious vote cut-offs only warn.
- Each sync rebuilds `data/current.duckdb`: every scripted series and miniseries with 6 or more rated episodes, with their episodes and ratings. Season 0 and episode 0 are left out. The new tables replace the old ones only if the scope and votes haven't moved too far.
- `getgood show <name>` finds a series by name, IMDb ID or year, asking when a name could mean several shows. It prints where the show gets good, its slumps and its low points, with a confidence and a reason. `--json` prints the same answer, described by `schema/answer.schema.json`.
- Verdicts come from ratings damped toward the show's mean, flat stretches found by PELT (with cheaper breaks at season premieres), and plain rules. A turn must hold for 6 episodes, and a slump is measured against the show's level before it.
- `make validate` scores the verdicts against 30 hand-labelled shows. 24 of 30 pass on the 2026-10-09 files.

### Infrastructure

- CI runs on every push: ruff, pyright in strict mode, pytest, a check that no IMDb data is tracked, and a Conventional Commit check on PR titles.
- Pre-commit hooks block large files, private keys and data files. Dependabot sends weekly grouped updates.
