import hashlib
import json
from pathlib import Path
from typing import Any

from getgood.charts import VENDOR, VENDORED, write_page


def test_the_vendored_libraries_are_the_released_files() -> None:
    for name, (_package, _version, sha256) in VENDORED.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == sha256, name
    assert {p.name for p in VENDOR.iterdir()} == {
        *VENDORED,
        "LICENSE-d3",
        "LICENSE-plot",
        "README.md",
    }


def embedded(page: str) -> dict[str, Any]:
    start = page.index('<script type="application/json" id="answer">') + 44
    data: dict[str, Any] = json.loads(page[start : page.index("</script>", start)])
    return data


def test_a_page_holds_the_answer_and_loads_the_libraries_beside_it(tmp_path: Path) -> None:
    answer = {
        "series": {"id": "tt0000001", "title": "Grey's Anatomy"},
        "episodes": [[1, 1, 75, 100]],
    }

    page = write_page(answer, tmp_path)

    assert page == tmp_path / "tt0000001.html"
    html = page.read_text()
    assert embedded(html) == answer
    assert "<title>Grey&#x27;s Anatomy · Does it get good?</title>" in html
    assert html.index("vendor/d3.min.js") < html.index("vendor/plot.umd.min.js")
    for name, (_package, _version, sha256) in VENDORED.items():
        assert hashlib.sha256((tmp_path / "vendor" / name).read_bytes()).hexdigest() == sha256


def test_a_title_cannot_break_out_of_the_page(tmp_path: Path) -> None:
    title = "</script><script>alert(1)</script><!--title-->"
    answer = {"series": {"id": "tt0000002", "title": title}}

    html = write_page(answer, tmp_path).read_text()

    assert embedded(html)["series"]["title"] == title
    assert html.count("<script") == 4  # D3, Plot, the answer and the page's own code
    assert "<title>&lt;/script&gt;" in html
