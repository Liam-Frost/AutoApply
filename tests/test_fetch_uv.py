"""The uv the packages carry: one version, every file checked before it is used."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import re
import tarfile
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("fetch_uv", Path(__file__).resolve().parents[1] / "scripts" / "fetch_uv.py")
fetch_uv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_uv)


def archive(name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    if name.endswith(".zip"):
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("uv-x86_64-pc-windows-msvc/uv.exe", content)
    else:
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            info = tarfile.TarInfo(name[:-len(".tar.gz")] + "/uv")
            info.size = len(content)
            t.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_every_system_a_package_is_built_for_has_a_pinned_file():
    assert set(fetch_uv.FILES) == {"windows-x86_64", "linux-x86_64", "linux-aarch64", "macos-x86_64", "macos-aarch64"}
    for name, digest in fetch_uv.FILES.values():
        assert re.fullmatch(r"[0-9a-f]{64}", digest) and name.startswith("uv-")
    assert re.fullmatch(r"\d+\.\d+\.\d+", fetch_uv.VERSION)


@pytest.mark.parametrize("target", ["windows-x86_64", "linux-aarch64"])
def test_a_file_that_matches_is_unpacked_and_kept(tmp_path, monkeypatch, target):
    name = fetch_uv.FILES[target][0]
    data = archive(name, b"the program")
    monkeypatch.setitem(fetch_uv.FILES, target, (name, hashlib.sha256(data).hexdigest()))
    calls = []
    assert fetch_uv.fetch(target, tmp_path, get=lambda url: calls.append(url) or data) == b"the program"
    assert fetch_uv.fetch(target, tmp_path, get=lambda url: pytest.fail("downloaded again")) == b"the program"
    assert calls == [f"https://github.com/astral-sh/uv/releases/download/{fetch_uv.VERSION}/{name}"]


def test_a_file_that_does_not_match_is_thrown_away(tmp_path):
    with pytest.raises(fetch_uv.Mismatch):
        fetch_uv.fetch("linux-x86_64", tmp_path, get=lambda url: archive("uv-x86_64-unknown-linux-gnu.tar.gz", b"something else"))
    assert not list(tmp_path.iterdir())
