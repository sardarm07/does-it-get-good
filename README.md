# Does It Get Good?

Find the episode where a TV series gets good, where it slumps, and when it got review-bombed.

`getgood` is a command-line tool for personal use. It works from IMDb's free non-commercial datasets and keeps everything it downloads on your own machine.

> **Status:** early development. Verdicts work; rating history and review bombs come next.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
make setup                     # Python dependencies and pre-commit hooks
uv tool install --editable .   # puts getgood on your PATH
getgood --version
```

## Usage

```bash
getgood sync                   # download, check and load IMDb's latest files (about 292 MB the first time)
```

`sync` downloads only files IMDb has changed, checks them, and rebuilds `data/current.duckdb`: every scripted series and miniseries with 6 or more rated episodes, with their episodes and ratings. A file that fails a check stops the sync, and the tables from the last good sync are kept.

Data lives in `data/` under the current directory, or wherever `GETGOOD_DATA` points, and stays on your machine.

```bash
getgood show "parks and rec"            # where it gets good, slumps and low points
getgood show "the office" --year 2005   # choose between shows with the same name
getgood show tt1234567 --json           # by IMDb ID, as JSON (see schema/answer.schema.json)
```

The answer for a made-up show looks like this:

```text
Example Show (2015–2021) · tt1234567 · 64 rated episodes · IMDb's files of 2026-10-09

Gets good at S2E3 (high confidence)
S1E1–S2E2 average 7.3. From S2E3 the next 31 episodes average 8.2 (+0.9).

Slumps:     S5E2–S5E9, 0.6 below its usual level
Low points: S6E10

Information courtesy of IMDb (https://www.imdb.com). Used with permission.
```

Ratings with few votes are pulled toward the show's average before anything else happens, so a handful of votes can't create a turn. The verdict comes from splitting the episodes into flat stretches and reading the jumps between them; the reason line shows the numbers behind it.

## Development

```bash
make test                      # ruff, pyright and pytest
make validate                  # score the verdicts against validation/turning_points.yaml (after a sync)
```

Changes are committed to `main` once `make test` passes, and CI checks every push. Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).

Each milestone ends with a release: add its entry to `CHANGELOG.md`, bump the version in `pyproject.toml` and run `uv lock`, commit `chore(release): X.Y.Z`, then push an annotated tag `vX.Y.Z` and publish a GitHub Release with the changelog entry.

## Data and licence

The code is MIT-licensed; see [LICENSE](LICENSE). The licence covers the code only, not IMDb's data. IMDb's datasets are for personal, non-commercial use, so this repository never contains IMDb data.

Information courtesy of IMDb (https://www.imdb.com). Used with permission.
