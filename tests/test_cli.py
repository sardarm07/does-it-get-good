import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from getgood import __version__, cli
from getgood.cli import app
from getgood.config import CURRENT_DB
from getgood.fetch import Download, FetchError
from getgood.load import Build, build_current
from getgood.search import Found, Match
from getgood.validate import Finding, Report
from tests.helpers import downloads, write_fixture

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


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """A data folder with tables built from the tiny scope fixture."""
    raw = tmp_path / "raw"
    raw.mkdir()
    write_fixture(raw)
    build_current(raw, tmp_path / CURRENT_DB, downloads(raw))
    return tmp_path


def test_show_prints_the_verdict_and_the_credit(data_dir: Path) -> None:
    result = CliRunner().invoke(app, ["show", "greys anatomy", "--data-dir", str(data_dir)])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert (
        lines[0]
        == "Grey's Anatomy (2005–) · tt0000001 · 6 rated episodes · IMDb's files of 2026-10-09"
    )
    assert lines[2].startswith("No clear turn (")
    assert lines[-1] == "Information courtesy of IMDb (https://www.imdb.com). Used with permission."


def test_show_json_matches_the_schema(data_dir: Path) -> None:
    result = CliRunner().invoke(app, ["show", "cafe noir", "--json", "--data-dir", str(data_dir)])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    schema = json.loads((Path(__file__).parents[1] / "schema" / "answer.schema.json").read_text())
    jsonschema.validate(data, schema, format_checker=jsonschema.FormatChecker())
    assert data["series"] == {
        "id": "tt0000004",
        "title": "Café Noir",
        "kind": "tvMiniSeries",
        "years": "2020",
        "start_year": 2020,
        "end_year": 2020,
        "votes": 100,
    }
    assert len(data["episodes"]) == 6


GREYS = Match(1, "Grey's Anatomy", 2005, None, 100, 4.0)
CAFE = Match(4, "Café Noir", 2020, 2020, 100, 4.0)


def finds_both(*args: object, **kwargs: object) -> Found:
    return Found(GREYS, (GREYS, CAFE))


def test_show_asks_which_show_a_name_means(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> None:
    monkeypatch.setattr(cli, "find", finds_both)

    result = CliRunner().invoke(app, ["show", "x", "--data-dir", str(data_dir)], input="7\n2\n")

    assert result.exit_code == 0, result.output
    assert "  2. Café Noir (2020), tt0000004" in result.output
    assert "Choose a number from 1 to 2." in result.output
    assert "Café Noir (2020) · tt0000004" in result.output


def test_show_json_never_asks(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> None:
    monkeypatch.setattr(cli, "find", finds_both)

    result = CliRunner().invoke(app, ["show", "x", "--json", "--data-dir", str(data_dir)])

    assert result.exit_code == 2
    assert "Add --year or give the IMDb ID to choose." in result.output


def test_show_explains_when_nothing_matches(data_dir: Path) -> None:
    result = CliRunner().invoke(app, ["show", "zzqqxx", "--data-dir", str(data_dir)])

    assert result.exit_code == 1
    assert 'No show matches "zzqqxx".' in result.output


def test_show_needs_a_sync_first(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["show", "anything", "--data-dir", str(tmp_path)])

    assert result.exit_code == 1
    assert "Run getgood sync first." in result.output
