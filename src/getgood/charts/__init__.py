"""getgood show --chart: one HTML page per show, drawn with Observable Plot."""

import hashlib
import html
import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

VENDOR = Path(__file__).with_name("vendor")
VENDORED = {
    "d3.min.js": (
        "d3",
        "7.9.0",
        "f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539",
    ),
    "plot.umd.min.js": (
        "@observablehq/plot",
        "0.6.17",
        "4358086467740777dd788d6b27a95cebdbaefdd50c730a3060117073bd7134cb",
    ),
}
"""Each vendored file: its npm package, version and SHA-256. Plot needs D3 loaded first."""
PAGE = Path(__file__).with_name("page.html")


def write_page(answer: Mapping[str, Any], charts_dir: Path) -> Path:
    """Write a show's chart page, and the libraries it loads, into charts_dir.

    The page is the answer getgood show --json prints, inside one HTML file. Returns its path.
    """
    vendor = charts_dir / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    for name, (_package, _version, sha256) in VENDORED.items():
        copy = vendor / name
        if not copy.exists() or hashlib.sha256(copy.read_bytes()).hexdigest() != sha256:
            shutil.copyfile(VENDOR / name, copy)
    # With every "<" escaped, the JSON can't close its script tag or hold the title marker.
    data = json.dumps(answer, ensure_ascii=False).replace("<", "\\u003c")
    title = html.escape(f"{answer['series']['title']} · Does it get good?")
    page = PAGE.read_text().replace("<!--answer-->", data).replace("<!--title-->", title)
    dest = charts_dir / f"{answer['series']['id']}.html"
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(page)
    tmp.replace(dest)
    return dest
