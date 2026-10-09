import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import jsonschema
import pytest
from typer.testing import CliRunner

from getgood import __version__, cli
from getgood.backfill import Backfill
from getgood.cli import app
from getgood.config import CURRENT_DB
from getgood.fetch import Download, FetchError
from getgood.load import Build, build_current
from getgood.search import Found, Match
from getgood.validate import Finding, Report
from tests.helpers import downloads, season, write_fixture, write_history

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

    def fake_save_today(*args: object) -> date | None:
        return date(2026, 10, 9)

    def fake_backfill(*args: object, **kwargs: object) -> Backfill:
        archive_calls.append(kwargs)
        return Backfill(added=[date(2023, 1, 30), date(2023, 1, 31)])

    monkeypatch.setattr(cli, "remember_good", fake_remember_good)
    monkeypatch.setattr(cli, "build_current", fake_build_current)
    monkeypatch.setattr(cli, "save_today", fake_save_today)
    monkeypatch.setattr(cli, "backfill", fake_backfill)
    return remembered


archive_calls: list[dict[str, object]] = []


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
        "History: saved IMDb's file of 2026-10-09",
        "Archive: 2 days added",
        "History: empty",
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
    assert "Review bombs: unknown: the history is empty until getgood sync" in lines
    assert lines[-1] == "Information courtesy of IMDb (https://www.imdb.com). Used with permission."


@pytest.fixture
def bombed(data_dir: Path) -> Path:
    """The same tables, with a history in which Grey's Anatomy S1E3 was bombed at launch."""
    episodes = [1_000_001 + k for k in range(6)]  # S1E1 to S1E6
    write_history(data_dir / "history", season(1, episodes, bombed=1_000_003))
    return data_dir


def test_show_lists_review_bombs_from_the_history(bombed: Path) -> None:
    result = CliRunner().invoke(app, ["show", "greys anatomy", "--data-dir", str(bombed)])

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert (
        "Review bombs: 2023-01-26 to 2023-02-07, S1E3: at launch, up to 3.9× the votes of its "
        "season's other episodes and 2.0 below their rating"
    ) in lines
    assert "History:      60 days from 2023-01-01 to 2023-03-01" in lines
    assert not any(line.startswith(("Boosts:", "Vote surges:")) for line in lines)


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
    assert data["history"] is None


def test_show_json_includes_the_history_and_matches_the_schema(bombed: Path) -> None:
    result = CliRunner().invoke(app, ["show", "tt0000001", "--json", "--data-dir", str(bombed)])

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    schema = json.loads((Path(__file__).parents[1] / "schema" / "answer.schema.json").read_text())
    jsonschema.validate(data, schema, format_checker=jsonschema.FormatChecker())
    history = data["history"]
    assert (history["days"], history["first"], history["last"]) == (60, "2023-01-01", "2023-03-01")
    [event] = history["events"]
    assert event["kind"] == "bomb"
    assert (event["from"], event["to"], event["titles"]) == ("2023-01-26", "2023-02-07", ["S1E3"])
    assert event["series_wide"] is False
    assert event["extra_votes"] == 29_000 - 7_500  # its biggest lead, at 13 days old
    assert len(event["flags"]) == 13
    assert event["flags"][0] == {
        "title": "S1E3",
        "day": "2023-01-26",
        "launch": True,
        "votes": 5_000,
        "rating": 7.0,
        "rating_change": -2.0,
        "extra_votes": 3_500,
        "z": None,
        "ratio": 3.33,
        "new_votes_rating": None,
    }


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


def test_no_history_never_calls_the_archive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_sync(monkeypatch, tmp_path, Report())
    archive_calls.clear()

    result = CliRunner().invoke(app, ["sync", "--no-history", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert archive_calls == []
    assert "History: saved IMDb's file of 2026-10-09" in result.output


def last_run(data_dir: Path) -> dict[str, object]:
    run: dict[str, object] = json.loads((data_dir / "runs.jsonl").read_text().splitlines()[-1])
    return run


def test_each_sync_is_logged(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run_sync(monkeypatch, tmp_path, Report())

    CliRunner().invoke(app, ["sync", "--data-dir", str(tmp_path)])

    run = last_run(tmp_path)
    assert run["outcome"] == "ok"
    assert run["tables"] == {"series": 2, "rated_episodes": 12}
    assert run["archive"] == {"added": 2, "skipped": 0}
    assert run["files"] == {
        "title.ratings.tsv.gz": {"changed": True, "as_of": "2026-10-09"},
        "title.episode.tsv.gz": {"changed": False, "as_of": "2026-10-09"},
    }


def test_a_stopped_sync_is_logged_with_its_reason(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    problem = Finding("title.ratings.tsv.gz", "IDs that appear more than once: 3")
    run_sync(monkeypatch, tmp_path, Report(findings=[problem]))

    CliRunner().invoke(app, ["sync", "--data-dir", str(tmp_path)])

    run = last_run(tmp_path)
    assert run["outcome"] == "stopped"
    assert run["reason"] == "title.ratings.tsv.gz: IDs that appear more than once: 3"


def test_status_shows_the_tables_the_history_and_the_last_syncs(data_dir: Path) -> None:
    sync_line = {
        "started": "2026-10-09T21:40:00+00:00",
        "outcome": "ok",
        "seconds": 5.6,
        "files": {"title.ratings.tsv.gz": {"changed": True}},
        "history": {"days": 1},
    }
    (data_dir / "runs.jsonl").write_text(json.dumps(sync_line) + "\n")

    result = CliRunner().invoke(app, ["status", "--data-dir", str(data_dir)])

    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "Tables: 2 series, 12 rated episodes, IMDb's files of 2026-10-09",
        "History: empty",
        "Last syncs:",
        "  2026-10-09 21:40  ok           5.6 s  1 file downloaded, history 1 day",
    ]


def test_status_before_any_sync(tmp_path: Path) -> None:
    result = CliRunner().invoke(app, ["status", "--data-dir", str(tmp_path)])

    assert result.output.splitlines() == ["Tables: none yet. Run getgood sync.", "History: empty"]
