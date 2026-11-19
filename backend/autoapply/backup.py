"""Export everything the user has put into the program as one zip, restore it, and look for a newer release.

The export holds the database, uploaded and generated documents, and the knowledge folder (profile, scoring rules,
stories, notes about sites, edited prompts). It leaves out the screenshots of past runs (large, and reproducible) and,
unless asked, the saved sign-ins. Passwords and API keys live in the system keyring and are never in an export.

Restoring replaces the data folder, so it is done from the command line while the program is not running
(``autoapply restore <file.zip>``); what was there before is kept next to it as ``data.before-restore-<time>``.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import zipfile
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any

from . import config


def exports_dir() -> Path:
    """Where exports are kept: in the data folder as it is now (asked each time - it was fixed when this module was
    first loaded, which is the data folder of whoever loaded it first)."""
    return config.DATA / "exports"


NAME = re.compile(r"^autoapply-backup-\d{8}-\d{6}\.zip$")


def version() -> str:
    try:
        return metadata.version("autoapply")
    except metadata.PackageNotFoundError:
        m = re.search(r'^version\s*=\s*"([^"]+)"', (config.ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
        return m.group(1) if m else "0"


def export(*, sessions: bool = False) -> dict[str, Any]:
    kept = exports_dir()
    kept.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = kept / f"autoapply-backup-{stamp}.zip"
    snap = kept / f".db-{stamp}.tmp"
    src = sqlite3.connect(config.DB_PATH)
    try:  # a consistent copy even while the program is writing
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst)
        dst.close()
    finally:
        src.close()
    # (data/agent: what the agent wrote down about each application - its journal, what the application has used of its
    # budget, what the applicant said when they asked for it, the picture of the confirmation. An application that is
    # carried to another computer is taken up from these. The pictures it took on the way are left out: large, and of
    # no use to the next run.)
    folders = {"data/files": config.FILES, "data/materials": config.MATERIALS, "knowledge": config.KNOWLEDGE, "data/agent": config.DATA / "agent"}
    if sessions:
        folders["data/sessions"] = config.SESSIONS
    count = 1
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "data/app.db")
            for arc, folder in folders.items():
                for f in sorted(folder.rglob("*")):
                    if f.is_file() and "shots" not in f.relative_to(folder).parts:
                        z.write(f, f"{arc}/{f.relative_to(folder).as_posix()}")
                        count += 1
            z.writestr("manifest.json", json.dumps({"app": "autoapply", "version": version(), "created": datetime.now().isoformat(timespec="seconds"),
                                                    "sessions": sessions, "files": count}, indent=1))
    finally:
        snap.unlink(missing_ok=True)
    for old in sorted(kept.glob("autoapply-backup-*.zip"))[:-5]:  # keep the last five
        old.unlink(missing_ok=True)
    return {"name": target.name, "path": str(target), "size": target.stat().st_size, "files": count, "sessions": sessions}


def exports() -> list[dict[str, Any]]:
    """The exports that are kept on this computer, newest first: when each was made, how large it is, whether the saved
    sign-ins are in it - read from the export itself (its manifest), not remembered beside it."""
    out = []
    for f in sorted(exports_dir().glob("autoapply-backup-*.zip"), reverse=True) if exports_dir().exists() else []:
        if not NAME.match(f.name):
            continue
        try:
            with zipfile.ZipFile(f) as z:
                m = json.loads(z.read("manifest.json"))
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            continue      # not an export that can be read: not one to offer
        out.append({"name": f.name, "created": _moment(str(m.get("created") or ""), f), "size": f.stat().st_size, "files": int(m.get("files") or 0),
                    "sessions": bool(m.get("sessions")), "version": str(m.get("version") or "")})
    return out


def _moment(written: str, f: Path) -> str:
    """When an export was made, as a moment (with its offset): the manifest has this computer's clock time without
    one, which a page would read as another time zone's. The file's own time when the manifest has none."""
    try:
        made = datetime.fromisoformat(written) if written else datetime.fromtimestamp(f.stat().st_mtime)
    except ValueError:
        made = datetime.fromtimestamp(f.stat().st_mtime)
    return made.astimezone().isoformat(timespec="seconds")


def last() -> dict[str, Any] | None:
    got = exports()
    return got[0] if got else None


def path_of(name: str) -> Path:
    if not NAME.match(name) or not (exports_dir() / name).is_file():
        raise FileNotFoundError(name)
    return exports_dir() / name


def restore(zip_path: str | Path) -> dict[str, Any]:
    """Replace the data and knowledge folders with an export. Run while the program is stopped."""
    zp = Path(zip_path)
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
        if "manifest.json" not in names or "data/app.db" not in names:
            raise ValueError("this is not an AutoApply export (no manifest.json / data/app.db inside)")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("app") != "autoapply":
            raise ValueError("this is not an AutoApply export")
        bad = [n for n in names if n.startswith(("/", "\\")) or ".." in Path(n).parts or not (n == "manifest.json" or n.startswith(("data/", "knowledge/")))]
        if bad:
            raise ValueError(f"the archive contains paths outside data/ and knowledge/: {bad[:3]}")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        kept = []
        for folder in (config.DATA, config.KNOWLEDGE):
            if folder.exists() and any(folder.iterdir()):
                before = folder.with_name(f"{folder.name}.before-restore-{stamp}")
                shutil.copytree(folder, before, ignore=shutil.ignore_patterns("runs", "exports"))
                kept.append(str(before))
        for folder in (config.FILES, config.MATERIALS):
            shutil.rmtree(folder, ignore_errors=True)
        if manifest.get("sessions"):
            shutil.rmtree(config.SESSIONS, ignore_errors=True)
        for stale in (config.DB_PATH, config.DB_PATH.with_name(config.DB_PATH.name + "-wal"), config.DB_PATH.with_name(config.DB_PATH.name + "-shm")):
            stale.unlink(missing_ok=True)
        for n in names:
            if n == "manifest.json" or n.endswith("/"):
                continue
            base = config.DATA if n.startswith("data/") else config.KNOWLEDGE
            out = base / n.split("/", 1)[1]
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(z.read(n))
    return {"restored": len(names) - 1, "from_version": manifest.get("version"), "created": manifest.get("created"), "previous_kept_at": kept}


def _key(v: str) -> tuple:
    parts = re.findall(r"\d+|[a-z]+", v.lower().lstrip("v"))
    nums = [int(p) for p in parts if p.isdigit()]
    pre = next((p for p in parts if not p.isdigit()), "")
    return (nums[:3] + [0, 0, 0])[:3], 0 if pre else 1, pre, nums[3:] if pre else []


def check_update(repo: str) -> dict[str, Any]:
    """Ask GitHub for the newest release of ``repo`` ("owner/name"). Nothing about the user is sent. Never installs anything."""
    import httpx

    cur = version()
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo or ""):
        return {"current": cur, "error": "没有设置发布仓库"}
    try:
        with httpx.Client(timeout=15, headers={"User-Agent": "autoapply-update-check", "Accept": "application/vnd.github+json"}) as c:
            r = c.get(f"https://api.github.com/repos/{repo}/releases", params={"per_page": 10})
        if r.status_code == 404:
            return {"current": cur, "error": "没有找到这个发布仓库"}
        r.raise_for_status()
        rels = [x for x in r.json() if not x.get("draft")]
    except Exception as e:  # noqa: BLE001
        return {"current": cur, "error": f"查不到（{type(e).__name__}）。可能是网络不通，或 GitHub 暂时限制了访问。"}
    if not rels:
        return {"current": cur, "latest": "", "newer": False, "note": "这个仓库还没有发布过版本"}
    best = max(rels, key=lambda x: _key(x.get("tag_name") or "0"))
    tag = (best.get("tag_name") or "").lstrip("v")
    return {"current": cur, "latest": tag, "newer": _key(tag) > _key(cur), "url": best.get("html_url", ""), "published": (best.get("published_at") or "")[:10],
            "notes": (best.get("body") or "")[:1500]}
