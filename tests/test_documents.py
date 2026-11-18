"""A file written for a posting - a cover letter, a tailored résumé - is written once (materials.version_dir)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from autoapply import db


def _pdf(path: Path, title: str, pages: int = 1) -> Path:
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    w.add_metadata({"/Title": title})
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        w.write(f)
    return path


def _title(path) -> str:
    from pypdf import PdfReader

    return str(PdfReader(str(path)).metadata.title)


def _job():
    from autoapply.models import Job

    with db.session() as s:
        j = Job(source="greenhouse", source_id="1", title="Software Intern", company="Acme", tenant="acme", status="scored", jd_text="Build services. " * 30)
        s.add(j)
        s.flush()
        s.expunge(j)
        return j


@pytest.fixture
def letters(app_env, monkeypatch):
    """The writing and the checking are the model's; Word is not there: a letter is what it was asked to say."""
    from autoapply import convert, materials

    said = {"n": 0, "fail": False}

    def write(job, *, feedback="", previous=None):
        said["n"] += 1
        return {"recipient": "Hiring Team\nAcme", "re_line": "Re: Software Intern", "salutation": "Dear Hiring Team:", "paragraphs": [f"letter {said['n']}: {feedback or 'first'}", "b", "c", "d"]}

    def to_pdf(docx, **kw):
        if said["fail"]:
            raise RuntimeError("Word stopped answering")
        from docx import Document as Docx

        text = "\n".join(p.text for p in Docx(str(docx)).paragraphs)
        return _pdf(Path(docx).with_suffix(".pdf"), next(ln for ln in text.splitlines() if ln.startswith("letter ")))

    monkeypatch.setattr(materials, "write_letter", write)
    monkeypatch.setattr(materials, "check_letter", lambda job, letter: [])
    monkeypatch.setattr(materials, "_template", lambda: None)
    monkeypatch.setattr(convert, "docx_to_pdf", to_pdf)
    return said


def test_a_rewritten_letter_leaves_the_letter_before_it_as_it_was(letters):
    """Every writing went to the same path: a draft approved with the first letter opened the second.

    (F-09: a row per letter, one file for all of them.)"""
    from autoapply import config, materials
    from autoapply.api.main import app
    from autoapply.models import Document

    job = _job()
    c = TestClient(app)
    one = materials.make_cover_letter(job)
    was = Path(one["path"]).read_bytes()
    assert _title(one["path"]) == "letter 1: first"
    two = materials.make_cover_letter(job, instructions="shorter")
    # the same name - it is what the employer sees - in a folder of its own
    assert Path(two["path"]).name == Path(one["path"]).name == "Acme_Software_Intern.pdf" and two["path"] != one["path"]
    assert "cover_letter_v1" in one["path"] and "cover_letter_v2" in two["path"]
    # the first letter is what it was: on disk, for the draft that names it, and as a Word file
    assert Path(one["path"]).read_bytes() == was and _title(two["path"]) == "letter 2: shorter"
    assert c.get(f"/api/documents/{one['id']}/file").content == was
    with db.session() as s:
        rows = {d.id: d for d in s.query(Document)}
        assert (rows[one["id"]].active, rows[two["id"]].active) == (0, 1)
        assert Path(rows[one["id"]].meta["docx"]).exists() and rows[one["id"]].meta["docx"] != rows[two["id"]].meta["docx"]
    assert materials.existing_cover_letter(job.id)["id"] == two["id"]
    listed = {d["id"]: d for d in c.get("/api/documents").json()}
    assert (listed[one["id"]]["version"], listed[two["id"]]["version"]) == (1, 2) and not listed[one["id"]]["overwritten"]

    # a writing that fails half-way: the letter in use is still the second, untouched, and nothing is left of the third
    letters["fail"] = True
    now = Path(two["path"]).read_bytes()
    with pytest.raises(RuntimeError, match="Word stopped answering"):
        materials.make_cover_letter(job, instructions="once more")
    letters["fail"] = False
    assert Path(two["path"]).read_bytes() == now and materials.existing_cover_letter(job.id)["id"] == two["id"]
    with db.session() as s:
        assert s.query(Document).count() == 2
    assert sorted(p.name for p in (config.MATERIALS / f"job_{job.id}").iterdir()) == ["cover_letter_v1", "cover_letter_v2"]

    # "use this version" on the first: it is the one in use, the second is not - and the next draft carries it
    assert c.patch(f"/api/documents/{one['id']}", json={"active": True}).status_code == 200
    with db.session() as s:
        assert {d.id: d.active for d in s.query(Document)} == {one["id"]: 1, two["id"]: 0}
    assert materials.existing_cover_letter(job.id)["id"] == one["id"]
    # the draft that was made with the second letter still names it: it is not among the files to tidy away
    from autoapply.models import Application, Draft

    with db.session() as s:
        a = Application(job_id=job.id, status="draft_ready")
        s.add(a)
        s.flush()
        s.add(Draft(application_id=a.id, version=1, schema={}, answers=[], unresolved=[], materials=[{"slot": "cl", "document_id": one["id"], "kind": "cover_letter"}], review_status="superseded"))
        s.add(Draft(application_id=a.id, version=2, schema={}, answers=[], unresolved=[], materials=[{"slot": "cl", "document_id": two["id"], "kind": "cover_letter"}], review_status="pending"))
    listed = {d["id"]: d for d in c.get("/api/documents").json()}
    assert (listed[one["id"]]["in_draft"], listed[two["id"]]["in_draft"]) == (False, True) and not listed[two["id"]]["active"]
    # removing a version removes its own file and no other
    assert c.delete(f"/api/documents/{two['id']}?permanent=true").status_code == 200
    assert not Path(two["path"]).exists() and Path(one["path"]).read_bytes() == was
    # the next one is written beside them, not over the folder the removed one had
    three = materials.make_cover_letter(job, instructions="again")
    assert three["path"] not in (one["path"], two["path"]) and Path(one["path"]).read_bytes() == was


