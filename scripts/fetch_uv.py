"""uv, the tool the installers bring along: one version, for every system a package is built for.

The packages carry uv itself instead of downloading its install script when they run. Each file is taken from uv's
GitHub release and checked against the SHA-256 below before it is used; a download that does not match is thrown
away and nothing is built.

    python scripts/fetch_uv.py <target> <output file> [--cache DIR]
        target: windows-x86_64 | linux-x86_64 | linux-aarch64 | macos-x86_64 | macos-aarch64

To move to a newer uv: change VERSION and every digest (the release page lists them next to the files).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "0.13.8"
FILES = {  # target: (file in the release, SHA-256 of that file)
    "windows-x86_64": ("uv-x86_64-pc-windows-msvc.zip", "529e78a9cec6cd7e3e014f7ecd8bda0c113969d4ed0f2efeedb85c30943325b8"),
    "linux-x86_64": ("uv-x86_64-unknown-linux-gnu.tar.gz", "5acfd9177cfecf0bf87578f059728215ccc884388988f55f7a65041b57387d91"),
    "linux-aarch64": ("uv-aarch64-unknown-linux-gnu.tar.gz", "74f2f5c6024d397481db228db8fc25eed420db192243f88438c118e7e013e585"),
    "macos-x86_64": ("uv-x86_64-apple-darwin.tar.gz", "a04c2ffeac28b2003a2c13caf538ab425fcd7def3e4a41571f4a8fb370a66af3"),
    "macos-aarch64": ("uv-aarch64-apple-darwin.tar.gz", "6b71028a6b904f2ae3340ef52e595512de807d06c0a20eaef2f692581b246558"),
}
URL = "https://github.com/astral-sh/uv/releases/download/{version}/{name}"


class Mismatch(Exception):
    pass


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=180) as r:  # noqa: S310 - a fixed https address
        return r.read()


def unpack(name: str, data: bytes) -> bytes:
    """The uv program itself, out of the release's archive."""
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return z.read(next(n for n in z.namelist() if n.rsplit("/", 1)[-1] == "uv.exe"))
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
        member = next(m for m in t.getmembers() if m.isfile() and m.name.rsplit("/", 1)[-1] == "uv")
        return t.extractfile(member).read()  # type: ignore[union-attr]


def fetch(target: str, cache: Path, get=download) -> bytes:
    """uv for `target`. The archive is kept in `cache` and checked every time it is used, kept or new."""
    name, expected = FILES[target]
    cache.mkdir(parents=True, exist_ok=True)
    kept = cache / f"uv-{VERSION}-{name}"
    if not kept.exists():
        print(f"downloading uv {VERSION} for {target}")
        kept.write_bytes(get(URL.format(version=VERSION, name=name)))
    data = kept.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        kept.unlink()
        raise Mismatch(f"uv {VERSION} for {target}: the file's SHA-256 is {digest}, not the expected {expected}")
    return unpack(name, data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", choices=sorted(FILES))
    ap.add_argument("output")
    ap.add_argument("--cache", default=str(Path(__file__).resolve().parents[1] / "dist-release" / ".cache"))
    a = ap.parse_args()
    try:
        data = fetch(a.target, Path(a.cache))
    except Mismatch as e:
        sys.exit(f"{e}. Nothing was written.")
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    if not a.target.startswith("windows"):
        out.chmod(0o755)
    print(f"{out}  uv {VERSION} ({a.target})")


if __name__ == "__main__":
    main()
