"""Command line: autoapply serve | import-tsv <path> | task <kind> | drain"""

from __future__ import annotations

import argparse
import json
import logging


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(prog="autoapply")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8000)
    i = sub.add_parser("import-tsv")
    i.add_argument("path")
    t = sub.add_parser("task")
    t.add_argument("kind")
    sub.add_parser("drain")
    tr = sub.add_parser("tray", help="start the launcher: a tray icon that runs the server and shows its status")
    tr.add_argument("--port", type=int, default=8000)
    tr.add_argument("--no-open", action="store_true")
    fx = sub.add_parser("fixtures", help="replay saved form pages through the current drivers")
    fx.add_argument("ats", nargs="?")
    sub.add_parser("claude-login", help="sign in with your Claude subscription (opens the browser)")
    ex = sub.add_parser("export", help="write everything you have put into the program into one zip")
    ex.add_argument("--sessions", action="store_true", help="include the saved sign-ins (only usable on this computer)")
    rs = sub.add_parser("restore", help="replace the data with an export (stop the program first)")
    rs.add_argument("path")
    sub.add_parser("shortcut", help="put an AutoApply shortcut on the desktop / in the applications menu")
    a = ap.parse_args()
    if a.cmd == "tray":
        from . import launcher

        return launcher.main(["--port", str(a.port)] + (["--no-open"] if a.no_open else []))
    if a.cmd == "shortcut":
        from . import launcher

        print(launcher.create_shortcut())
        return None
    if a.cmd == "restore":
        import urllib.request

        from . import backup

        try:
            urllib.request.urlopen("http://127.0.0.1:8000/api/overview", timeout=2)  # noqa: S310
            raise SystemExit("AutoApply is running. Quit it first (tray icon -> Quit), then run restore again.")
        except OSError:
            pass
        print(json.dumps(backup.restore(a.path), ensure_ascii=False, indent=1))
        return None
    if a.cmd == "export":
        from . import backup, db as _db

        _db.init_db()
        print(json.dumps(backup.export(sessions=a.sessions), ensure_ascii=False, indent=1))
        return None
    if a.cmd == "claude-login":
        from . import llm_sdk

        raise SystemExit(llm_sdk.login())

    from . import db

    db.init_db()
    from . import persona

    persona.migrate()
    from . import i18n

    i18n.first_run_lang()
    if a.cmd == "serve":
        import uvicorn

        uvicorn.run("autoapply.api.main:app", host="127.0.0.1", port=a.port, log_level="info")
    elif a.cmd == "import-tsv":
        from . import importer

        print(json.dumps(importer.import_tsv(a.path), ensure_ascii=False))
    elif a.cmd == "task":
        from . import handlers, tasks  # noqa: F401

        tasks.enqueue(a.kind, ref="cli", dedupe=False)
        tasks.drain(1)
    elif a.cmd == "fixtures":
        from . import fixtures

        res = fixtures.run_all(a.ats)
        for r in res["results"]:
            print(("ok   " if r["ok"] else "FAIL ") + f"{r['ats']}/{r['fixture']}" + ("" if r["ok"] else f"  {r.get('error') or r.get('missing') or r.get('changed')}"))
        print(f"{res['fixtures']} fixture(s), {res['failed']} failed")
        raise SystemExit(1 if res["failed"] else 0)
    elif a.cmd == "drain":
        from . import handlers, tasks  # noqa: F401

        print(tasks.drain())


if __name__ == "__main__":
    main()
