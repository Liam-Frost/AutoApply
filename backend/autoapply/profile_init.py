"""The profile, written from uploaded material (résumé, transcript, old cover letters, free-text notes).

It is a task in the queue (``start``), not a request a page waits for: reading a résumé takes a minute or more, and
the applicant goes on - to the next step of the first-run guide, to another page. What it wrote is kept with the
task (``state``): saved as the profile when there was none, kept as a proposal to look at when there is one.

An empty profile is also something other work waits for (``wanted``): a posting cannot be scored for nobody, a form
cannot be answered from nothing. That work goes on by itself once something is in the profile (``arrived``)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import db, knowledge, llm
from . import prompts
from .materials import _doc_text
from .models import Document, Task

KIND = "profile_init"
REF = "profile"                 # one profile, one task at a time
CARD = "config:profile"         # the card that says the profile is empty - and what a task that needs it waits for
RESUMES = ("resume_site", "resume_docx", "resume_portal", "source")       # an upload of these starts the writing when there is no profile
NOTE = "从上传资料初始化"

SYSTEM = """You set up an applicant profile used to fill job application forms.
Write Markdown with exactly these level-2 sections, in this order:
Identity & contact / Education / Work authorization / Availability / Standard answers / Experience / Rules / Materials / Agent-added

- Copy facts exactly from the documents (names, dates, numbers, URLs). Do not invent or infer facts that are not there.
- Experience: one entry per job and per project, each with the bullets from the résumé (keep the metrics).
- Where forms commonly need something the documents do not state (legal name vs preferred name, phone country code,
  work authorization, sponsorship, citizenship, graduation date for forms, GPA, salary expectations, demographics),
  add a bullet "- TODO: <question>" in the right section so the applicant can fill it in. Never guess these.
- Rules: leave conditional rules to the applicant; add only "- TODO" prompts for name handling and consent handling.
- Materials: list the uploaded files by kind.
- Agent-added: leave empty.

When a <current_profile> is given, you are UPDATING it, not rewriting it:
- Keep every existing line (facts, rules, dated notes, standard answers) word for word unless a document adds to it.
- Add facts that are new in the documents to the right section.
- If a document disagrees with the current profile (a date, a number, a title, a name), keep the profile's value
  where it is - the applicant confirmed it - and list the disagreement under a final section
  "## Conflicts to review" as "- <field>: profile says <A>; <document name> says <B>". Never silently replace.
