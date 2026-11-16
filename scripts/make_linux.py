"""Build the Linux package: AutoApply-<version>-linux.run, one file that unpacks itself and starts the installer.

    uv run python scripts/make_linux.py [--out dist-release]          (can be built on any system)

    sh AutoApply-<version>-linux.run                 install / upgrade / repair (asks in windows if zenity is there, else in the terminal)
    sh AutoApply-<version>-linux.run --yes           without questions; all options of scripts/package/linux/install.sh pass through

The file is a small shell stub followed by a tar.gz with the installer, the program's files, the icon, and uv for
x86_64 and for aarch64 (one fixed version, checked against its SHA-256 here: scripts/fetch_uv.py). The installer
therefore needs nothing but bash and tar on the computer, and downloads no script to run.
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
import fetch_uv  # noqa: E402
from make_release import version  # noqa: E402

STUB = """#!/bin/sh
# AutoApply {version} for Linux: self-extracting installer. Run:  sh {name} [--yes] [--dir DIR] [--uninstall] ...
set -e
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
LINE=$(awk '/^__PAYLOAD__$/ {{ print NR + 1; exit }}' "$0")
tail -n +"$LINE" "$0" | tar -xz -C "$TMP"
# said in full: with "set -e" some shells end with the trap's result instead of the installer's
rc=0
bash "$TMP/install.sh" "$@" || rc=$?
trap - EXIT
rm -rf "$TMP"
exit $rc
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
    package = ROOT / "scripts" / "package"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(arc: str, data: bytes, mode: int = 0o644) -> None:
            info = tarfile.TarInfo(arc)
            info.size, info.mode = len(data), mode
            tar.addfile(info, io.BytesIO(data))

        def script(path: Path) -> bytes:
            return path.read_bytes().replace(b"\r\n", b"\n")

        add("install.sh", script(package / "linux" / "install.sh"), 0o755)
        add("common.sh", script(package / "common.sh"))
        add("version.txt", ver.encode())
        add("autoapply.png", (ROOT / "frontend" / "public" / "favicon.png").read_bytes())
        # the program's files as they are, so that the installer needs no unzip
        prefix = f"AutoApply-{ver}/"
        with zipfile.ZipFile(zip_path) as z:
            for item in z.infolist():
                if item.is_dir() or not item.filename.startswith(prefix):
                    continue
                add("app/" + item.filename[len(prefix):], z.read(item), 0o755 if item.filename.endswith(".sh") else 0o644)
        for arch in ("x86_64", "aarch64"):
            try:
                add(f"uv-{arch}", fetch_uv.fetch(f"linux-{arch}", out / ".cache"), 0o755)
            except fetch_uv.Mismatch as e:
                sys.exit(f"{e}. Nothing was built.")
    target = out / name
    target.write_bytes(STUB.format(version=ver, name=name).encode() + buf.getvalue())
    try:
        target.chmod(0o755)
    except OSError:
        pass
    print(f"{target}  {target.stat().st_size / 1e6:.1f} MB  (uv {fetch_uv.VERSION})")


if __name__ == "__main__":
    main()
