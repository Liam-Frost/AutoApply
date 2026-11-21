"""Application materials: cover-letter generation, verification, rendering, PDF merge.

Generation is unconstrained on purpose: the model gets the whole résumé, the
whole job description, example letters the user approved, and the layout it
must fit. Constraints are enforced AFTER writing (one page, every fact traceable
to the résumé, correct names) and failures are fed back for a rewrite.
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Iterator

from pypdf import PdfReader

from . import config, db, knowledge, llm
from . import prompts
from .models import Document, Job

SCRIPTS = config.ROOT / "scripts"
MAX_REWRITES = 2
GENERATED = ("cover_letter", "tailored_resume")      # written by the program, for one posting


# --- a file written for a posting is written once ---------------------------------------------
#
# A draft is approved with the letter it shows, and an application is sent with it. The record of that letter - the
# Document row the draft names - has to stay that letter. Every writing went to the same path (job_12/Acme_123/
# Acme_123.pdf): the rows of the earlier letters, and the drafts that named them, opened whatever had been written
# last, and a writing that failed half-way left them with half a file. So: each writing gets a folder of its own, a
# row is added only when the file is there, and nothing writes to a folder that has a row.


@contextlib.contextmanager
def version_dir(job_id: int, kind: str) -> Iterator[Path]:
    """A new folder for one writing of a ``kind`` of file for a posting: ``job_12/cover_letter_v3``.

    The file keeps the name it is sent to the employer under (Acme_123.pdf); what differs is the folder. A writing
    that fails takes its folder with it - nothing names it."""
    root = config.MATERIALS / f"job_{job_id}"
    with db.session() as s:
        n = s.query(Document).filter_by(kind=kind, job_id=job_id).count() + 1      # what was there before is the versions before
    while (root / f"{kind}_v{n}").exists():
        n += 1
    out = root / f"{kind}_v{n}"
    out.mkdir(parents=True)
    try:
        yield out
    except BaseException:
        shutil.rmtree(out, ignore_errors=True)
        raise


def publish(kind: str, job_id: int, pdf: str, meta: dict[str, Any], *, current: bool = True) -> int:
    """Record a file that was written for a posting. ``current``: it is the one the next draft uses, in place of the
    one before - decided here, in the same step as the record, and only for a file that is there to be read."""
    path = Path(pdf)
    if not path.is_file() or not path.stat().st_size:
        raise RuntimeError(f"the file was not written: {path.name}")
    with db.session() as s:
        if current:
            for old in s.query(Document).filter_by(kind=kind, job_id=job_id, active=1):
                old.active = 0
        d = Document(kind=kind, name=path.name, path=str(path), job_id=job_id, active=int(current), meta=meta)
        s.add(d)
        s.flush()
        return d.id


def use_version(doc_id: int) -> None:
    """The applicant picks an earlier writing: it is the one in use, and the others of its kind for that posting are not."""
    with db.session() as s:
        d = s.get(Document, doc_id)
        if d is None or d.kind not in GENERATED or not d.job_id:
            return
        for other in s.query(Document).filter(Document.kind == d.kind, Document.job_id == d.job_id, Document.active == 1, Document.id != d.id):
            other.active = 0
        d.active = 1


def versions() -> dict[int, int]:
    """Which writing each of these files is, counted per posting and kind: {document id: 1, 2, 3...} - for the files
    that have been written more than once (a single letter is not "version 1" of anything)."""
    nth: dict[int, int] = {}
    of: dict[int, tuple[str, int]] = {}
    seen: dict[tuple[str, int], int] = {}
    with db.session() as s:
        for i, kind, job_id in s.query(Document.id, Document.kind, Document.job_id).filter(Document.kind.in_(GENERATED), Document.job_id.isnot(None)).order_by(Document.id):
            of[i] = (kind, job_id)
            seen[of[i]] = nth[i] = seen.get(of[i], 0) + 1
    return {i: n for i, n in nth.items() if seen[of[i]] > 1}


def held_by_drafts() -> set[int]:
    """The files the latest draft of each application names: what would be sent, or was. A version that is no longer
    the one in use can still be one of these (the applicant went back to an earlier letter after a draft was made)."""
    from .models import Draft

    latest: dict[int, list[dict[str, Any]]] = {}
    with db.session() as s:
        for app_id, _, mats in s.query(Draft.application_id, Draft.version, Draft.materials).order_by(Draft.application_id, Draft.version):
            latest[app_id] = mats or []
    return {int(m["document_id"]) for mats in latest.values() for m in mats if m.get("document_id")}


GENERATED = ("cover_letter", "tailored_resume", "made")      # written or put together for one posting
ENDED = ("rejected", "withdrawn")
STALE_DAYS = 30        # an application sent this long ago, with nothing heard, is over as far as its files are concerned


def _key(path: str) -> str:
    return str(Path(path)).lower()


def whereabouts() -> tuple[dict[int, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    """Where the files went: the applications whose records name them (by the file's record or its path) - with the
    form field they were for, and whether the application went out - and the mails sent with them. By document id and
    by path."""
    from collections import defaultdict

    from .models import SENT, Application, Draft, Outgoing

    by_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[Any, ...]] = set()
    with db.session() as s:
        apps = {a.id: a for a in s.query(Application)}
        for d in s.query(Draft).order_by(Draft.id.desc()):
            a = apps.get(d.application_id)
            if a is None:
                continue
            for m in d.materials or []:
                doc, path = m.get("document_id"), str(m.get("path") or "")
                key = (a.id, doc, _key(path) if path else "")
                if key in seen or not (doc or path):
                    continue
                seen.add(key)
                row = {"application_id": a.id, "company": a.job.company, "title": a.job.title, "status": a.status, "how": "record",
                       "field": str(m.get("label") or m.get("slot") or "")[:120], "sent": a.status in SENT or a.submitted_at is not None}
                (by_id[int(doc)] if doc else by_path[_key(path)]).append(row)
        for o in s.query(Outgoing).filter(Outgoing.status == "sent"):
            a = apps.get(o.application_id) if o.application_id else None
            for att in o.attachments or []:
                if att.get("path"):
                    by_path[_key(att["path"])].append({"application_id": a.id if a else None, "company": a.job.company if a else "", "title": a.job.title if a else "",
                                                       "status": a.status if a else "", "how": "mail", "field": o.subject[:120], "sent": True})
    return by_id, by_path


def ended(a: Any) -> bool:
    """Is the application a file was made for over (as far as the file is concerned)?"""
    from datetime import datetime, timedelta, timezone

    if a is None:
        return False
    if a.status in ENDED or a.job.archived_at is not None or not a.job.online:
        return True
    sent = a.submitted_at
    return sent is not None and a.status in ("submitted", "confirmed") and sent < datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=STALE_DAYS)


def register_made(path: Path, name: str, job_id: int | None, made_from: list[str]) -> int:
    """A file the agent put together from the applicant's own (make_file) - in the library, saying what it holds."""
    with db.session() as s:
        d = s.query(Document).filter(Document.path == str(path)).first()
        if d is None:
            d = Document(kind="made", name=name, path=str(path), job_id=job_id, meta={})
            s.add(d)
        d.meta = {**(d.meta or {}), "made_from": list(made_from)[:20]}
        d.active = 1
        s.flush()
        return d.id


def mark_overwritten() -> int:
    """The records from before each writing had a folder of its own: those of one posting share one file, and it holds
    what was written last. The earlier ones are marked - "overwritten_by": the record whose content the file has -
    so that the library and the drafts that name them can say that what opens is not what was approved then."""
    n = 0
    with db.session() as s:
        by_path: dict[str, list[Document]] = {}
        for d in s.query(Document).filter(Document.kind.in_(GENERATED)).order_by(Document.id):
            by_path.setdefault(d.path, []).append(d)
        for rows in by_path.values():
            for d in rows[:-1]:
                if (d.meta or {}).get("overwritten_by") != rows[-1].id:
                    d.meta = {**(d.meta or {}), "overwritten_by": rows[-1].id}
                    n += 1
    return n


def overwritten(ids: list[int]) -> set[int]:
    """Which of these records no longer have the file they were made with (see mark_overwritten)."""
    ids = [int(i) for i in ids if i]
    if not ids:
        return set()
    with db.session() as s:
        return {d.id for d in s.query(Document).filter(Document.id.in_(ids)) if (d.meta or {}).get("overwritten_by")}

LETTER_SCHEMA = llm.obj(
    {
        "recipient": {"type": "string", "description": "2-3 lines separated by \\n: team/person, company (and division), city"},
        "re_line": {"type": "string", "description": "'Re: <exact job title>, Job ID <id>' when a Job ID is given, otherwise 'Re: <exact job title>'"},
        "salutation": {"type": "string"},
        "paragraphs": {"type": "array", "items": {"type": "string"}, "description": "body paragraphs, normally 4"},
    }
)

CHECK_SCHEMA = llm.obj(
    {
        "unsupported_claims": {"type": "array", "items": {"type": "string"}, "description": "statements about the applicant not supported by the résumé/profile"},
        "wrong_names": {"type": "array", "items": {"type": "string"}, "description": "company / title / job id errors"},
        "missed_requirements": {"type": "array", "items": {"type": "string"}, "description": "explicit cover-letter instructions in the posting that the letter ignores"},
    }
)

WRITE_SYSTEM = """You write one-page cover letters for a job applicant.
Write the way the applicant's own approved letters read (examples are provided): specific, plain, confident.
Open with something tied to this company and this role; use the applicant's strongest matching work as evidence;
close with availability and, if the examples have one, the contact line they use.
Every statement about the applicant must come from the résumé or the profile. Do not invent metrics, tools, or experience.
Honour any explicit instructions in the posting about what the letter must contain.
Body length: 300-370 words so it fits one page in the applicant's template."""


def _doc_text(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        try:
            return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
        except Exception:  # noqa: BLE001
            return ""
    if p.suffix.lower() == ".docx":
        import docx

        return "\n".join(par.text for par in docx.Document(str(p)).paragraphs)
    return p.read_text(encoding="utf-8", errors="ignore")


def _docs(kind: str, active_only: bool = True) -> list[Document]:
    with db.session() as s:
        q = s.query(Document).filter_by(kind=kind)
        if active_only:
            q = q.filter_by(active=1)
        return q.order_by(Document.id.desc()).all()


def resume_text(job: Job) -> str:
    kinds = ["resume_portal", "resume_site"] if job.channel == "PD Portal" else ["resume_site", "resume_portal"]
    for k in kinds:
        d = _docs(k)
        if d:
            return _doc_text(d[0].path)
    return ""


def needs_cover_letter(job: Job, schema_labels: list[tuple[str, bool]]) -> bool:
    """Write a letter only when the posting or the form requires one."""
    if re.search(r"cover letter", job.docs_required or "", re.I):
        return True
    if any(req and "cover" in label.lower() for label, req in schema_labels):
        return True
    return bool(re.search(r"(include|submit|attach|provide)[^.]{0,60}cover letter", job.jd_text or "", re.I))


def _public_id(job: Job) -> str:
    """A job number a recruiter would recognise (PD Portal ids, requisition numbers) - not a URL or an internal UUID."""
    sid = str(job.source_id or "").split(":")[-1]
    return sid if job.source in ("pdportal", "workday") and re.fullmatch(r"[A-Za-z]{0,4}[-_]?\d{3,10}", sid) else ""


def _job_id_line(job: Job) -> str:
    pid = _public_id(job)
    return f"Job ID: {pid}\n" if pid else ""


CHECK_RULES = """Check the letter against the résumé and profile. List every claim about the applicant that is not supported,
every wrong company/title/job-id, and every explicit cover-letter instruction in the posting that the letter ignores.
Rounding a number the résumé gives (e.g. '50+' -> 'over 50') is supported.
Contact details and standard closing lines that also appear in previous_letters (the applicant's own earlier letters) are supported;
claims about experience are not supported by previous_letters alone."""


def write_letter(job: Job, *, feedback: str = "", previous: dict[str, Any] | None = None) -> dict[str, Any]:
    examples = "\n\n---\n\n".join(_doc_text(d.path)[:4000] for d in _docs("cl_example")[:2])
    prompt = (
        f"<resume>\n{resume_text(job)}\n</resume>\n\n<profile>\n{knowledge.read('profile')}\n</profile>\n\n"
        f"<approved_example_letters>\n{examples or '(none uploaded)'}\n</approved_example_letters>\n\n"
        f"<job>\nCompany: {job.company}\nTitle: {job.title}\n{_job_id_line(job)}Term: {job.term} ({job.months} months)\n"
        f"Location: {job.location or job.work_type}\n\n{job.jd_text or job.summary}\n</job>\n"
    )
    if previous:
        prompt += f"\n<previous_draft>\n{json.dumps(previous, ensure_ascii=False)}\n</previous_draft>\n<problems_to_fix>\n{feedback}\n</problems_to_fix>\n"
    elif feedback:
        prompt += f"\n<instructions_from_applicant>\n{feedback}\n</instructions_from_applicant>\n"
    return llm.json(prompt, LETTER_SCHEMA, system=prompts.get("letter_write"))


def _examples_text() -> str:
    return "\n\n---\n\n".join(_doc_text(d.path)[:4000] for d in _docs("cl_example")[:2])


def reference_names() -> list[str]:
    return [f"{d.kind}: {d.name}" for k in ("cl_template", "cl_example") for d in _docs(k)]


def check_letter(job: Job, letter: dict[str, Any]) -> list[str]:
    """Independent fact/name check. Returns a list of problems (empty = pass)."""
    body = "\n\n".join(letter["paragraphs"])
    prompt = (
        f"<resume>\n{resume_text(job)}\n</resume>\n<profile>\n{knowledge.read('profile')}\n</profile>\n"
        f"<job>\nCompany: {job.company}\nTitle: {job.title}\n{_job_id_line(job)}{(job.jd_text or job.summary)}\n</job>\n"
        f"<previous_letters>\n{_examples_text()}\n</previous_letters>\n"
        f"<letter>\n{letter['recipient']}\n{letter['re_line']}\n{letter['salutation']}\n\n{body}\n</letter>\n\n"
    )
    r = llm.json(prompt, CHECK_SCHEMA, system=prompts.get("letter_check"))
    return (
        [f"unsupported: {c}" for c in r["unsupported_claims"]]
        + [f"wrong name: {c}" for c in r["wrong_names"]]
        + [f"missed requirement: {c}" for c in r["missed_requirements"]]
    )


# --- rendering (Word template via COM; same approach the user's letters already use) ---


def _fits_layout(path: Path) -> bool:
    """The Word script fills a fixed paragraph layout (name, title, contact, date, recipient, Re:, salutation,
    four body paragraphs, 'Sincerely,', name). An earlier letter in that layout works as a template."""
    if path.suffix.lower() != ".docx":
        return False
    try:
        from docx import Document as Docx

        ps = [p.text.strip() for p in Docx(str(path)).paragraphs]
    except Exception:  # noqa: BLE001
        return False
    return len(ps) >= 21 and ps[19].lower().startswith("sincerely") and ps[7].lower().startswith("re")


def _template() -> Path | None:
    """The uploaded template; failing that, an uploaded example letter that has the same layout."""
    for kind in ("cl_template", "cl_example"):
        for d in _docs(kind):
            if _fits_layout(Path(d.path)):
                return Path(d.path)
    d = _docs("cl_template")
    return Path(d[0].path) if d and Path(d[0].path).suffix.lower() == ".docx" else None


def _sender() -> tuple[str, str]:
    """Name and contact line for the built-in layout, from the résumé's first lines."""
    docs = _docs("resume_site") or _docs("resume_portal")
    lines = [ln.strip() for ln in (_doc_text(docs[0].path) if docs else "").splitlines() if ln.strip()][:8]
    name = re.split(r"\s*[(|]", lines[0])[0].strip() if lines else ""
    contact = next((ln for ln in lines[1:] if "@" in ln), "")
    return name, contact


def _render_builtin(letter: dict[str, Any], docx: Path, today: str) -> None:
    """Plain one-page business letter, used when there is neither a template nor a usable example."""
    from docx import Document as Docx
    from docx.shared import Pt

    name, contact = _sender()
    doc = Docx()
    for sec in doc.sections:
        sec.left_margin = sec.right_margin = sec.top_margin = sec.bottom_margin = Pt(64)
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10.5)
    st.paragraph_format.space_after = Pt(8)

    def para(text: str, *, bold: bool = False, size: float | None = None, after: float | None = None):  # noqa: ANN202
        p = doc.add_paragraph()
        for i, line in enumerate(text.split("\n")):
            r = p.add_run(line)
            r.bold = bold
            if size:
                r.font.size = Pt(size)
            if i < text.count("\n"):
                r.add_break()
        if after is not None:
            p.paragraph_format.space_after = Pt(after)
        return p

    if name:
        para(name, bold=True, size=16, after=2)
    if contact:
        para(contact, after=14)
    para(today, after=10)
    para(letter["recipient"], after=10)
    para(letter["re_line"], bold=True)
    para(letter["salutation"])
    for p in letter["paragraphs"]:
        if p.strip():
            para(p.strip())
    para("Sincerely,", after=2)
    para(name)
    docx.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(docx))


