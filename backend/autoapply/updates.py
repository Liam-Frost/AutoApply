"""Updates: the program looks for a newer release, fetches it, checks it, puts it next to the one that runs, and has the
tray switch over - by hand, or by itself when nothing is being done.

What it does, in order:
- **look** - GitHub's list of releases of the publishing repository (``update.repo``); stable releases only, or the
  pre-releases too (``update.channel``). Nothing about the applicant is sent.
- **fetch** - the portable package of that release and its ``SHA256SUMS.txt``; a package whose checksum does not match is
  thrown away. Only the repository set, only over HTTPS.
- **prepare** - unpacked into ``data/releases/<version>``, its dependencies installed from its lock file, the browser
  it needs. Nothing in the package is run. The version that runs is not touched.
- **switch** - the tray's own restart (launcher.py): it backs the database up, tries the new version, lets the old one
  finish what it has in hand and hands over; a new version that does not start is left and the old one goes on.

``update.mode``: off | notify (look once a day and say so - the default) | download (also fetch and prepare; the
switch is pressed) | auto (switch too, when idle: nothing applying or waiting in the queue, no window kept for an
approval, no window open for the applicant, inside ``update.window``). An installation run from a source checkout or
in a container does not update itself: it is told how.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import config, db

log = logging.getLogger("autoapply.updates")

STATE = "update.state"          # what is known: {checked_at, latest, url, notes, published, prerelease, assets, status, progress, error, staged, notified}
MODES = ("off", "notify", "download", "auto")
_busy = threading.Lock()


def version() -> str:
    from .backup import version as v

    return v()


def _key(v: str) -> tuple:
    from .backup import _key as k

    return k(v)


def kind() -> str:
    """How this installation runs: "managed" (the tray starts it: it can switch), "unmanaged" (started by hand: it can
    prepare, the switch is a restart), "source" (a git checkout), "container"."""
    if Path("/.dockerenv").exists() or os.environ.get("AUTOAPPLY_CONTAINER"):
        return "container"
    if (config.ROOT / ".git").exists():
        return "source"
    return "managed" if os.environ.get("AUTOAPPLY_ROOT") else "unmanaged"


def state() -> dict[str, Any]:
    return dict(db.get_setting(STATE) or {})


def _save(**changes: Any) -> dict[str, Any]:
    s = {**state(), **changes}
    db.set_setting(STATE, s)
    return s


def status() -> dict[str, Any]:
    """What the about page shows. A release is named by its folder in data/releases (``staged``, ``previous``,
    ``switching_to``, ``pending``, ``build``); each comes with ``<name>_release`` - what that folder is (release())."""
    s = state()
    cur = version()
    latest = str(s.get("latest") or "")
    rel = config.DATA / "releases"
    staged = str(s.get("staged") or "")
    if staged and _key(staged) <= _key(cur):      # (what was prepared is what runs, or older: nothing to switch to)
        staged = ""
    kept = staged if staged and (rel / staged).is_dir() else ""
    previous, build, switching = _previous(), running(), str(s.get("switching_to") or "")
    pending = _next_release()
    if pending in (build, switching):      # (the one that runs, or the switch under way: nothing more to say)
        pending = ""
    return {"current": cur, "kind": kind(), "mode": db.get_setting("update.mode") or "notify", "channel": db.get_setting("update.channel") or "stable",
            "window": db.get_setting("update.window") or {}, "latest": latest, "newer": bool(latest) and _key(latest) > _key(cur),
            "url": s.get("url", ""), "notes": s.get("notes", ""), "published": s.get("published", ""), "prerelease": bool(s.get("prerelease")),
            "checked_at": s.get("checked_at", ""), "status": "idle" if s.get("status") == "ready" and not staged else s.get("status", "idle"),
            "progress": s.get("progress", 0), "error": s.get("error", ""),
            "staged": kept, "previous": previous, "history": (s.get("history") or [])[-10:],
            # (added for the about page: each folder as a person reads it, and the switch asked for that has not happened yet)
            "staged_release": release(kept), "previous_release": release(previous), "build": build, "build_release": release(build),
            "switching_to": switching, "switching_release": release(switching),
            "pending": pending, "pending_release": release(pending), "when_idle": str(s.get("when_idle") or "")}


def _name_ok(name: str) -> bool:
    return bool(name) and Path(name).name == name and name not in (".", "..")


def release(name: str) -> dict[str, Any] | None:
    """A folder of data/releases as the about page names it: ``version`` - what its own pyproject.toml says ("" when it
    says nothing); ``date`` - the day its name starts with ("2026-11-22-calendar"), else the day its interface was built
    or unpacked; ``local`` - put there by hand (scripts/stage_local_release.py: the updater names a folder by the version
    it fetched). None when there is no such folder."""
    if not _name_ok(name):
        return None
    d = config.DATA / "releases" / name
    if not d.is_dir():
        return None
    ver = ""
    try:
        m = re.search(r'^version\s*=\s*"([^"]+)"', (d / "pyproject.toml").read_text(encoding="utf-8", errors="replace"), re.M)
        ver = m.group(1) if m else ""
    except OSError:
        pass
    day = ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?!\d)", name)
    if m:
        try:
            day = datetime.strptime(m.group(1), "%Y-%m-%d").date().isoformat()
        except ValueError:
            day = ""
    if not day:
        for f in (d / "frontend" / "dist" / "index.html", d / "pyproject.toml"):
            if f.is_file():
                day = datetime.fromtimestamp(f.stat().st_mtime).date().isoformat()
                break
    return {"name": name, "version": ver, "date": day, "local": name != ver}


def running() -> str:
    """The folder of data/releases this copy runs from - "" when it runs from anywhere else (the installation's own
    folder, a checkout, a container)."""
    here = config.ROOT.resolve()
    return here.name if here.parent == (config.DATA / "releases").resolve() else ""


def _next_release() -> str:
    """The release the tray starts at its next restart (data/run/next-release: written by a switch, or by
    scripts/stage_local_release.py) - when the marker names a folder the tray can start."""
    marker = config.DATA / "run" / "next-release"
    try:
        name = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
    except OSError:
        return ""
    return name if _name_ok(name) and (config.DATA / "releases" / name / "frontend" / "dist" / "index.html").is_file() else ""


# --- look ------------------------------------------------------------------------------------------------------------------
def check() -> dict[str, Any]:
    """Ask GitHub for the newest release (of the channel chosen). Never installs anything."""
    import httpx

    repo = str(db.get_setting("update.repo") or "")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        return _save(error="no-repo", checked_at=datetime.now().isoformat(timespec="minutes"))
    beta = db.get_setting("update.channel") == "beta"
    try:
        with httpx.Client(timeout=20, headers={"User-Agent": "autoapply-update-check", "Accept": "application/vnd.github+json"}) as c:
            r = c.get(f"https://api.github.com/repos/{repo}/releases", params={"per_page": 20})
        r.raise_for_status()
        rels = [x for x in r.json() if not x.get("draft") and (beta or not x.get("prerelease"))]
    except Exception as e:  # noqa: BLE001 - the network, GitHub's limits: said, and tried again tomorrow
        return _save(error=f"network:{type(e).__name__}", checked_at=datetime.now().isoformat(timespec="minutes"))
    if not rels:
        return _save(latest="", error="", checked_at=datetime.now().isoformat(timespec="minutes"))
    best = max(rels, key=lambda x: _key(x.get("tag_name") or "0"))
    assets = {a.get("name", ""): a.get("browser_download_url", "") for a in best.get("assets") or []}
    return _save(latest=(best.get("tag_name") or "").lstrip("v"), url=best.get("html_url", ""), notes=(best.get("body") or "")[:4000],
                 published=(best.get("published_at") or "")[:10], prerelease=bool(best.get("prerelease")), assets=assets, error="",
                 checked_at=datetime.now().isoformat(timespec="minutes"))


# --- fetch and prepare -----------------------------------------------------------------------------------------------------
def _uv() -> str | None:
    """The uv the installation brought (``<root>/tools``; a release running from data/releases finds it next to the data)."""
    exe = "uv.exe" if os.name == "nt" else "uv"
    for base in (config.ROOT, config.DATA.parent):
        for p in (base / "tools" / exe, base / exe):
            if p.is_file():
                return str(p)
    return shutil.which("uv")


def _download(url: str, target: Path, *, progress: bool = False) -> None:
    import httpx

    if not url.startswith("https://"):
        raise ValueError("only https")
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "autoapply-update"}) as c, c.stream("GET", url) as r:
        r.raise_for_status()
        total, got = int(r.headers.get("content-length") or 0), 0
        with open(target, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                f.write(chunk)
                got += len(chunk)
                if progress and total:
                    pct = int(got * 100 / total)
                    if pct % 5 == 0 and pct != state().get("progress"):
                        _save(progress=pct)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _unpack(zip_path: Path, into: Path) -> None:
    """The package's files under its one top folder, into ``into`` - nothing outside it, whatever the names say."""
    into.mkdir(parents=True)
    root = into.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = info.filename.split("/", 1)[1] if "/" in info.filename else ""
            if not name or info.is_dir():
                continue
            target = (root / name).resolve()
            if root not in target.parents:
                raise ValueError(f"a file outside the folder: {info.filename}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            if info.external_attr >> 16 & 0o111:
                target.chmod(0o755)


def prepare(target: str | None = None) -> dict[str, Any]:
    """Fetch, check and prepare the newest release found (or ``target``). Returns the state. One at a time."""
    if not _busy.acquire(blocking=False):
        return status()
    try:
        s = state()
        ver = target or str(s.get("latest") or "")
        if not ver or _key(ver) <= _key(version()):
            return status()
        if kind() in ("source", "container"):
            _save(status="failed", error="not-here")
            return status()
        assets = s.get("assets") or {}
        pkg, sums = f"AutoApply-{ver}.zip", "SHA256SUMS.txt"
        if pkg not in assets or sums not in assets:
            _save(status="failed", error="no-package")
            return status()
        uv = _uv()
        if not uv:
            _save(status="failed", error="no-uv")
            return status()
        rel = config.DATA / "releases" / ver
        work = config.DATA / "tmp" / f"update-{ver}"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        _save(status="downloading", progress=0, error="")
        _download(assets[sums], work / sums)
        _download(assets[pkg], work / pkg, progress=True)
        want = next((ln.split()[0].lower() for ln in (work / sums).read_text(encoding="utf-8", errors="replace").splitlines()
                     if ln.strip().endswith(pkg)), "")
        if not want or _sha256(work / pkg) != want:
            _save(status="failed", error="checksum")
            return status()
        _save(status="preparing", progress=100)
        if rel.exists():
            shutil.rmtree(rel)
        _unpack(work / pkg, rel)
        if not (rel / "frontend" / "dist" / "index.html").is_file() or not (rel / "uv.lock").is_file():
            shutil.rmtree(rel, ignore_errors=True)
            _save(status="failed", error="incomplete")
            return status()
        env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(rel / ".venv")}
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        subprocess.run([uv, "sync", "--locked", "--no-dev", "--all-extras"], cwd=rel, env=env, check=True, timeout=1800, creationflags=flags,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        py = rel / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(py), "-m", "playwright", "install", "chromium"], cwd=rel, env=env, timeout=1800, creationflags=flags,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(work, ignore_errors=True)
        _save(status="ready", staged=ver, error="")
        _tell("ready", ver)
        return status()
    except Exception as e:  # noqa: BLE001 - said on the about page; the version that runs is untouched
        log.exception("an update could not be prepared")
        _save(status="failed", error=f"{type(e).__name__}")
        return status()
    finally:
        _busy.release()


