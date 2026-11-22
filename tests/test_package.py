"""What a release carries: every file the server reads at run time - in the zip every package is made from
(scripts/make_release.py) and in the container image (Dockerfile). The server's messages moved to
frontend/src/locales/ while the package still kept only the old dictionary's place: a package would have said keys."""
from __future__ import annotations

import importlib.util


def _root():
    from autoapply import config

    return config.ROOT


def _needed() -> list[str]:
    """What the server reads from the interface's tree: its messages in every language and the list of languages."""
    from autoapply import say

    d = say.catalog_dir()
    files = sorted(d.glob("*.json")) + [d.parent / "languages.json"]
    assert len(files) >= 5 and all(f.is_file() for f in files)
    return [f.relative_to(_root()).as_posix() for f in files]


def test_the_package_carries_what_the_server_says():
    spec = importlib.util.spec_from_file_location("make_release", _root() / "scripts" / "make_release.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert [f for f in _needed() if m.LEAVE_OUT.search(f) or m.PERSONAL.search(f)] == []


def test_the_image_carries_it_too():
    copied = []
    for line in (_root() / "Dockerfile").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if parts[:1] == ["COPY"] and not any(p.startswith("--from") for p in parts):
            copied += [p.rstrip("/") for p in parts[1:-1]]
    for f in _needed():
        assert any(f == c or f.startswith(c + "/") for c in copied), f
