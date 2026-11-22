"""Stage a built AutoApply release for the tray's next service restart."""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version_directory")
    parser.add_argument("--restart", action="store_true", help="ask the running tray to restart the service into this release now")
    args = parser.parse_args()
    name = args.version_directory
    if not name or name in (".", "..") or Path(name).name != name:
        parser.error("pass one release directory name")

    root = Path(__file__).resolve().parents[1]
    data = Path(os.environ.get("AUTOAPPLY_DATA", root / "data")).resolve()
    release = data / "releases" / name
    if release.exists():
        parser.error("release directory already exists")

    uv = shutil.which("uv")
    npm = shutil.which("npm")
    if not uv or not npm:
        parser.error("uv and npm are required")
    build = data / "tmp" / ("release-ui-" + name)
    subprocess.run([npm, "ci"], cwd=root / "frontend", check=True)
    subprocess.run([npm, "run", "build", "--", "--outDir", str(build)], cwd=root / "frontend", check=True)

    release.mkdir(parents=True)
    for directory in ("backend", "scripts", "frontend/public", "frontend/src/i18n", "frontend/src/locales"):
        shutil.copytree(root / directory, release / directory, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(build, release / "frontend/dist")
    for filename in ("pyproject.toml", "uv.lock", "README.md", "LICENSE", "CHANGELOG.md"):
        shutil.copy2(root / filename, release / filename)
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(release / ".venv")}
    subprocess.run([uv, "sync", "--locked", "--no-dev", "--all-extras"], cwd=release, env=env, check=True)
    marker = data / "run" / "next-release"
    marker.parent.mkdir(parents=True, exist_ok=True)
    with marker.with_suffix(".pending").open("x", encoding="utf-8") as pending:
        pending.write(name)
    marker.with_suffix(".pending").replace(marker)
    print(f"Staged {release}")
    if args.restart:      # (the tray looks for this every few seconds: the same restart as its menu's)
        (marker.parent / "restart-request").write_text(name, encoding="utf-8")
        print("Asked the tray to restart the service")


if __name__ == "__main__":
    main()

