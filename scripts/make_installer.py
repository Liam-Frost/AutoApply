"""Build the Windows installer: one .exe that installs AutoApply for the current user.

    uv run python scripts/make_installer.py [--out dist-release] [--test]

Three parts, one inside the other:
  the window     scripts/package/windows/setup (Setup.cs, Window.xaml): what people see, in the program's own design.
                 Compiled with the C# compiler that is part of Windows, so nothing has to be installed for it.
  the engine     scripts/package/windows/autoapply.iss: an Inno Setup 6 installer that the window carries inside
                 itself and runs without its wizard. It does the installing, registering and removing.
  the second half  scripts/prepare.py, run by the engine: dependencies, browser, and the way back.

The engine carries the release zip's files (scripts/make_release.py) and uv, the tool that gets Python and the
dependencies. uv is one fixed version, downloaded here from its GitHub release and checked against its SHA-256
(scripts/fetch_uv.py) - the installer itself downloads no program and runs no script from the network.

Inno Setup: https://jrsoftware.org/isinfo.php  (winget install JRSoftware.InnoSetup, or choco install innosetup).

--test builds "AutoApply Test" with its own identity, so trying it out does not replace the registration, the
shortcuts or the sign-in entry of a real installation on the same computer.

Signing: set AUTOAPPLY_SIGN_COMMAND to the command that signs a file, with $f where the file goes, e.g.
    signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /a $f
The installer, the engine inside it and the uninstaller are then signed (the small copy of the window that stays in
the program folder is not: sign it in the same way if you sign at all). Without it the .exe is not signed and Windows SmartScreen says
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
import fetch_uv  # noqa: E402
from make_release import version  # noqa: E402

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


def window(stage: Path, target: Path, ver: str, name: str, guid: str, test: bool, engine: Path | None) -> None:
    """Compile the setup window. With `engine` it is the download; without, the small copy that stays in the
    program folder for removing it."""
    base = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319"
    csc = base / "csc.exe"
    if not csc.exists():
        sys.exit(f"The C# compiler was not found at {csc} (it is part of Windows' .NET Framework 4).")
    src = ROOT / "scripts" / "package" / "windows" / "setup"
    four = (ver.split("-")[0] + ".0.0.0").split(".")[:4]
    info = stage / "BuildInfo.cs"
    info.write_text(
        "using System.Reflection;\n"
        f'[assembly: AssemblyTitle("{name} Setup")]\n[assembly: AssemblyProduct("{name}")]\n[assembly: AssemblyCompany("AutoApply")]\n'
        f'[assembly: AssemblyVersion("{".".join(four)}")]\n[assembly: AssemblyFileVersion("{".".join(four)}")]\n[assembly: AssemblyInformationalVersion("{ver}")]\n'
        f'static class Build {{ public static readonly string Version = "{ver}", AppName = "{name}", Guid = "{guid}"; public static readonly bool Test = {"true" if test else "false"}; }}\n',
        encoding="utf-8-sig")
    refs = ["System.dll", "System.Core.dll", "System.Xaml.dll", "System.Management.dll", "System.Windows.Forms.dll", "System.Drawing.dll",
            "WPF\\WindowsBase.dll", "WPF\\PresentationCore.dll", "WPF\\PresentationFramework.dll"]
    args = [str(csc), "/nologo", "/target:winexe", "/optimize+", "/codepage:65001", "/platform:anycpu", f"/out:{target}",
            f"/win32icon:{ROOT / 'scripts' / 'package' / 'windows' / 'autoapply.ico'}",
            f"/resource:{src / 'Window.xaml'},Window.xaml", f"/resource:{ROOT / 'frontend' / 'public' / 'favicon.png'},logo.png"]
    if engine is not None:
        args.append(f"/resource:{engine},engine.exe")
    args += [f"/reference:{base / r}" for r in refs]
    subprocess.run(args + [str(src / "Setup.cs"), str(info)], check=True, cwd=stage)


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
        try:
            (stage / "uv.exe").write_bytes(fetch_uv.fetch("windows-x86_64", out / ".cache"))
        except fetch_uv.Mismatch as e:
            sys.exit(f"{e}. Nothing was built.")
        # Inno Setup reads a script as UTF-8 only when it starts with a byte-order mark
        script = stage / "autoapply.iss"
        script.write_text((ROOT / "scripts" / "package" / "windows" / "autoapply.iss").read_text(encoding="utf-8"), encoding="utf-8-sig")
        app = "AutoApply Test" if a.test else "AutoApply"
        guid = "{5C0A1D52-77E3-4E0B-8B1F-2E9C6A4D7F10}" if a.test else "{B6E0E7A4-3D1C-4C7E-9A52-7F1B5A6D2C31}"
        window(stage, stage / "AutoApplySetup.exe", ver, app, guid, a.test, None)
        args = [str(iscc), "/Qp", f"/DAppVersion={ver}", f"/DStage={stage}", f"/DOutDir={stage}", "/DOutName=engine", f"/DRepo={ROOT}", f"/DAppName={app}", f"/DAppGuid={guid}"]
        if a.test:
            args += ["/DTestBuild"]
        sign = os.environ.get("AUTOAPPLY_SIGN_COMMAND")
        if sign:
            args += ["/DSign", f"/Ssign={sign}"]
        subprocess.run(args + [str(script)], check=True, cwd=stage)
        if not (stage / "engine.exe").exists():
            sys.exit("Inno Setup did not produce the installer.")
        window(stage, target, ver, app, guid, a.test, stage / "engine.exe")
        if sign:        # the engine and its uninstaller were signed by Inno Setup; the window that carries them is signed here
            subprocess.run(sign.replace("$f", f'"{target}"'), check=True, shell=True)
    if not target.exists():
        sys.exit("The installer was not produced.")
    print(f"{target}  {target.stat().st_size / 1e6:.1f} MB  ({'signed' if sign else 'not code-signed'}, uv {fetch_uv.VERSION})")


if __name__ == "__main__":
    main()
