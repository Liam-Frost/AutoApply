"""Profile initialisation from uploaded material (résumé, transcript, old cover
letters, free-text notes). Produces a draft profile.md for the user to confirm."""

from __future__ import annotations

from pathlib import Path

from . import db, knowledge, llm
from . import prompts
from .materials import _doc_text
from .models import Document

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
    with db.session() as s:
        return s.query(Document).filter(Document.active == 1, Document.kind.in_(
            ("resume_site", "resume_portal", "transcript", "cl_example", "source"))).order_by(Document.id).all()


def draft_profile(notes: str = "") -> str:
    """Return a proposed profile.md. Does not save it."""
    docs = documents_for_init()
    if not docs and not notes.strip():
        raise ValueError("Upload at least a résumé (or write some notes) first.")
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
        raise ValueError(f"{Path(path).name} has no extractable text (a scanned PDF?). Upload a text PDF or a .docx.")
    return text[:60000]


def _strip_fence(md: str) -> str:
    md = md.strip()
    if md.startswith("```"):
        md = md.split("\n", 1)[1] if "\n" in md else ""
        md = md.rsplit("```", 1)[0]
    return md.strip()
