# Does It Get Good?

Find the episode where a TV series gets good, where it slumps, and when it got review-bombed.

`getgood` is a command-line tool for personal use. It works from IMDb's free non-commercial datasets and keeps everything it downloads on your own machine.

> **Status:** early development. So far it only does `getgood --version`.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
make setup                     # Python dependencies and pre-commit hooks
uv tool install --editable .   # puts getgood on your PATH
getgood --version
```

## Development

```bash
make test                      # ruff, pyright and pytest
```

Changes go through pull requests with green CI. Commit messages and PR titles follow [Conventional Commits](https://www.conventionalcommits.org/).

## Data and licence

The code is MIT-licensed; see [LICENSE](LICENSE). The licence covers the code only, not IMDb's data. IMDb's datasets are for personal, non-commercial use, so this repository never contains IMDb data.

Information courtesy of IMDb (https://www.imdb.com). Used with permission.