- Remove a "- TODO" bullet only if a document now answers it.
Output only the Markdown."""


def documents_for_init() -> list[Document]:
    """What the profile is written from. A file that is there twice - the Word résumé the first-run guide files both
    as the résumé to tailor and as source material - is read once. Twice means the same bytes: two files of one name
    and one length in two categories can be two documents."""
    import hashlib

    with db.session() as s:
        rows = s.query(Document).filter(Document.active == 1, Document.kind.in_(
            ("resume_site", "resume_docx", "resume_portal", "transcript", "cl_example", "source"))).order_by(Document.id).all()
        s.expunge_all()
    out, seen = [], set()
    for d in rows:
        p = Path(d.path)
        if not p.exists():
            continue
        same = hashlib.sha256(p.read_bytes()).hexdigest()
        if same not in seen:
            seen.add(same)
            out.append(d)
    return out


NOTHING_TO_READ = "请先上传一份简历，或者写几句补充说明。"


def in_flight() -> int | None:
    """The task that is queued or being worked on, if there is one."""
    with db.session() as s:
        t = s.query(Task).filter(Task.kind == KIND, Task.status.in_(("queued", "running"))).order_by(Task.id.desc()).first()
        return t.id if t else None


def start(notes: str = "") -> int:
    """Queue the writing of the profile from what is uploaded. Asked for again while it is queued or being written,
    it is that one: two of them would read the same files and write over each other."""
    if not documents_for_init() and not notes.strip():
        raise ValueError(NOTHING_TO_READ)
    from . import tasks

    with db.session() as s:
        running = s.query(Task).filter_by(kind=KIND, status="running").order_by(Task.id.desc()).first()
        if running is not None:
            return running.id
    return tasks.enqueue(KIND, ref=REF, payload={"notes": notes}, priority=5)


def on_upload(kind: str) -> int | None:
    """A résumé has been uploaded and nothing is known about the applicant yet: the profile is written from it at once,
    without being asked for - wherever the upload was made. Once there is a profile, a new résumé changes nothing by
    itself: "generate from résumé" proposes, and the applicant decides."""
    if kind not in RESUMES or not knowledge.blank():
        return None
    try:
        return start()
    except ValueError:
        return None


def run(notes: str = "") -> dict[str, Any]:
    """Write the profile (the task's work). With no profile there is nothing to compare it with and nothing to lose:
    it is saved, and everything that waited for a profile goes on. With one, what was written is a proposal - kept in
    the task's result until the applicant has adopted or discarded it."""
    md = draft_profile(notes)
    if knowledge.blank(md):
        raise ValueError("AI 没有从这些资料里整理出内容。可以换一份文件，或者在“个人资料”页自己填写。")
    todos = len(re.findall(r"TODO:", md))
    if knowledge.blank():
        knowledge.write("profile", md, source="init", note=NOTE)
        return {"applied": True, "todos": todos}
    return {"applied": False, "todos": todos, "draft": md}


def _card() -> None:
    from . import notify

    body = "给岗位评分、回答申请表都要用到个人资料，现在里面还没有内容，所以这两件事先等着。上传一份简历，程序会自动整理出个人资料；也可以在“个人资料”页自己填写。资料有了之后，等着的事会自动继续，不需要再操作。"
    notify.add_todo("config", "个人资料还是空的", ref=CARD, body=body)


def wanted() -> str:
    """Something that needs the profile found it empty. Said once - one card, whatever met it and however often - and
    not at all while the profile is being written (it is on its way; if that fails, the card is made then).
    Returns what to wait for."""
    if in_flight() is None:
        _card()
    return CARD


def failed() -> None:
    """The writing did not work. If there is still no profile, say so where the applicant sees what is waiting."""
    if knowledge.blank():
        _card()


def arrived() -> None:
    """There is something in the profile now (knowledge.write, whoever wrote it): what waited for it goes on
    (``go_on``). An application whose record was written while there was no profile is worked again: its open
    questions were asked of nothing."""
    from . import tasks
    from .models import Draft

    go_on()
    with db.session() as s:
        open_ = sorted({d.application.job_id for d in s.query(Draft).filter(Draft.review_status == "pending")
                        if any(a.get("source") == "unresolved" for a in (d.answers or []))})
    for job_id in open_:
        tasks.enqueue("apply", ref=f"job:{job_id}", payload={"job_id": job_id}, priority=10)


def go_on() -> None:
    """The card is closed, the drafts that waited for a profile go back in the queue, and scoring is queued - whether
    or not anything counts as unscored: a posting that came as a short summary is not counted until its page has been
    read, and reading it is the scoring task's first step."""
    from . import handlers, notify, tasks

    notify.close_todos("config", CARD)
    handlers.resume_waiting(CARD)
    tasks.enqueue("score", ref="unscored", priority=150)


def began_to_wait(status: str, waits_for: str, result: dict[str, Any]) -> None:
    """A task has just been recorded as waiting for the profile (tasks._run_one, after the record is saved). If the
    profile arrived while the task was finding it empty, the arrival looked for waiting tasks before this one was
    among them - and it comes once. So it is looked at again here: with a profile there, what waits goes on."""
    waits = (status == "waiting_human" and waits_for == CARD) or bool((result or {}).get("waits_for_profile"))
    if waits and not knowledge.blank():
        go_on()


def state() -> dict[str, Any]:
    """Where the writing of the profile stands, for whichever page shows it - whenever it is opened: the task that is
    queued or being worked on, or else the last one and what came of it (saved as the profile; a proposal that waits
    to be looked at, with its text; or why it did not work)."""
    from . import humanize

    with db.session() as s:
        t = s.query(Task).filter(Task.kind == KIND, Task.status != "cancelled").order_by(Task.id.desc()).first()
        task = None
        if t is not None:
            r = t.result or {}
            why = humanize.explain(re.sub(r"^[A-Za-z_.]+(Error|Exception|Unavailable|Refused): ", "", t.error or ""))
            task = {"id": t.id, "status": t.status, "error": why["message"], "detail": why["detail"],
                    "applied": bool(r.get("applied")), "todos": int(r.get("todos") or 0), "settled": str(r.get("settled") or ""),
                    "draft": str(r.get("draft") or "") if t.status == "done" and not r.get("settled") else "",
                    "notes": str((t.payload or {}).get("notes") or ""),
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "started_at": t.started_at.isoformat() if t.started_at else None,
                    "finished_at": t.finished_at.isoformat() if t.finished_at else None}
    profile = knowledge.read("profile")
    return {"task": task, "blank": knowledge.blank(profile), "todos": len(re.findall(r"TODO:", profile)),
            "documents": [{"id": d.id, "kind": d.kind, "name": d.name} for d in documents_for_init()]}


def settle(task_id: int, how: str, markdown: str | None = None) -> dict[str, Any]:
    """The applicant has looked at a proposal: ``adopt`` saves it as the profile (as they edited it, when they did),
    ``discard`` drops it. Either way it is not shown again."""
    if how not in ("adopt", "discard"):
        raise KeyError(how)
    with db.session() as s:
        t = s.get(Task, task_id)
        if t is None or t.kind != KIND:
            raise KeyError(task_id)
        r = dict(t.result or {})
        if t.status != "done" or r.get("settled") or not r.get("draft"):
            raise ValueError("这份草稿已经处理过了。")
        md = (markdown if markdown is not None and markdown.strip() else r["draft"]) if how == "adopt" else ""
        r.pop("draft")
        t.result = {**r, "settled": "adopted" if how == "adopt" else "discarded"}
    if how == "adopt":
        return {"version": knowledge.write("profile", md, source="init", note=NOTE)}
    return {"version": None}


def draft_profile(notes: str = "") -> str:
    """Return a proposed profile.md. Does not save it."""
    docs = documents_for_init()
    if not docs and not notes.strip():
        raise ValueError(NOTHING_TO_READ)
    content: list = []
    listing = []
    for d in docs:
        p = Path(d.path)
        listing.append(f"- {d.kind}: {d.name}")
        if p.suffix.lower() == ".pdf":
            content.append(llm.pdf_block(p))  # the model reads the PDF itself (layout, tables)
            content.append({"type": "text", "text": f"(above: {d.kind} — {d.name})"})
        else:
            content.append({"type": "text", "text": f"<document kind=\"{d.kind}\" name=\"{d.name}\">\n{_doc_text(d.path)}\n</document>"})
    existing = knowledge.read("profile")
    has_existing = "TODO" not in existing and len(existing) > 400
    content.append({"type": "text", "text": (
        f"Uploaded files:\n" + "\n".join(listing) + "\n\n"
        + (f"<applicant_notes>\n{notes}\n</applicant_notes>\n\n" if notes.strip() else "")
        + (f"<current_profile>\n{existing}\n</current_profile>\nUpdate the current profile with anything new in the documents; keep every existing rule and dated note.\n" if has_existing else "")
        + "Write the profile."
    )})
    if llm.backend() != "api_key":
        # Only the Anthropic API reads PDFs natively; every other backend gets the extracted text.
        parts = []
        for c in content:
            if c["type"] == "text":
                parts.append(c["text"])
        for d in docs:
            if Path(d.path).suffix.lower() == ".pdf":
                parts.insert(0, f"<document kind=\"{d.kind}\" name=\"{d.name}\">\n{_pdf_text(d.path)}\n</document>")
        return _strip_fence(llm.text("\n\n".join(parts), system=prompts.get("profile_init")))
    resp = llm._create(small=False, max_tokens=16000, system=prompts.get("profile_init"), messages=[{"role": "user", "content": content}])
    return _strip_fence(llm._text_of(resp))


def _pdf_text(path: str) -> str:
    from pypdf import PdfReader

    text = "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages).strip()
    if not text:
        raise ValueError(f"「{Path(path).name}」里读不出文字（可能是扫描件）。请上传文字版的 PDF 或 Word 文件。")
    return text[:60000]


def _strip_fence(md: str) -> str:
    md = md.strip()
    if md.startswith("```"):
        md = md.split("\n", 1)[1] if "\n" in md else ""
        md = md.rsplit("```", 1)[0]
    return md.strip()
