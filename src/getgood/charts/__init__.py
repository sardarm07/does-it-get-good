"""getgood show --chart: one HTML page per show, drawn with Observable Plot."""

from pathlib import Path

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
