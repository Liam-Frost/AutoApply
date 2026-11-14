"""Build the Linux package: AutoApply-<version>-linux.run, one file that unpacks itself and starts the installer.

    uv run python scripts/make_linux.py [--out dist-release]          (can be built on any system)

    sh AutoApply-<version>-linux.run                 install / upgrade / repair (asks in windows if zenity is there, else in the terminal)
    sh AutoApply-<version>-linux.run --yes           without questions; all options of scripts/package/linux/install.sh pass through

The file is a small shell stub followed by a tar.gz with the installer, the release zip and the icon.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
from make_release import version  # noqa: E402

STUB = """#!/bin/sh
# AutoApply {version} for Linux: self-extracting installer. Run:  sh {name} [--yes] [--dir DIR] [--uninstall] ...
set -e
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
LINE=$(awk '/^__PAYLOAD__$/ {{ print NR + 1; exit }}' "$0")
tail -n +"$LINE" "$0" | tar -xz -C "$TMP"
bash "$TMP/install.sh" "$@"
exit $?
__PAYLOAD__
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist-release")
    a = ap.parse_args()
    out = ROOT / a.out
    ver = version()
    zip_path = out / f"AutoApply-{ver}.zip"
    if not zip_path.exists():
        subprocess.run([sys.executable, str(Path(__file__).parent / "make_release.py"), "--out", a.out], cwd=ROOT, check=True)
    name = f"AutoApply-{ver}-linux.run"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(arc: str, data: bytes, mode: int = 0o644) -> None:
            info = tarfile.TarInfo(arc)
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))

        add("install.sh", (ROOT / "scripts" / "package" / "linux" / "install.sh").read_bytes().replace(b"\r\n", b"\n"), 0o755)
        add("app.zip", zip_path.read_bytes())
        add("version.txt", ver.encode())
        add("autoapply.png", (ROOT / "frontend" / "public" / "favicon.png").read_bytes())
    target = out / name
    target.write_bytes(STUB.format(version=ver, name=name).encode() + buf.getvalue())
    try:
        target.chmod(0o755)
    except OSError:
        pass
    print(f"{target}  {target.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