def render_letter(letter: dict[str, Any], out_dir: Path, basename: str) -> dict[str, Any]:
    """Fill the user's Word template and export a PDF. Returns {docx, pdf, pages}."""
    tpl = _template()
    paras = list(letter["paragraphs"])
    while len(paras) < 4:
        paras.append("")
    if len(paras) > 4:  # the template has four body slots
        paras = paras[:3] + [" ".join(paras[3:])]
    spec = [{
        "id": basename, "folder": basename, "file": basename,
        "recipient": letter["recipient"].replace("\n", "\u000b"),
        "re": letter["re_line"], "salutation": letter["salutation"],
        "p1": paras[0], "p2": paras[1], "p3": paras[2], "p4": paras[3],
        # conventions of the applicant's own template (Settings): names set in bold, links to restore, fixed text to correct
        "bold": list(db.get_setting("cover_letter.bold_terms") or []), "links": list(db.get_setting("cover_letter.links") or []),
        "replace": list(db.get_setting("cover_letter.replace") or []),
    }]
    out_dir.mkdir(parents=True, exist_ok=True)
    spec_path = out_dir / f"{basename}.letters.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    docx = out_dir / basename / f"{basename}.docx"
    docx.unlink(missing_ok=True)
    today = date.today().strftime("%B %d, %Y").replace(" 0", " ")
    ps = lambda *a: subprocess.run(  # noqa: E731
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", *a], capture_output=True, text=True, timeout=180
    )
    from . import convert

    if tpl is None or not convert.available()["word"]:  # filling the user's own template needs Word; without it the built-in layout is used
        _render_builtin(letter, docx, today)
    else:
        r = ps(str(SCRIPTS / "gen_cover_letters.ps1"), "-Letters", str(spec_path), "-OutBase", str(out_dir), "-Date", today, "-Template", str(tpl))
        if not docx.exists():
            raise RuntimeError(f"Word could not generate the letter: {(r.stderr or r.stdout)[-400:]}")
    from . import convert

    pdf = convert.docx_to_pdf(docx)
    return {"docx": str(docx), "pdf": str(pdf), "pages": len(PdfReader(str(pdf)).pages)}