def prepare_later(target: str | None = None) -> None:
    threading.Thread(target=prepare, args=(target,), name="autoapply-update", daemon=True).start()


# --- switch --------------------------------------------------------------------------------------------------------------
def _previous() -> str:
    """The version run before the last switch, when it is still there to go back to."""
    prev = str(state().get("previous") or "")
    return prev if prev and (config.DATA / "releases" / prev / "frontend" / "dist" / "index.html").is_file() else ""


def idle() -> bool:
    """Nothing being done that a switch would interrupt."""
    from . import tasks
    from .models import Task

    with db.session() as s:
        busy = s.query(Task).filter(Task.status.in_(("running", "queued")), Task.kind.in_(("apply", "execute", "recon", "revise"))).count()
    if busy or getattr(tasks, "KEPT", None):
        return False
    from . import remote

    return not remote.windows()      # (a window open for the applicant: they are in the middle of something)


def in_window(at: datetime | None = None) -> bool:
    w = db.get_setting("update.window") or {"from": "03:00", "to": "05:00"}
    at = at or datetime.now()
    try:
        (fh, fm), (th, tm) = (map(int, str(w.get(k) or "").split(":")) for k in ("from", "to"))
    except (ValueError, TypeError):
        return False
    now_m, a, b = at.hour * 60 + at.minute, fh * 60 + fm, th * 60 + tm
    return a <= now_m < b if a < b else (now_m >= a or now_m < b)


