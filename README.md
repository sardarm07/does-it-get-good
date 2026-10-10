# Does It Get Good?

Find the episode where a TV series gets good, where it slumps, and when it got review-bombed.

`getgood` is a command-line tool for personal use. It works from IMDb's free non-commercial datasets and keeps everything it downloads on your own machine.

> **Status:** everything works, on a history of 1,352 days back to February 2022. Verdicts, search and speed meet their targets; the review-bomb checks find 7 of 10 documented bombs, and about 6 in 10 of the events they call bombs are real, short of their targets of 8 and 7. The [methodology](docs/methodology.md#validation) says why.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
make setup                     # Python dependencies and pre-commit hooks
uv tool install --editable .   # puts getgood on your PATH
getgood --version
```

## Usage

```bash
getgood sync                   # download, check and load IMDb's latest files, and fill the history
getgood sync --no-history      # the same, without fetching past days from the Internet Archive
getgood status                 # the tables, the history and the last syncs
```

`sync` downloads only files IMDb has changed (about 292 MB the first time), checks them, and rebuilds `data/current.duckdb`: every scripted series and miniseries with 6 or more rated episodes, with their episodes and ratings. A file that fails a check stops the sync, and the tables from the last good sync are kept.

Each sync also keeps that day's ratings in a history, `data/history/`, and fills in past days from the Internet Archive's copies of IMDb's ratings file, which go back to February 2022. The first backfill downloads about 10 GB, one file every few seconds, and takes several hours; stop it any time and the next sync carries on. The history takes under 1 GB on disk. Every sync is logged in `data/runs.jsonl`.

The archive's copies are IMDb's own files, but using them sits in a gray area of IMDb's terms ("taken only from the datasets made available") and the archive's ("scholarship and research purposes"). `--no-history` leaves the archive alone; the history then starts from your first sync.

Data lives in `data/` under the current directory, or wherever `GETGOOD_DATA` points, and stays on your machine.

```bash
getgood show "parks and rec"            # where it gets good, slumps and low points
getgood show "the office" --year 2005   # choose between shows with the same name
getgood show tt1234567 --json           # by IMDb ID, as JSON (see schema/answer.schema.json)
getgood show "parks and rec" --chart    # the same answer drawn on a page in your browser
getgood bombs                           # the biggest review bombs of the history's last 30 days
getgood bombs --since 2023-01-01 --all  # since a date, with boosts and vote surges too
```

The answer for a made-up show looks like this:

```text
Example Show (2015–2021) · tt1234567 · 64 rated episodes · IMDb's files of 2026-10-09

Gets good at S2E3 (high confidence)
S1E1–S2E2 average 7.3. From S2E3 the next 31 episodes average 8.2 (+0.9).

Slumps:       S5E2–S5E9, 0.6 below its usual level
Low points:   S6E10
Contested:    S6E10, 4.2× its neighbours' votes, rated 1.9 below them
Review bombs: 2024-03-02 to 2024-03-04, series page, S6E10: 8,400 more votes than usual, rating -0.4
History:      1,412 days from 2022-02-21 to 2026-10-09

Information courtesy of IMDb (https://www.imdb.com). Used with permission.
```

`--chart` writes the answer to `data/charts/<id>.html` and opens it: every episode's rating with the stretches it splits into, the turn, slumps, low points and contested episodes marked, the votes behind each rating, and the series page's rating and votes day by day with review bombs marked. Hover for the numbers, or open the table. The page works offline.

Ratings with few votes are pulled toward the show's average before anything else happens, so a handful of votes can't create a turn. The verdict comes from splitting the episodes into flat stretches and reading the jumps between them; the reason line shows the numbers behind it.

Review bombs come from the history. Each day, every title's new votes are compared with its own usual pace: a surge far beyond it that drags the rating down, on votes well below it, is a review bomb, one that lifts the rating is a boost, and any other is a vote surge. A new episode has no pace of its own yet, so for its first two weeks it's compared with its season's other episodes at the same age, and a new show's series page with its own episodes: bombers rate the page without watching, so a page far below its episodes on a crowd of votes is a review bomb. Contested episodes come from today's numbers alone: far more votes than the episodes around them and a much lower rating. That can't be dated or told apart from honest backlash, so it isn't called a bomb.

## Development

```bash
make test                      # ruff, pyright and pytest with coverage; analysis/ must stay at 90%
make validate                  # score verdicts, bombs, search and speed against their targets (after a sync)
make review                    # draw review-bomb events into validation/reviewed_events.yaml to mark
make data                      # getgood sync --no-history
make history                   # getgood sync
make backup BACKUP_DIR=/Volumes/Drive/getgood   # copy the history somewhere safe
```

The history can be downloaded again only while the Internet Archive keeps its copies, so back it up now and then. Everything else in `data/` is rebuilt by a sync.

Changes are committed to `main` once `make test` passes, and CI checks every push. Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).

## Data and licence

The code is MIT-licensed; see [LICENSE](LICENSE). The licence covers the code only, not IMDb's data. IMDb's datasets are for personal, non-commercial use, so this repository never contains IMDb data.

Information courtesy of IMDb (https://www.imdb.com). Used with permission.
