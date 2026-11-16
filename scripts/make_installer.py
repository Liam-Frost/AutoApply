"""Build the Windows installer with Inno Setup 6: one .exe that installs AutoApply for the current user.

    uv run python scripts/make_installer.py [--out dist-release] [--test]

The installer carries the release zip's files (scripts/make_release.py) and uv, the tool that gets Python and the
dependencies. uv is one fixed version, downloaded here from its GitHub release and checked against the SHA-256
below - the installer itself downloads no program and runs no script from the network. What the installer does is in
scripts/package/windows/autoapply.iss; what happens after the files are copied is scripts/prepare.py.

Inno Setup: https://jrsoftware.org/isinfo.php  (winget install JRSoftware.InnoSetup, or choco install innosetup).

--test builds "AutoApply Test" with its own identity, so trying it out does not replace the registration, the
shortcuts or the sign-in entry of a real installation on the same computer.

Signing: set AUTOAPPLY_SIGN_COMMAND to the command that signs a file, with $f where the file goes, e.g.
    signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a $f
The installer and its uninstaller are then signed. Without it the .exe is not signed and Windows SmartScreen says
"Windows protected your PC" the first time (More info > Run anyway). Signing needs a certificate issued to the publisher.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
from make_release import version  # noqa: E402

# To move to a newer uv: change both lines. The digest is on the release page, next to the file.
UV_VERSION = "0.13.8"
UV_SHA256 = "529e78a9cec6cd7e3e014f7ecd8bda0c113969d4ed0f2efeedb85c30943325b8"
UV_URL = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"


def compiler() -> Path:
    found = shutil.which("ISCC")
    places = [Path(found)] if found else []
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("PROGRAMFILES", "")):
        if base:
            places += [Path(base) / "Programs" / "Inno Setup 6" / "ISCC.exe", Path(base) / "Inno Setup 6" / "ISCC.exe"]
    for p in places:
        if p.exists():
            return p
    sys.exit("Inno Setup 6 was not found. Install it: winget install JRSoftware.InnoSetup  (or: choco install innosetup)")


def fetch_uv(cache: Path) -> bytes:
    """uv.exe of the fixed version. The download is kept, and it is checked every time it is used."""
    cache.mkdir(parents=True, exist_ok=True)
    kept = cache / f"uv-{UV_VERSION}-x86_64-pc-windows-msvc.zip"
    if not kept.exists():
        print(f"downloading uv {UV_VERSION}")
        with urllib.request.urlopen(UV_URL, timeout=120) as r:  # noqa: S310 - a fixed https address
            kept.write_bytes(r.read())
    data = kept.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != UV_SHA256:
        kept.unlink()
        sys.exit(f"uv {UV_VERSION}: the download's SHA-256 is {digest}, not the expected {UV_SHA256}. Nothing was built.")
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        name = next(n for n in z.namelist() if n.endswith("uv.exe"))
        return z.read(name)


def main() -> None:
    if sys.platform != "win32":
        sys.exit("The installer is built on Windows (Inno Setup). On macOS and Linux see scripts/make_macos.sh and scripts/make_linux.py.")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist-release")
    ap.add_argument("--test", action="store_true", help="a copy with its own identity, for trying out next to a real installation")
    a = ap.parse_args()
    out = ROOT / a.out
    ver = version()
    zip_path = out / f"AutoApply-{ver}.zip"
    if not zip_path.exists():
        subprocess.run([sys.executable, str(Path(__file__).parent / "make_release.py"), "--out", a.out], cwd=ROOT, check=True)
    iscc = compiler()
    name = f"AutoApply-Test-Setup-{ver}" if a.test else f"AutoApply-Setup-{ver}"
    target = out / f"{name}.exe"
    target.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="aa-installer-") as tmp:
        stage = Path(tmp)
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(stage / "unzipped")
        (stage / "unzipped" / f"AutoApply-{ver}").rename(stage / "app")
        for needed in ("pyproject.toml", "uv.lock", "scripts/prepare.py", "frontend/dist/index.html"):
            if not (stage / "app" / needed).exists():
                sys.exit(f"The release zip has no {needed}: the installer would not work.")
        (stage / "uv.exe").write_bytes(fetch_uv(out / ".cache"))
        # Inno Setup reads a script as UTF-8 only when it starts with a byte-order mark
        script = stage / "autoapply.iss"
        script.write_text((ROOT / "scripts" / "package" / "windows" / "autoapply.iss").read_text(encoding="utf-8"), encoding="utf-8-sig")
        args = [str(iscc), "/Qp", f"/DAppVersion={ver}", f"/DStage={stage}", f"/DOutDir={out}", f"/DOutName={name}", f"/DRepo={ROOT}"]
        if a.test:
            args += ["/DTestBuild", "/DAppName=AutoApply Test", "/DAppGuid={5C0A1D52-77E3-4E0B-8B1F-2E9C6A4D7F10}"]
        sign = os.environ.get("AUTOAPPLY_SIGN_COMMAND")
        if sign:
            args += ["/DSign", f"/Ssign={sign}"]
        subprocess.run(args + [str(script)], check=True, cwd=stage)
    if not target.exists():
        sys.exit("Inno Setup did not produce the installer.")
    print(f"{target}  {target.stat().st_size / 1e6:.1f} MB  ({'signed' if sign else 'not code-signed'}, uv {UV_VERSION})")


if __name__ == "__main__":
    main()
