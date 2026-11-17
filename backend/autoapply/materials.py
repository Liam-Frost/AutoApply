"""Application materials: cover-letter generation, verification, rendering, PDF merge.

Generation is unconstrained on purpose: the model gets the whole résumé, the
whole job description, example letters the user approved, and the layout it
must fit. Constraints are enforced AFTER writing (one page, every fact traceable
to the résumé, correct names) and failures are fed back for a rewrite.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from . import config, db, knowledge, llm
from . import prompts
from .models import Document, Job

SCRIPTS = config.ROOT / "scripts"
MAX_REWRITES = 2

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


def existing_cover_letter(job_id: int) -> dict[str, Any] | None:
    """The active letter already written for this job, if its file is still there."""
    with db.session() as s:
        d = s.query(Document).filter_by(kind="cover_letter", job_id=job_id, active=1).order_by(Document.id.desc()).first()
        if d is None or not Path(d.path).exists():
            return None
        return {"id": d.id, "name": d.name, "path": d.path, "kind": d.kind, "problems": (d.meta or {}).get("problems", []), "letter": (d.meta or {}).get("letter")}


def make_cover_letter(job: Job, *, instructions: str = "") -> dict[str, Any]:
    """Write -> check -> render -> (rewrite on failure). Stores a Document and returns its dict."""
    out_dir = config.MATERIALS / f"job_{job.id}"
    base = re.sub(r"[^A-Za-z0-9]+", "_", f"{job.company}_{_public_id(job) or job.title}").strip("_")[:60]
    letter = write_letter(job, feedback=instructions)
    problems: list[str] = []
    rendered: dict[str, Any] = {}
    for attempt in range(MAX_REWRITES + 1):
        problems = check_letter(job, letter)
        rendered = render_letter(letter, out_dir, base)
        if rendered["pages"] != 1:
            words = sum(len(p.split()) for p in letter["paragraphs"])
            problems.append(f"renders to {rendered['pages']} pages at {words} words; must be exactly one page - shorten")
        if not problems or attempt == MAX_REWRITES:
            break
        letter = write_letter(job, feedback="\n".join(problems), previous=letter)
    with db.session() as s:
        for old in s.query(Document).filter_by(kind="cover_letter", job_id=job.id, active=1):
            old.active = 0
        d = Document(kind="cover_letter", name=Path(rendered["pdf"]).name, path=rendered["pdf"], job_id=job.id,
                     meta={"letter": letter, "docx": rendered["docx"], "pages": rendered["pages"], "problems": problems})
        s.add(d)
        s.flush()
        return {"id": d.id, "name": d.name, "path": d.path, "kind": d.kind, "problems": problems, "letter": letter}


# --- PDF utilities -----------------------------------------------------------------------
