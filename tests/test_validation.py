import re
from datetime import date
from pathlib import Path

import pytest

from getgood import validation
from getgood.analysis.bombs import Event, Flag, Kind, group
from getgood.analysis.verdicts import judge
from getgood.config import CURRENT_DB
from getgood.load import build_current
from getgood.report import SERIES_PAGE
from getgood.validation import (
    FACTS,
    covered,
    draw_for_review,
    found_bomb,
    load_known_bombs,
    load_labels,
    load_reviewed,
    misses,
    score_coverage,
    score_review,
    score_search,
    score_speed,
    touches,
    write_reviewed,
)
from tests.helpers import day, downloads, show, two_bombs, write_fixture


def test_the_labels_file_is_well_formed() -> None:
    labels = load_labels()

    assert len(labels) == 30
    assert len({label["id"] for label in labels}) == 30
    for label in labels:
        assert re.fullmatch(r"tt\d{7,}", label["id"])
        assert set(label) <= {"id", "title", "note", *FACTS}
        assert any(fact in label for fact in FACTS), label["title"]


GETS_GOOD = show((6, 7.0), (20, 8.0), per_season=6)  # gets good at S2E1


@pytest.mark.parametrize(
    ("at", "passes"), [("S2E1", True), ("S2E4", True), ("S1E4", True), ("S2E5", False)]
)
def test_a_turn_may_be_three_episodes_from_its_label(at: str, passes: bool) -> None:
    assert (misses({"gets_good_at": at}, GETS_GOOD, judge(GETS_GOOD)) == []) == passes


def test_a_steady_show_counts_as_good_from_the_start() -> None:
    episodes = show((20, 8.0))

    assert misses({"good_from_start": True}, episodes, judge(episodes)) == []
    assert misses({"good_from_start": True}, GETS_GOOD, judge(GETS_GOOD)) == [
        "expected good from the start, got gets good at S2E1"
    ]


def test_a_slump_must_start_near_its_label() -> None:
    episodes = show((20, 9.0), (10, 8.0))  # slumps from S3E1

    assert misses({"slump_from": "S3E3"}, episodes, judge(episodes)) == []
    assert misses({"slump_from": "S2E1"}, episodes, judge(episodes)) == [
        "expected a slump from S2E1, got slumps: S3E1–S3E10"
    ]


def test_a_low_point_may_be_one_episode_off() -> None:
    episodes = show((10, 8.0), (1, 5.0), (10, 8.0), per_season=30)  # low point S1E11

    assert misses({"low_point": "S1E12"}, episodes, judge(episodes)) == []
    assert misses({"low_point": "S1E13"}, episodes, judge(episodes)) != []


def test_the_known_bombs_file_is_well_formed() -> None:
    bombs = load_known_bombs()

    assert len(bombs) == 10
    for bomb in bombs:
        assert set(bomb) == {"id", "title", "titles", "from", "to", "note", "sources"}
        assert re.fullmatch(r"tt\d{7,}", bomb["id"])
        assert all(re.fullmatch(r"series|S\d+(E\d+)?", t) for t in bomb["titles"])
        assert isinstance(bomb["from"], date) and bomb["from"] <= bomb["to"]
        assert bomb["from"] >= date(2022, 2, 22), "before the archive's first copy"
        assert bomb["sources"] and all(u.startswith("https://") for u in bomb["sources"])


SHOW = 1
LABELS = {SHOW: SERIES_PAGE, 11: "S1E1", 12: "S1E2", 41: "S4E1", 42: "S4E2"}


def event(tid: int, first: int, last: int, kind: Kind = "bomb") -> Event:
    flags = [
        Flag(tid, SHOW, day(n), kind, False, 1_000, 6.0, -0.5, 500.0, z=20.0)
        for n in range(first, last + 1)
    ]
    [e] = group(flags)
    return e


