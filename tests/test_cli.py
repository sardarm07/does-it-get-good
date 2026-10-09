from pathlib import Path

import pytest
from typer.testing import CliRunner

from getgood import __version__, cli
from getgood.cli import app
from getgood.fetch import Download, FetchError


def test_version_flag_prints_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"getgood {__version__}"


def test_no_arguments_shows_help() -> None:
    result = CliRunner().invoke(app, [])
    assert "Usage" in result.output


def test_sync_reports_each_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_fetch_all(raw_dir: Path) -> list[Download]:
        date = "Fri, 09 Oct 2026 00:39:31 GMT"
        return [
            Download(
                "title.ratings.tsv.gz",
                raw_dir / "r",
                changed=True,
                size=8_683_071,
                last_modified=date,
            ),
            Download(
                "title.episode.tsv.gz", raw_dir / "e", changed=False, size=1, last_modified=date
            ),
        ]

    monkeypatch.setattr(cli, "fetch_all", fake_fetch_all)
    result = CliRunner().invoke(app, ["sync", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "title.ratings.tsv.gz: downloaded 8.7 MB (IMDb's file of 2026-10-09)",
        "title.episode.tsv.gz: unchanged (IMDb's file of 2026-10-09)",
    ]


def test_sync_stops_with_a_clear_message(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def failing_fetch_all(raw_dir: Path) -> list[Download]:
        raise FetchError("title.basics.tsv.gz: HTTP 404")

    monkeypatch.setattr(cli, "fetch_all", failing_fetch_all)
    result = CliRunner().invoke(app, ["sync", "--data-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "Sync stopped: title.basics.tsv.gz: HTTP 404" in result.output
