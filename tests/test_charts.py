import hashlib

from getgood.charts import VENDOR, VENDORED


def test_the_vendored_libraries_are_the_released_files() -> None:
    for name, (_package, _version, sha256) in VENDORED.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == sha256, name
    assert {p.name for p in VENDOR.iterdir()} == {
        *VENDORED,
        "LICENSE-d3",
        "LICENSE-plot",
        "README.md",
    }
