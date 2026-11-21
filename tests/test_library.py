"""The material library: what a file is for, whose it is, where it went - and a file that went out is kept."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from autoapply import config, db


def _file(name: str) -> str:
    p = config.FILES / "x" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"%PDF-1.4 test")
    return str(p)


def test_where_a_file_went_and_what_can_be_put_away(app_env):
    from autoapply import materials
    from autoapply.api.main import bulk_documents, list_documents
    from autoapply.models import Application, Document, Draft, Job, Outgoing

    resume, letter, old_letter, spare = _file("resume.pdf"), _file("letter.pdf"), _file("old.pdf"), _file("spare.pdf")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with db.session() as s:
        a_job = Job(source="manual", source_id="a", company="Acme", title="Analyst", apply_url="https://x/1", jd_text="x" * 300, status="queued", online=1)
        b_job = Job(source="manual", source_id="b", company="Globex", title="Intern", apply_url="https://x/2", jd_text="x" * 300, status="queued", online=1)
        s.add_all([a_job, b_job])
        s.flush()
        a = Application(job_id=a_job.id, status="submitted", submitted_at=now - timedelta(days=3))
        b = Application(job_id=b_job.id, status="rejected", submitted_at=now - timedelta(days=60))
        s.add_all([a, b])
        s.flush()
        s.add_all([Document(kind="resume_site", name="resume.pdf", path=resume), Document(kind="cover_letter", name="letter.pdf", path=letter, job_id=a_job.id),
                   Document(kind="cover_letter", name="old.pdf", path=old_letter, job_id=b_job.id), Document(kind="other", name="spare.pdf", path=spare)])
        s.add(Draft(application_id=a.id, version=1, review_status="closed", schema={}, answers=[], materials=[{"label": "Résumé", "path": resume}, {"label": "Cover letter", "path": letter}]))
        s.add(Outgoing(application_id=b.id, status="sent", subject="Application: Intern", attachments=[{"name": "resume.pdf", "path": resume}, {"name": "old.pdf", "path": old_letter}]))
    rows = {d["name"]: d for d in list_documents()}
    r = rows["resume.pdf"]
    assert r["purpose"] == "mine" and r["sent"] and {(w["company"], w["how"]) for w in r["went"]} == {("Acme", "record"), ("Globex", "mail")}
    assert rows["letter.pdf"]["purpose"] == "for_job" and rows["letter.pdf"]["application"]["label"] and not rows["letter.pdf"]["application"]["ended"]
    assert rows["old.pdf"]["application"]["ended"] and rows["old.pdf"]["cleanable"]          # rejected: over
    assert not rows["letter.pdf"]["cleanable"] and not rows["resume.pdf"]["cleanable"]
    assert rows["spare.pdf"]["went"] == [] and not rows["spare.pdf"]["sent"]
    # delete: what went out is archived instead (it is what was sent), the rest goes
    got = bulk_documents({"action": "delete", "ids": [rows["old.pdf"]["id"], rows["spare.pdf"]["id"]]})
    assert got == {"done": 2, "archived_instead": 1}
    rows = {d["name"]: d for d in list_documents()}
    assert "spare.pdf" not in rows and rows["old.pdf"]["archived"] and not rows["old.pdf"]["cleanable"]
    # a file the agent put together is in the library, saying what it holds
    made = _file("all-in-one.pdf")
    did = materials.register_made(__import__("pathlib").Path(made), "all-in-one.pdf", None, ["resume.pdf (all 1 page(s))", "letter.pdf (all 1 page(s))"])
    assert materials.register_made(__import__("pathlib").Path(made), "all-in-one.pdf", None, ["resume.pdf"]) == did          # once
    row = next(d for d in list_documents() if d["id"] == did)
    assert row["purpose"] == "made" and row["made_from"] == ["resume.pdf"]
