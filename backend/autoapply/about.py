"""What the about page says about this copy of the program: its version and how it runs, where its data is."""
from __future__ import annotations

from typing import Any

from . import config, db


def info() -> dict[str, Any]:
    import platform
    import subprocess as _sp
    from importlib import metadata

    from . import backup, updates

    commit = ""
    if (config.ROOT / ".git").exists():
        try:
            commit = _sp.run(["git", "rev-parse", "--short", "HEAD"], cwd=config.ROOT, capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:  # noqa: BLE001
            commit = ""
    wanted = ("fastapi", "uvicorn", "sqlalchemy", "pydantic", "httpx", "playwright", "anthropic", "claude-agent-sdk", "pypdf", "python-docx", "keyring",
              "apscheduler", "cryptography", "pillow", "pystray", "websockets", "google-api-python-client", "nodriver", "openai-codex")
    parts = []
    for name in wanted:
        try:
            m = metadata.metadata(name)
            parts.append({"name": name, "version": metadata.version(name), "license": (m.get("License-Expression") or m.get("License") or "")[:60]})
        except metadata.PackageNotFoundError:
            continue
    ver = backup.version()
    # (what changed in it is the changelog's: /api/about/changelog, from the release data)
    build = updates.running()      # (the folder of data/releases it runs from: "" for an installation's own folder or a checkout)
    return {"version": ver, "commit": commit, "kind": updates.kind(), "python": platform.python_version(), "system": platform.platform(terse=True),
            "data": str(config.DATA), "repo": str(db.get_setting("update.repo") or ""), "components": parts,
            "build": build, "build_release": updates.release(build)}


