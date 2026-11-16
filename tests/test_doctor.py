"""The doctor: what the computer lacks, said before it is needed; and the Linux service."""

from __future__ import annotations

import sys

import keyring
from keyring.backends.fail import Keyring as NoKeyring

from autoapply import doctor, secrets, service


def by_id(found):
    return {f["id"]: f for f in found}


def test_a_desktop_with_everything_reports_nothing_bad(app_env, monkeypatch):
    monkeypatch.setattr(doctor, "_browser", lambda deep: doctor._finding("browser", "ok", "x"))
    found = doctor.run()
    assert by_id(found)["secrets"]["level"] == "ok"
    assert not [f for f in found if f["level"] == "bad"]
    assert all(set(f) == {"id", "level", "title", "detail", "fix"} for f in found)


def test_a_server_is_told_what_it_lacks_and_how_to_get_it(app_env, monkeypatch):
    keyring.set_keyring(NoKeyring())
    secrets.reset()
    monkeypatch.setattr(sys, "platform", "linux")
    for name in ("DISPLAY", "WAYLAND_DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor, "_browser", lambda deep: doctor._finding("browser", "ok", "x"))
    monkeypatch.setattr("autoapply.convert._soffice", lambda: None)
    monkeypatch.setattr(service, "available", lambda: False)
    found = by_id(doctor.run())
    assert found["secrets"]["level"] == "warn" and "AUTOAPPLY_MASTER_KEY_FILE" in found["secrets"]["fix"]
    assert found["screen"]["level"] == "warn" and "xvfb" in found["screen"]["fix"]
    assert found["converter"]["level"] == "warn" and "libreoffice" in found["converter"]["fix"]
    assert found["service"]["level"] == "info"
    secrets.reset()


def test_a_check_that_breaks_does_not_hide_the_others(app_env, monkeypatch):
    def broken(deep):
        raise RuntimeError("boom")

    monkeypatch.setattr(doctor, "_browser", broken)
    found = doctor.run()
    assert any("boom" in f["detail"] for f in found) and by_id(found)["secrets"]["level"] == "ok"


def test_the_doctor_is_served_in_the_interface_language(app_env):
    from fastapi.testclient import TestClient

    from autoapply.api.main import app

    r = TestClient(app).get("/api/doctor")
    assert r.status_code == 200 and {f["id"] for f in r.json()} >= {"secrets", "browser", "disk"}


def test_the_service_runs_the_program_from_where_it_is_installed(app_env):
    from autoapply import config

    text = service.unit_text()
    assert f"WorkingDirectory={config.ROOT}" in text and "-m autoapply.cli serve" in text and sys.executable in text
    assert f"EnvironmentFile=-{config.DATA / 'service.env'}" in text and "Restart=on-failure" in text


def test_stopping_the_service_waits_for_the_running_task_and_leaves_the_pause_as_it_was(app_env, monkeypatch):
    from autoapply import db
    from autoapply.models import Task

    db.init_db()
    with db.session() as s:
        s.add(Task(kind="execute", ref="1", status="running"))
    calls, told = [], []
    monkeypatch.setattr(service, "status", lambda: {"active": True})
    monkeypatch.setattr(service, "_ctl", lambda *a, **k: calls.append(a))

    def finish():
        with db.session() as s:
            for t in s.query(Task):
                t.status = "done"

    import threading

    threading.Timer(1.5, finish).start()
    assert service.stop(tell=told.append) is True
    assert calls == [("stop", "autoapply")] and db.get_setting("schedule.paused") is False
    # --now does not wait, and does not touch the pause
    calls.clear()
    service.stop(now=True)
    assert calls == [("stop", "autoapply")]