def test_the_letters_from_before_each_writing_kept_its_own_file_are_said_to_be_overwritten(letters):
    """What is there when the program is updated: several records, one file. The file is the last letter's; the
    earlier records - and the drafts that name them - say that what opens is not what it was."""
    from autoapply import config, drafts, materials
    from autoapply.api.main import app
    from autoapply.models import Document

    job = _job()
    old = _pdf(config.MATERIALS / f"job_{job.id}" / "Acme_Software_Intern" / "Acme_Software_Intern.pdf", "the letter written last")
    with db.session() as s:
        for n in (1, 2):
            s.add(Document(kind="cover_letter", name=old.name, path=str(old), job_id=job.id, active=int(n == 2), meta={"letter": {"paragraphs": [f"letter {n}"]}, "problems": []}))
        s.add(Document(kind="resume_site", name="CV.pdf", path=str(_pdf(config.FILES / "CV.pdf", "cv")), active=1, meta={}))
    with db.session() as s:
        first, second, cv = (d.id for d in s.query(Document).order_by(Document.id))
    assert materials.mark_overwritten() == 1 and materials.mark_overwritten() == 0          # once
    c = TestClient(app)
    listed = {d["id"]: d for d in c.get("/api/documents").json()}
    assert [listed[i]["overwritten"] for i in (first, second, cv)] == [True, False, False]
    assert [listed[i]["version"] for i in (first, second, cv)] == [1, 2, None]
    mats = [{"slot": "cv", "document_id": cv, "name": "CV.pdf", "kind": "resume_site"}, {"slot": "cl", "document_id": first, "name": old.name, "kind": "cover_letter"},
            {"slot": "cl2", "document_id": second, "name": old.name, "kind": "cover_letter"}]
    assert [m.get("overwritten", False) for m in drafts._files_as_they_are(mats)] == [False, True, False]
    # removing the earlier record does not take the file the later one still has
    assert c.delete(f"/api/documents/{first}?permanent=true").status_code == 200 and old.exists()
    # the file that is there counts as the writings before: the next one goes beside it, and it stays as it is
    new = materials.make_cover_letter(job, instructions="rewrite")
    assert _title(old) == "the letter written last" and Path(new["path"]) != old and Path(new["path"]).exists()
    assert materials.existing_cover_letter(job.id)["id"] == new["id"]