def switch(target: str | None = None) -> dict[str, Any]:
    """Ask the tray to restart into the version prepared (or into ``target``, one kept in data/releases). The tray waits
    for what is in hand to be done; a version that does not start is left and the running one goes on."""
    ver = target or str(state().get("staged") or "")
    if not ver or not (config.DATA / "releases" / ver / "frontend" / "dist" / "index.html").is_file():
        raise ValueError("nothing prepared")
    if kind() != "managed":
        raise ValueError("not-managed")
    run = config.DATA / "run"
    run.mkdir(parents=True, exist_ok=True)
    active = run / "active-release"
    pending = (run / "next-release").with_suffix(".pending")
    pending.write_text(ver, encoding="utf-8")
    pending.replace(run / "next-release")
    hist = list(state().get("history") or []) + [{"from": version(), "to": ver, "at": datetime.now().isoformat(timespec="minutes")}]
    here = config.ROOT.resolve()
    previous = here.name if here.parent == (config.DATA / "releases").resolve() else (active.read_text(encoding="utf-8").strip() if active.is_file() else "")
    _save(switching_to=ver, previous=previous, failed_switch="", history=hist[-20:])
    (run / "restart-request").write_text(ver, encoding="utf-8")
    return status()


def rollback() -> dict[str, Any]:
    prev = _previous()
    if not prev:
        raise ValueError("no-previous")
    return switch(prev)


