"""Release data: change fragments, versions, release manifests, the generated changelog and app data.

    python scripts/release.py change --type fixed --scope calendar --summary-en "..."   a new change fragment
    python scripts/release.py validate [--release X] [--strict]                        check everything
    python scripts/release.py status                                                   pending, next version, releases
    python scripts/release.py prepare --dry-run | --title-en "..." [--version X]       make a release
    python scripts/release.py generate [--check]                                       CHANGELOG.md, releases.json
    python scripts/release.py notes X                                                  a release's GitHub notes
    python scripts/release.py correct X ID --reason "..."                              change released text
    python scripts/release.py publish X [--yes]                                        check, then tag and push

Exit codes: 0 ok, 1 problems found, 2 usage error. All logic is in backend/autoapply/release/; needs PyYAML (a
dependency of the program: `uv run python scripts/release.py ...`). See docs/release-workflow.md.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from autoapply.release.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:], root=ROOT))