@pytest.mark.parametrize(
    ("tid", "titles", "hit"),
    [
        (SHOW, ["series"], True),
        (12, ["S1E2"], True),
        (42, ["series", "S4"], True),
        (12, ["S4"], False),
        (SHOW, ["S1E1"], False),
    ],
)
def test_an_event_touches_a_series_page_an_episode_or_a_season(
    tid: int, titles: list[str], hit: bool
) -> None:
    assert touches(event(tid, 10, 12), titles, LABELS) is hit


def test_a_known_bomb_needs_a_bomb_event_within_its_dates() -> None:
    known = {"titles": ["series"], "from": day(10), "to": day(20)}

    assert found_bomb(known, [event(SHOW, 18, 25)], LABELS) is not None
    assert found_bomb(known, [event(SHOW, 21, 25)], LABELS) is None
    assert found_bomb(known, [event(SHOW, 12, 14, "suspicious")], LABELS) is None


def test_a_known_bomb_counts_only_if_the_history_saw_its_days() -> None:
    known = {"from": day(10), "to": day(20)}

    assert covered(known, {day(8), day(15)})
    assert not covered(known, {day(15)})  # nothing just before: an arrival is unseen
    assert not covered(known, {day(5), day(25)})


def test_the_review_list_reads_back_as_written(tmp_path: Path) -> None:
    entries = [
        {
            "id": "tt0000001",
            "title": 'Grey\'s "Anatomy": Café',
            "from": day(25),
            "to": day(37),
            "summary": "S1E3: at launch, up to 3.9× the votes",
            "verdict": "real",
            "note": "a note: with a colon",
        }
    ]

    write_reviewed(entries, tmp_path / "reviewed.yaml")

    assert load_reviewed(tmp_path / "reviewed.yaml") == entries


def test_drawing_for_review_lists_each_bomb_once_and_keeps_verdicts(tmp_path: Path) -> None:
    data = two_bombs(tmp_path / "data")
    listed = tmp_path / "reviewed.yaml"

    assert draw_for_review(data, 1, listed) == 1
    first = load_reviewed(listed)
    first[0]["verdict"] = "real"
    write_reviewed(first, listed)
    assert draw_for_review(data, 5, listed) == 1
    assert draw_for_review(data, 5, listed) == 0

    entries = load_reviewed(listed)
    assert [(e["id"], e["from"], e["to"]) for e in entries] == [
        ("tt0000001", day(25), day(37)),
        ("tt0000001", day(50), day(50)),
    ]
    assert [e["verdict"] for e in entries].count("real") == 1


def test_precision_counts_the_reviewed_bombs_still_found(tmp_path: Path) -> None:
    data = two_bombs(tmp_path / "data")
    listed = tmp_path / "reviewed.yaml"
    draw_for_review(data, 2, listed)
    entries = load_reviewed(listed)
    entries[0]["verdict"], entries[1]["verdict"] = "real", "misread"
    gone = {**entries[0], "from": day(5), "to": day(6), "verdict": "misread"}
    write_reviewed([*entries, gone], listed)

    assert score_review(data, listed) is False  # 1 of 2: the event no longer found isn't counted

    entries[1]["verdict"] = "real"
    write_reviewed([*entries, gone], listed)
    assert score_review(data, listed) is True


@pytest.fixture
def tables(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir()
    write_fixture(raw)
    build_current(raw, tmp_path / CURRENT_DB, downloads(raw))
    return tmp_path


def test_every_series_in_scope_gets_a_verdict(
    tables: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert score_coverage(tables)
    assert "2/2 in-scope series get a verdict" in capsys.readouterr().out


def test_search_reports_a_show_that_doesnt_come_first(
    monkeypatch: pytest.MonkeyPatch, tables: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    labels = [
        {"id": "tt0000001", "title": "Grey's Anatomy"},
        {"id": "tt0000099", "title": "Café Noir"},
    ]
    monkeypatch.setattr(validation, "load_labels", lambda: labels)

    assert not score_search(tables)
    out = capsys.readouterr().out
    assert "MISS  'café noir' found Café Noir (2020), tt0000004" in out
    assert "1/2 labelled shows come first" in out


def test_speed_is_timed_on_the_real_command(
    tables: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert score_speed(tables)
    assert "getgood show tt0000001:" in capsys.readouterr().out