def after_start() -> None:
    """At every start: a switch asked for has happened - or has not, and the old version goes on. Said either way, once.
    Versions older than the one before are cleared away."""
    s = state()
    if s.get("status") in ("downloading", "preparing") and not _busy.locked():
        _save(status="failed", error="interrupted")      # (the program stopped while it was preparing)
    to = str(s.get("switching_to") or "")
    if to:
        ok = to in (version(), config.ROOT.name)
        _save(switching_to="", status="idle" if ok else "failed", error="" if ok else "did-not-start", staged="" if ok else s.get("staged", ""),
              failed_switch="" if ok else to)
        if not ok:
            (config.DATA / "run" / "next-release").unlink(missing_ok=True)      # (not tried again at the next restart)
        _tell("switched" if ok else "failed", to)
    kept = str(state().get("staged") or "")
    if kept and _key(kept) <= _key(version()) and not state().get("switching_to"):
        # The version that runs is the one prepared - or a later one (it was started another way: the installer, a
        # build of one's own). "Ready: switch to 2.0.2" on a program that is 2.0.2 was this.
        _save(staged="", status="idle" if state().get("status") == "ready" else state().get("status", "idle"), when_idle="")
    rel = config.DATA / "releases"
    keep = {version(), str(state().get("previous") or ""), str(state().get("staged") or "")}
    active = config.DATA / "run" / "active-release"
    if active.is_file():
        keep.add(active.read_text(encoding="utf-8").strip())
    if rel.is_dir() and kind() == "managed":
        for d in rel.iterdir():
            if d.is_dir() and d.name not in keep and re.fullmatch(r"\d+\.\d+\.\d+[\w.-]*", d.name):
                shutil.rmtree(d, ignore_errors=True)


# --- by itself -------------------------------------------------------------------------------------------------------------
def _tell(what: str, ver: str) -> None:
    from . import messages, notify

    try:
        notify.send("status_update", messages.update(what, ver), tag="update", ref=f"update:{ver}:{what}")
    except Exception:  # noqa: BLE001
        log.exception("an update notice could not be sent")


def when_idle(ver: str) -> Any:
    """"Update when idle" (the button on the phone's card): prepare ``ver`` if it is not yet, and switch to it the next
    time nothing is being done - whatever the mode and the window. Returns what is said back."""
    from .say import say

    if kind() != "managed" or _key(ver) <= _key(version()) or ver != str(state().get("latest") or ""):
        raise ValueError("not-here")
    s = _save(when_idle=ver, failed_switch="")
    if s.get("staged") != ver:
        prepare_later(ver)
    return say("server.updates.whenIdle", v=ver)


def tick(at: datetime | None = None) -> str:
    """Every few minutes: look once a day; say what is new once; fetch and prepare when that is the mode; switch when
    it is "auto", idle and inside the window - or when "update when idle" was pressed, and idle. Returns what it did."""
    s = state()
    wanted = str(s.get("when_idle") or "")
    if wanted and wanted == s.get("staged") and s.get("failed_switch") != wanted and kind() == "managed" and idle():
        _save(when_idle="")
        switch(wanted)
        return "switching"
    mode = db.get_setting("update.mode") or "notify"
    if mode not in MODES or mode == "off":
        return ""
    at = at or datetime.now()
    last = str(s.get("checked_at") or "")
    if not last or last < (at - timedelta(hours=20)).isoformat():
        s = check()
    latest = str(s.get("latest") or "")
    if not latest or _key(latest) <= _key(version()):
        return ""
    if s.get("notified") != latest:
        _save(notified=latest)
        _tell("available", latest)
    if mode in ("download", "auto") and kind() not in ("source", "container") and s.get("staged") != latest and s.get("status") not in ("downloading", "preparing"):
        if s.get("status") == "failed" and s.get("failed_for") == latest:
            return ""          # (one try per version by itself: the page has the button for another)
        _save(failed_for=latest)
        prepare_later(latest)
        return "preparing"
    if mode == "auto" and s.get("staged") == latest and s.get("failed_switch") != latest and kind() == "managed" and idle() and in_window(at):
        switch(latest)
        return "switching"
    return ""
