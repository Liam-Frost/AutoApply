"""Build the release package: one zip that runs after unzipping and double-clicking start.bat / start.sh.

It contains the source, the *built* interface (so Node.js is not needed) and the start scripts (which fetch uv, and
through it Python and the dependencies, on first run). It never contains anything personal: only files that are
tracked by git are taken, plus frontend/dist.

    uv run python scripts/make_release.py [--out dist-release] [--skip-build]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEAVE_OUT = re.compile(r"^(docs/images/|docs/private/|\.github/|scripts/demo\.py|scripts/make_[a-z]+\.(py|sh)|scripts/fetch_uv\.py|scripts/package/|Dockerfile$|\.dockerignore$|docker-compose\.yml$|tests/|\.gitattributes|\.gitignore|frontend/src/(?!i18n/[a-z-]+\.json$)|frontend/public/|frontend/[^/]+$)")
PERSONAL = re.compile(r"^(data/|knowledge/|docs/screens/|\.venv/|node_modules/)")


def version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "0"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist-release")
    ap.add_argument("--skip-build", action="store_true", help="use the frontend/dist that is already there")
    a = ap.parse_args()

    if not a.skip_build:
        npm = "npm.cmd" if sys.platform == "win32" else "npm"
        subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=ROOT / "frontend", check=True)
        subprocess.run([npm, "run", "build"], cwd=ROOT / "frontend", check=True)
    dist = ROOT / "frontend" / "dist"
    if not (dist / "index.html").exists():
        sys.exit("frontend/dist is missing: run without --skip-build")

    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split("\n")
    files = [f for f in tracked if f and not LEAVE_OUT.search(f) and not PERSONAL.search(f)]
    assert not any(PERSONAL.search(f) for f in files)
    files += [str(p.relative_to(ROOT)).replace("\\", "/") for p in dist.rglob("*") if p.is_file()]

    out = ROOT / a.out
    out.mkdir(exist_ok=True)
    name = f"AutoApply-{version()}"
    target = out / f"{name}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(set(files)):
            info = zipfile.ZipInfo.from_file(ROOT / f, f"{name}/{f}")
            info.compress_type = zipfile.ZIP_DEFLATED
            if f.endswith(".sh"):
                info.external_attr = 0o755 << 16  # keep it executable on macOS / Linux
            z.writestr(info, (ROOT / f).read_bytes())
    print(f"{target}  {len(set(files))} files  {target.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
