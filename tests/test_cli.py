from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from getgood import __version__, cli
from getgood.cli import app
from getgood.fetch import Download, FetchError
from getgood.load import Build
from getgood.validate import Finding, Report

IMDB_DATE = "Fri, 09 Oct 2026 00:39:31 GMT"


def test_version_flag_prints_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"getgood {__version__}"


def test_no_arguments_shows_help() -> None:
    result = CliRunner().invoke(app, [])
    assert "Usage" in result.output


def fake_fetch_all(raw_dir: Path) -> list[Download]:
    return [
        Download("title.ratings.tsv.gz", raw_dir / "r", True, 8_683_071, IMDB_DATE),
        Download("title.episode.tsv.gz", raw_dir / "e", False, 1, IMDB_DATE),
    ]


def run_sync(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, report: Report, built: Build | None = None
) -> list[Report]:
    """Fake the downloads and checks for getgood sync; return the reports it remembers."""
    remembered: list[Report] = []

    def fake_check_files(raw_dir: Path, downloads: Sequence[Download], *, today: date) -> Report:
        return report

    def fake_remember_good(raw_dir: Path, downloads: Sequence[Download], report: Report) -> None:
        remembered.append(report)

    monkeypatch.setattr(cli, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(cli, "check_files", fake_check_files)

    def fake_build_current(raw_dir: Path, db_path: Path, downloads: Sequence[Download]) -> Build:
        return built or Build(series=2, rated_episodes=12)

    monkeypatch.setattr(cli, "remember_good", fake_remember_good)
    monkeypatch.setattr(cli, "build_current", fake_build_current)
    return remembered


def test_sync_reports_each_file_and_the_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    remembered = run_sync(monkeypatch, tmp_path, Report(already_checked=["title.episode.tsv.gz"]))
    result = CliRunner().invoke(app, ["sync", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "title.ratings.tsv.gz: downloaded 8.7 MB (IMDb's file of 2026-10-09)",
        "title.episode.tsv.gz: unchanged (IMDb's file of 2026-10-09)",
        "Checks passed (1 file checked, 1 already checked)",
        "Tables built: 2 series, 12 rated episodes",
    ]
    assert len(remembered) == 1


def test_sync_stops_when_a_check_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    problem = Finding("title.ratings.tsv.gz", "IDs that appear more than once: 3")
    remembered = run_sync(monkeypatch, tmp_path, Report(findings=[problem]))
    result = CliRunner().invoke(app, ["sync", "--data-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "Problem: title.ratings.tsv.gz: IDs that appear more than once: 3" in result.output
    assert "Sync stopped" in result.output
    assert remembered == []


def test_warnings_do_not_stop_the_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    warning = Finding("title.ratings.tsv.gz", "IMDb's newest file is 5 days old", blocking=False)
    remembered = run_sync(monkeypatch, tmp_path, Report(findings=[warning]))
    result = CliRunner().invoke(app, ["sync", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert "Warning: title.ratings.tsv.gz: IMDb's newest file is 5 days old" in result.output
    assert len(remembered) == 1


def test_sync_stops_when_a_download_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def failing_fetch_all(raw_dir: Path) -> list[Download]:
        raise FetchError("title.basics.tsv.gz: HTTP 404")

    monkeypatch.setattr(cli, "fetch_all", failing_fetch_all)
    result = CliRunner().invoke(app, ["sync", "--data-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "Sync stopped: title.basics.tsv.gz: HTTP 404" in result.output


def test_a_failed_build_stops_the_sync(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    problem = Finding("in-scope series", "count moved -50.0% since the last sync")
    run_sync(monkeypatch, tmp_path, Report(), Build(findings=[problem]))
    result = CliRunner().invoke(app, ["sync", "--data-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "Problem: in-scope series: count moved -50.0% since the last sync" in result.output
    assert "the tables from the last sync were kept" in result.output
