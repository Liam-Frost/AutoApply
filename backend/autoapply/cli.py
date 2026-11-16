"""Command line: autoapply serve | doctor | service ... | import-tsv <path> | task <kind> | drain"""

from __future__ import annotations

import argparse
import json
import logging


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    # These libraries log every request with its full address, and a Telegram bot's address contains its token: a
    # secret would be written to the log with every notification. Their warnings and errors are still logged.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(prog="autoapply")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=None, help="default: the port in the access settings (8000)")
    s.add_argument("--host", default=None, help="default: the address in the access settings (127.0.0.1)")
    sub.add_parser("reset-admin", help="forget the administrator's password: the next visit from this computer sets a new one")
    sa = sub.add_parser("set-admin", help="set the administrator's name and password here, in the terminal (a server or a container: "
                                          "there is no browser on the computer itself to do the first set-up in)")
    sa.add_argument("--user", help="the name; asked for when not given")
    sa.add_argument("--password-stdin", action="store_true", help="read the password from standard input instead of asking (a secret piped in by a deployment tool)")
    i = sub.add_parser("import-tsv")
    i.add_argument("path")
    t = sub.add_parser("task")
    t.add_argument("kind")
    sub.add_parser("drain")
    tr = sub.add_parser("tray", help="start the launcher: a tray icon that runs the server and shows its status")
    tr.add_argument("--port", type=int, default=None)
    tr.add_argument("--no-open", action="store_true")
    fx = sub.add_parser("fixtures", help="replay saved form pages through the current drivers")
    fx.add_argument("ats", nargs="?")
    sub.add_parser("claude-login", help="sign in with your Claude subscription (opens the browser)")
    ex = sub.add_parser("export", help="write everything you have put into the program into one zip")
    ex.add_argument("--sessions", action="store_true", help="include the saved sign-ins (only usable on this computer)")
    rs = sub.add_parser("restore", help="replace the data with an export (stop the program first)")
    rs.add_argument("path")
    sub.add_parser("shortcut", help="put an AutoApply shortcut on the desktop / in the applications menu")
    dr = sub.add_parser("doctor", help="what this computer has and lacks for the program to do its whole job")
    dr.add_argument("--deep", action="store_true", help="also start the browser once")
    dr.add_argument("--json", action="store_true", help="the findings as JSON, for a script")
    sv = sub.add_parser("service", help="Linux: run as a service that starts with the computer")
    sv.add_argument("action", choices=["install", "uninstall", "status", "start", "stop", "restart"])
    sv.add_argument("--now", action="store_true", help="stop: do not wait for the task that is running")
    a = ap.parse_args()
    if a.cmd == "tray":
        from . import launcher

        return launcher.main((["--port", str(a.port)] if a.port else []) + (["--no-open"] if a.no_open else []))
    if a.cmd == "set-admin":
        import getpass
        import sys

        from . import access

        user = (a.user or input("Administrator name: ")).strip()
        if a.password_stdin:
            password = sys.stdin.readline().rstrip("\r\n")
        else:
            password = getpass.getpass("Password (at least 8 characters): ")
            if getpass.getpass("Once more: ") != password:
                raise SystemExit("The two passwords are not the same. Nothing was changed.")
        problem = "the name is empty" if not user else access.password_problem(password)
        if problem:
            from . import i18n

            raise SystemExit(f"{i18n.tr(problem, 'en')}. Nothing was changed.")
        access.set_admin(user, password)
        access.end_all_sessions()
        print(f"The administrator is {user}. Every earlier login was ended.")
        return None
    if a.cmd == "reset-admin":
        from . import access

        access.reset_admin()
        print("The administrator account was removed and every login ended. Open AutoApply on this computer to set a new one.")
        return None
    if a.cmd == "doctor":
        from . import db as _db, doctor, i18n

        _db.init_db()
        marks = {"ok": "[ok]  ", "info": "[--]  ", "warn": "[!]   ", "bad": "[FAIL]"}
        found = doctor.run(deep=a.deep)
        if a.json:
            print(json.dumps(found, ensure_ascii=False, indent=1))
            raise SystemExit(1 if any(f["level"] == "bad" for f in found) else 0)
        for f in found:
            print(f"{marks[f['level']]} {i18n.tr(f['title'])}")
            if f["detail"]:
                print(f"         {i18n.tr(f['detail'])}")
            if f["fix"]:
                print(f"         -> {f['fix']}")
        raise SystemExit(1 if any(f["level"] == "bad" for f in found) else 0)
    if a.cmd == "service":
        from . import service

        try:
            if a.action == "install":
                st = service.install()
                print("AutoApply runs as a service now: it starts with the computer and is restarted when it fails.")
                if not st["linger"]:
                    print(f"It will stop when you log out. To keep it running:  sudo loginctl enable-linger {st['user']}")
            elif a.action == "uninstall":
                service.uninstall()
                print("The service was removed. The program and your data are untouched.")
            elif a.action == "status":
                print(json.dumps(service.status(), indent=1))
            elif a.action == "start":
                service.start()
            elif a.action == "stop":
                raise SystemExit(0 if service.stop(now=a.now) else 3)
            elif a.action == "restart":
                service.stop(now=a.now)
                service.start()
        except service.NotHere as e:
            raise SystemExit(str(e)) from e
        return None
    if a.cmd == "shortcut":
        from . import launcher

        print(launcher.create_shortcut())
        return None
    if a.cmd == "restore":
        import urllib.request

        from . import backup

        try:
            from . import access as _access

            # the one address that answers without a login; any answer at all means the program is running
            urllib.request.urlopen(f"http://127.0.0.1:{_access.conf()['port']}/api/auth/state", timeout=2)  # noqa: S310
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

        import os

        from . import access

        from . import runstate

        runstate.mark("server")         # the installers look for this before they touch the program's files
        c = access.conf()
        host, port = a.host or c["host"], a.port or c["port"]
        os.environ["AUTOAPPLY_LISTENING_HOST"], os.environ["AUTOAPPLY_LISTENING_PORT"] = host, str(port)
        if access.exposed({"host": host}) and not access.has_admin():
            logging.getLogger("autoapply").warning("listening on %s, and no administrator is set yet: open the page on this computer first to set one", host)
        # proxy_headers off: who is calling is worked out by access.caller, from the proxies named in the settings
        uvicorn.run("autoapply.api.main:app", host=host, port=port, log_level="info", proxy_headers=False)
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
