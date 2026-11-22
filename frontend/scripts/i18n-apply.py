"""Add, change or remove messages in every catalog at once, from one patch file - so that a key always arrives with its
English, its translations and its note, and so that several people (or agents) working at the same time do not write
over each other (the catalogs are read and written under a lock).

    python frontend/scripts/i18n-apply.py patch.json

patch.json (UTF-8):
{
  "set":    { "applications.col.schedule": { "en": "Next event", "zh": "关联日程", "fr": "Prochain événement", "note": "Column header: ..." } },
  "remove": [ "applications.sub" ],
  "server": { "set": { "server.accounts.sessionSaved": { "en": "...", "zh": "...", "fr": "...", "note": "..." } }, "remove": [] }
}
A key that exists keeps the languages the patch does not give (so a wording can be changed in one language); a new key
needs en, zh, fr and note. Interface keys are nested by their dots; server keys are flat. Then run `npm run i18n:status`.
"""
import json
import os
import sys
import time
from pathlib import Path

L = Path(__file__).resolve().parents[1] / "src" / "locales"
LANGS = ("en", "zh", "fr")


def leaf(d, path, create=False):
    *head, last = path.split(".")
    for p in head:
        if p not in d:
            if not create:
                return None, last
            d[p] = {}
        d = d[p]
        if not isinstance(d, dict):
            raise SystemExit(f"{path}: {p} is a message, not a group")
    return d, last


def prune(d, path):
    """Remove a key and the groups it leaves empty."""
    parts = path.split(".")
    chain = [d]
    for p in parts[:-1]:
        d = d.get(p) if isinstance(d, dict) else None
        if d is None:
            return
        chain.append(d)
    chain[-1].pop(parts[-1], None)
    for i in range(len(chain) - 1, 0, -1):
        if not chain[i]:
            chain[i - 1].pop(parts[i - 1], None)


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def write(p, d, indent):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8", newline="\n")


def apply(patch):
    ui = {l: read(L / f"{l}.json") for l in LANGS}
    notes = read(L / "notes.json")
    for key, v in (patch.get("set") or {}).items():
        d, last = leaf(ui["en"], key)
        new = d is None or last not in d
        if new and not all(v.get(k) for k in (*LANGS, "note")):
            raise SystemExit(f"{key}: a new key needs en, zh, fr and note")
        for l in LANGS:
            if l in v:
                d, last = leaf(ui[l], key, create=True)
                d[last] = v[l]
        if "note" in v:
            notes[key] = v["note"]
    for key in patch.get("remove") or []:
        for l in LANGS:
            prune(ui[l], key)
        notes.pop(key, None)
    for l in LANGS:
        write(L / f"{l}.json", ui[l], 2)
    write(L / "notes.json", notes, 2)

    sp = patch.get("server") or {}
    if sp.get("set") or sp.get("remove"):
        S = L / "server"
        srv = {l: read(S / f"{l}.json") for l in LANGS}
        snotes = read(S / "notes.json")
        for key, v in (sp.get("set") or {}).items():
            if key not in srv["en"] and not all(v.get(k) for k in (*LANGS, "note")):
                raise SystemExit(f"{key}: a new key needs en, zh, fr and note")
            for l in LANGS:
                if l in v:
                    srv[l][key] = v[l]
            if "note" in v:
                snotes[key] = v["note"]
        for key in sp.get("remove") or []:
            for l in LANGS:
                srv[l].pop(key, None)
            snotes.pop(key, None)
        for l in LANGS:
            write(S / f"{l}.json", dict(sorted(srv[l].items())), 1)
        write(S / "notes.json", dict(sorted(snotes.items())), 1)


def main():
    patch = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    lock = L / ".lock"
    for _ in range(600):
        try:
            os.mkdir(lock)
            break
        except FileExistsError:
            if time.time() - lock.stat().st_mtime > 60:      # (left behind by a run that died)
                try:
                    os.rmdir(lock)
                except OSError:
                    pass
            time.sleep(0.1)
    else:
        raise SystemExit("the catalogs are locked")
    try:
        apply(patch)
    finally:
        os.rmdir(lock)
    n = len(patch.get("set") or {}) + len((patch.get("server") or {}).get("set") or {})
    print(f"applied: {n} set, {len(patch.get('remove') or []) + len((patch.get('server') or {}).get('remove') or [])} removed")


if __name__ == "__main__":
    main()