def test_a_tailored_resume_that_fails_its_checks_does_not_take_the_place_of_the_one_in_use(app_env, monkeypatch):
    """The same for the résumé written for a posting - and one that does not pass is a record, not the résumé in use.
    (It was made the one in use and written over the one before; a draft could then be given a résumé of three pages.)"""
    from autoapply import config, tailor
    from autoapply.models import Document

    job = _job()
    base = config.FILES / "CV.docx"
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_bytes(b"docx")
    how = {"pages": 1, "changes": [{"type": "rewrite", "where": "Acme", "before": "a", "after": "b"}], "n": 0}

    def render(doc, docx):
        how["n"] += 1
        docx.parent.mkdir(parents=True, exist_ok=True)
        docx.write_bytes(b"docx %d" % how["n"])
        return {"docx": str(docx), "pdf": str(_pdf(docx.with_suffix(".pdf"), f"resume {how['n']}", how["pages"])), "pages": how["pages"]}

    monkeypatch.setattr(tailor, "settings", lambda: {"target_pages": 1, "mode": "light", "min_bullets": 2})
    monkeypatch.setattr(tailor, "base_doc", lambda: {"id": 1, "name": "CV.docx", "path": str(base), "meta": {"pages": 1}})
    monkeypatch.setattr(tailor, "parse", lambda path: {"doc": object(), "sections": [{"locked": False, "entries": [{"title": "Acme", "bullets": [{"id": i, "text": "t", "el": None} for i in range(3)]}]}]})
    monkeypatch.setattr(tailor, "plan", lambda job, st, cfg, instructions="": {"focus": "backend", "keywords": [], "least_relevant": []})
    monkeypatch.setattr(tailor, "apply", lambda st, p, cfg: list(how["changes"]))
    monkeypatch.setattr(tailor, "render", render)

    one = tailor.make(job)
    was = Path(one["path"]).read_bytes()
    assert one["current"] and tailor.existing(job.id)["id"] == one["id"] and "tailored_resume_v1" in one["path"]
    # the applicant asks for another, and it comes out at three pages
    how["pages"] = 3
    two = tailor.make(job, instructions="more detail")
    assert not two["current"] and two["tailor"]["problems"] and two["path"] != one["path"] and Path(two["path"]).name == Path(one["path"]).name
    assert tailor.existing(job.id)["id"] == one["id"] and Path(one["path"]).read_bytes() == was and _title(one["path"]) == "resume 1"
    with db.session() as s:
        assert {d.id: d.active for d in s.query(Document)} == {one["id"]: 1, two["id"]: 0}
    # what the program writes by itself and changes nothing: kept, not used; the same asked for by the applicant is theirs to see
    how["pages"], how["changes"] = 1, []
    three = tailor.make(job, instructions="x", automatic=True)
    assert three["tailor"]["unchanged"] and not three["current"] and tailor.existing(job.id)["id"] == one["id"]
    four = tailor.make(job, instructions="x")
    assert four["current"] and tailor.existing(job.id)["id"] == four["id"] and Path(one["path"]).read_bytes() == was
    # a rendering that fails: the one in use stays, and the folder of the failed writing is gone
    monkeypatch.setattr(tailor, "render", lambda doc, docx: (_ for _ in ()).throw(RuntimeError("Word stopped answering")))
    with pytest.raises(RuntimeError):
        tailor.make(job, instructions="y")
    assert tailor.existing(job.id)["id"] == four["id"]
    assert sorted(p.name for p in (config.MATERIALS / f"job_{job.id}").iterdir()) == [f"tailored_resume_v{n}" for n in (1, 2, 3, 4)]
