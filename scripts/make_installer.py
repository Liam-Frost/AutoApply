"""Build the Windows installer: one .exe that installs AutoApply for the current user.

    uv run python scripts/make_installer.py [--out dist-release]

It wraps the release zip (scripts/make_release.py) and scripts/setup.ps1 into a self-extracting program with IExpress,
which is part of Windows, so nothing has to be installed to build it. setup.ps1 is the whole installer: a window drawn
to the design system that installs, upgrades, repairs and removes the program (the same script, started with
-Mode uninstall, is what Settings > Apps runs).

The .exe is not code-signed. Windows SmartScreen will say "Windows protected your PC" the first time; the user
chooses "More info" > "Run anyway". Signing needs a certificate issued to the publisher.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
from make_release import version  # noqa: E402

CMD = """@echo off
rem Started by the self-extracting installer. Uses the 64-bit PowerShell when the extractor itself is 32-bit.
set "PS=%SystemRoot%\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
if exist "%SystemRoot%\\Sysnative\\WindowsPowerShell\\v1.0\\powershell.exe" set "PS=%SystemRoot%\\Sysnative\\WindowsPowerShell\\v1.0\\powershell.exe"
"%PS%" -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0setup.ps1" -Mode install %AUTOAPPLY_SETUP_ARGS%
"""

SED = """[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=%PostInstallCmd%
AdminQuietInstCmd=%AdminQuietInstCmd%
UserQuietInstCmd=%UserQuietInstCmd%
SourceFiles=SourceFiles
[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName={target}
FriendlyName=AutoApply {version} Setup
AppLaunched=cmd /c .\\install.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=
FILE0="app.zip"
FILE1="setup.ps1"
FILE2="install.cmd"
FILE3="logo.png"
FILE4="version.txt"
[SourceFiles]
SourceFiles0={stage}\\
[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
%FILE3%=
%FILE4%=
"""


def main() -> None:
    if sys.platform != "win32":
        sys.exit("The installer is built on Windows (it uses IExpress). On macOS and Linux the release zip with start.sh is the package.")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist-release")
    a = ap.parse_args()
    out = ROOT / a.out
    ver = version()
    zip_path = out / f"AutoApply-{ver}.zip"
    if not zip_path.exists():
        subprocess.run([sys.executable, str(Path(__file__).parent / "make_release.py"), "--out", a.out], cwd=ROOT, check=True)
    iexpress = Path(shutil.which("iexpress") or r"C:\Windows\System32\iexpress.exe")
    if not iexpress.exists():
        sys.exit("iexpress.exe was not found (it is part of Windows).")
    target = out / f"AutoApply-Setup-{ver}.exe"
    target.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="aa-installer-") as tmp:
        stage = Path(tmp)
        shutil.copy(zip_path, stage / "app.zip")
        # Windows PowerShell 5.1 reads a script without a byte-order mark as ANSI: the Chinese messages need the mark
        (stage / "setup.ps1").write_text((ROOT / "scripts" / "setup.ps1").read_text(encoding="utf-8-sig"), encoding="utf-8-sig", newline="\r\n")
        shutil.copy(ROOT / "frontend" / "public" / "favicon.png", stage / "logo.png")
        (stage / "version.txt").write_text(ver, encoding="ascii")
        (stage / "install.cmd").write_text(CMD, encoding="ascii", newline="\r\n")
        sed = stage / "setup.sed"
        sed.write_text(SED.format(target=target, version=ver, stage=stage), encoding="mbcs", newline="\r\n")
        subprocess.run([str(iexpress), "/N", "/Q", str(sed)], check=True, cwd=stage)
    if not target.exists():
        sys.exit("IExpress did not produce the installer.")
    print(f"{target}  {target.stat().st_size / 1e6:.1f} MB  (not code-signed)")


if __name__ == "__main__":
    main()