def letter_request_key(job: Job, instructions: str) -> str:
    import hashlib

    inputs = [job.id, job.company, job.title, job.term, job.months, job.location, job.work_type,
              job.jd_text or job.summary, resume_text(job), knowledge.read("profile"), instructions.strip(),
              [(d.id, d.path) for kind in ("cl_template", "cl_example") for d in _docs(kind)],
              [db.get_setting("cover_letter." + key) for key in ("links", "bold_terms", "replace")]]
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def existing_cover_letter(job_id: int) -> dict[str, Any] | None:
    """The active letter already written for this job, if its file is still there."""
    with db.session() as s:
        d = s.query(Document).filter_by(kind="cover_letter", job_id=job_id, active=1).order_by(Document.id.desc()).first()
        if d is None or not Path(d.path).exists():
            return None
        return {"id": d.id, "name": d.name, "path": d.path, "kind": d.kind, "request_key": (d.meta or {}).get("request_key"), "problems": (d.meta or {}).get("problems", []), "letter": (d.meta or {}).get("letter")}


def make_cover_letter(job: Job, *, instructions: str = "", request_key: str = "") -> dict[str, Any]:
    """Write -> check -> render -> (rewrite on failure). Stores a Document and returns its dict.

    The letter is rendered in a folder of its own (version_dir) and becomes the one in use once it is there as a PDF;
    until then, and if anything fails on the way, the letter before it is untouched and still the one in use. What
    the checks still object to after the rewrites is kept with it and shown: a letter the applicant asked for is the
    one the next draft carries, objections and all - whether to send it is theirs to decide."""
    base = re.sub(r"[^A-Za-z0-9]+", "_", f"{job.company}_{_public_id(job) or job.title}").strip("_")[:60]
    letter = write_letter(job, feedback=instructions)
    problems: list[str] = []
    rendered: dict[str, Any] = {}
    with version_dir(job.id, "cover_letter") as out_dir:
        for attempt in range(MAX_REWRITES + 1):
            problems = check_letter(job, letter)
            rendered = render_letter(letter, out_dir, base)
            if rendered["pages"] != 1:
                words = sum(len(p.split()) for p in letter["paragraphs"])
                problems.append(f"renders to {rendered['pages']} pages at {words} words; must be exactly one page - shorten")
            if not problems or attempt == MAX_REWRITES:
                break
            letter = write_letter(job, feedback="\n".join(problems), previous=letter)
        doc_id = publish("cover_letter", job.id, rendered["pdf"], {"letter": letter, "request_key": request_key, "docx": rendered["docx"], "pages": rendered["pages"], "problems": problems})
    return {"id": doc_id, "name": Path(rendered["pdf"]).name, "path": rendered["pdf"], "kind": "cover_letter", "problems": problems, "letter": letter}


# --- PDF utilities -----------------------------------------------------------------------
