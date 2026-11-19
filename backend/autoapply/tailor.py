"""Per-job résumé tailoring.

The user's own Word résumé is the only source. The model proposes a plan (which bullets lead, which
projects come first, the order of skills, optionally a tighter wording); this module decides what
is allowed, applies it to a copy of the Word file so the layout stays the user's, and checks the
page count. Nothing can appear in a tailored résumé that is not in the original:

* ``select`` mode only reorders and (if allowed) leaves bullets out - no text changes at all;
* ``rephrase`` mode may reword a bullet, and every reworded bullet is checked in code: no number
  and no tool / product name that the original résumé does not contain. A rewording that fails is
  dropped and the original bullet is kept.
"""

from __future__ import annotations

import copy
import re
import subprocess
from pathlib import Path
from typing import Any

from . import config, db, llm
from .models import Document, Job

SCRIPTS = config.ROOT / "scripts"
BASE_KIND, OUT_KIND = "resume_docx", "tailored_resume"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
CHRONO = re.compile(r"experience|employment|work|education|经历|经验|教育", re.I)  # sections kept in date order unless the user says otherwise
SKILLS = re.compile(r"skill|技能|technolog", re.I)

PLAN_SCHEMA = llm.obj(
    {
        "focus": {"type": "string", "description": "一句中文：这份简历针对这个岗位突出了什么"},
        "keywords": {"type": "array", "items": {"type": "string"}, "description": "requirements of the posting that the résumé already supports (short phrases)"},
        "skills": {"type": "array", "items": llm.obj({"id": {"type": "string"}, "items": {"type": "array", "items": {"type": "string"}}}),
                   "description": "skill lines to reorder: the same items, most relevant first"},
        "entry_order": {"type": "array", "items": llm.obj({"section": {"type": "string"}, "entries": {"type": "array", "items": {"type": "string"}}}),
                        "description": "sections whose entries should be reordered: all entry ids of that section, most relevant first"},
        "bullets": {"type": "array", "items": llm.obj({"entry": {"type": "string"}, "keep": {"type": "array", "items": {"type": "string"}}}),
                    "description": "for each entry: bullet ids in the order they should appear"},
        "rewrites": {"type": "array", "items": llm.obj({"id": {"type": "string"}, "text": {"type": "string"}}),
                     "description": "reworded bullets (only when rewording is allowed); **bold** marks emphasis"},
        "least_relevant": {"type": "array", "items": {"type": "string"}, "description": "bullet ids from least relevant to this posting upwards; used when the page is too long"},
    }
)

SYSTEM = """You tailor an applicant's résumé to one job posting. You never add a fact: you choose what leads, and -
where the rules of the request allow rewording - how a bullet is worded. Put the bullets, projects and skills that match
the posting's requirements first. The applicant's facts, numbers and tools stay exactly what they are; the words around
them may change only when rewording is allowed. Use the ids given in the résumé outline."""


def settings() -> dict[str, Any]:
    st = db.all_settings()
    return {k[7:]: v for k, v in st.items() if k.startswith("tailor.")}


def base_doc() -> dict[str, Any] | None:
    with db.session() as s:
        d = s.query(Document).filter_by(kind=BASE_KIND, active=1).order_by(Document.id.desc()).first()
        if d is None or not Path(d.path).exists() or not d.path.lower().endswith(".docx"):
            return None
        return {"id": d.id, "name": d.name, "path": d.path, "meta": dict(d.meta or {})}


# --- reading the Word file ---------------------------------------------------------------------


def _text(el) -> str:  # noqa: ANN001
    return "".join((n.text or "") if n.tag == f"{W}t" else "  " for n in el.iter(f"{W}t", f"{W}tab"))


def _runs(el) -> list:  # noqa: ANN001
    return [r for r in el.iter(f"{W}r")]


def _bold(r) -> bool:  # noqa: ANN001
    b = r.find(f"{W}rPr/{W}b")
    return b is not None and b.get(f"{W}val") not in ("0", "false")


def _md(el) -> str:  # noqa: ANN001
    """Paragraph text with bold runs as **bold**."""
    out, cur = [], None
    for r in _runs(el):
        t = "".join(x.text or "" for x in r.iter(f"{W}t"))
        if not t:
            continue
        b = _bold(r)
        if cur is not None and cur[0] == b:
            cur[1] += t
        else:
            cur = [b, t]
            out.append(cur)
    return "".join(f"**{t.strip()}**" + (" " if t.endswith(" ") else "") if b and t.strip() else t for b, t in out)


def _split_items(s: str) -> list[str]:
    items, depth, cur = [], 0, ""
    for ch in s:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth <= 0:
            items.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return [i for i in [*items, cur.strip()] if i]


def _style_is_list(doc, el) -> bool:  # noqa: ANN001
    """Bullets are often defined on the paragraph style (Word's "List Bullet") rather than on the paragraph."""
    sid = el.find(f"{W}pPr/{W}pStyle")
    if sid is None:
        return False
    try:
        style = next(x for x in doc.styles if x.style_id == sid.get(f"{W}val"))
    except StopIteration:
        return False
    for _ in range(6):
        if style is None:
            return False
        if style.element.find(f"{W}pPr/{W}numPr") is not None:
            return True
        style = style.base_style
    return False


def parse(path: str) -> dict[str, Any]:
    """The résumé as sections -> entries -> bullets, with ids the plan refers to (p<N> = N-th body element)."""
    from docx import Document as Docx

    doc = Docx(path)
    body = doc.element.body
    sections: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    entry: dict[str, Any] | None = None
    for i, el in enumerate(list(body)):
        if not el.tag.endswith("}p"):
            entry = None
            continue
        txt = _text(el).strip()
        is_list = el.find(f"{W}pPr/{W}numPr") is not None or _style_is_list(doc, el)
        locked = el.find(f"{W}pPr/{W}sectPr") is not None  # carries a layout break: must stay where it is
        letters = re.sub(r"[^A-Za-z一-鿿]", "", txt)
        heading = bool(txt) and not is_list and len(txt) <= 40 and (letters.isupper() or el.find(f"{W}pPr/{W}outlineLvl") is not None) and len(letters) >= 4 and i > 0
        if heading:
            cur = {"id": f"s{i}", "name": txt, "el": el, "entries": [], "skills": [], "locked": False}
            sections.append(cur)
            entry = None
            continue
        if cur is None:
            continue
        cur["locked"] = cur["locked"] or locked
        if is_list:
            if entry is None:
                entry = {"id": f"e{i}", "title": "", "heads": [], "bullets": []}
                cur["entries"].append(entry)
            entry["bullets"].append({"id": f"p{i}", "el": el, "text": txt, "md": _md(el), "links": el.find(f".//{W}hyperlink") is not None})
        elif not txt:
            entry = None if entry and entry["bullets"] else entry
        else:
            m = re.match(r"^([^:：]{2,40})[:：]\s*(.+)$", txt)
            if SKILLS.search(cur["name"]) and m and "," in m.group(2) and el.find(f".//{W}hyperlink") is None:
                cur["skills"].append({"id": f"p{i}", "el": el, "label": m.group(1), "items": _split_items(m.group(2))})
                continue
            if entry is None or entry["bullets"]:
                entry = {"id": f"e{i}", "title": txt.replace("\t", "  "), "heads": [], "bullets": []}
                cur["entries"].append(entry)
            entry["heads"].append(el)
    for s in sections:  # entries without bullets (education lines) are fixed text, not something to reorder
        s["entries"] = [e for e in s["entries"] if e["bullets"]]
    return {"doc": doc, "sections": sections, "text": "\n".join(_text(p) for p in body.iter(f"{W}p"))}


def outline(st: dict[str, Any]) -> str:
    lines = []
    for s in st["sections"]:
        if not s["entries"] and not s["skills"]:
            continue
        lines.append(f"\n## [{s['id']}] {s['name']}")
        for k in s["skills"]:
            lines.append(f"[{k['id']}] {k['label']}: {', '.join(k['items'])}")
        for e in s["entries"]:
            lines.append(f"\n[{e['id']}] {e['title']}")
            lines += [f"  [{b['id']}] {b['md']}" for b in e["bullets"]]
    return "\n".join(lines)


# --- deciding ----------------------------------------------------------------------------------


def _rules_text(cfg: dict[str, Any]) -> str:
    r = ["Order the bullets inside each entry so the ones that match the posting come first."]
    r.append("You may leave out bullets that say nothing to this posting, but keep at least %d per entry." % int(cfg.get("min_bullets") or 2)
             if cfg.get("allow_drop") else "Keep every bullet: list all bullet ids of each entry in `keep`.")
    which = cfg.get("reorder_entries") or "projects"
    r.append({"none": "Do not reorder entries.", "projects": "You may reorder the entries of project-type sections; leave work experience and education in date order.",
              "all": "You may reorder the entries of any section."}[which])
    r.append("You may reorder the items of a skills line (same items, most relevant first)." if cfg.get("reorder_skills") else "Leave skills lines as they are.")
    if cfg.get("mode") == "rephrase":
        r.append("Rewording is allowed and wanted where it helps. Go through the bullets you put first: where one describes work the posting asks for but in other "
                 "words (the posting says \"embedded platforms\" and \"automated test\", the bullet says \"firmware\" and \"CI checks\"), reword it under `rewrites` so "
                 "that a reader of this posting recognises it - the posting's term for the same thing, the matching part of the bullet moved to its start. Same facts, "
                 "same numbers, same tools, not longer than the original, nothing claimed that the bullet does not say. Expect a few such bullets on a résumé that "
                 "fits the posting; none only when every relevant bullet already speaks the posting's language. A bullet that would not read differently to this "
                 "employer is left alone. Keep **bold** on the same kind of phrases.")
    else:
        r.append("Do not change any wording: leave `rewrites` empty.")
    r.append("Always fill `least_relevant` with every bullet id, least relevant first.")
    return "\n".join("- " + x for x in r)


def plan(job: Job, st: dict[str, Any], cfg: dict[str, Any], instructions: str = "") -> dict[str, Any]:
    prompt = (f"<resume_outline>{outline(st)}\n</resume_outline>\n\n<job>\nCompany: {job.company}\nTitle: {job.title}\n\n{(job.jd_text or job.summary or '')[:12000]}\n</job>\n\n"
              f"<rules>\n{_rules_text(cfg)}\n</rules>\n")
    if instructions:
        prompt += f"\n<instructions_from_applicant>\n{instructions}\n</instructions_from_applicant>\n"
    from . import prompts

    return llm.json(prompt, PLAN_SCHEMA, system=prompts.get("tailor"))


def _norm_num(s: str) -> str:
    return s.replace(",", "").rstrip(".")


def rewrite_problem(old: str, new: str, resume_text: str) -> str:
    """Why a reworded bullet is not acceptable ('' = fine). Pure text checks, no model."""
    plain_new, plain_old = new.replace("**", ""), old.replace("**", "")
    if len(plain_new) > len(plain_old) * 1.15 + 10:
        return "longer than the original"
    nums_old = {_norm_num(n) for n in re.findall(r"\d[\d,.]*", plain_old)}
    for n in re.findall(r"\d[\d,.]*", plain_new):
        if _norm_num(n) not in nums_old:
            return f"number {n} is not in the original bullet"
    low = resume_text.lower()
    words = re.findall(r"[A-Za-z][A-Za-z0-9+#./-]*", plain_new)
    for i, w in enumerate(words):
        w = w.rstrip(".,/-")
        named = any(c.isupper() for c in w[1:]) or any(c.isdigit() or c in "+#" for c in w) or (w[:1].isupper() and i > 0)
        if named and len(w) > 1 and w.lower() not in low:
            return f"'{w}' does not appear in the résumé"
    return ""


def _set_runs(el, md: str) -> None:  # noqa: ANN001
    """Replace a paragraph's text with ``md`` (**bold** segments), keeping the paragraph's own font."""
    runs = [r for r in el.findall(f"{W}r")]
    plain = next((r for r in runs if not _bold(r) and _text(r).strip()), runs[0])
    for r in runs:
        el.remove(r)
    for i, seg in enumerate(re.split(r"\*\*", md)):
        if not seg:
            continue
        r = copy.deepcopy(plain)
        for child in list(r):
            if not child.tag.endswith("}rPr"):
                r.remove(child)
        rpr = r.find(f"{W}rPr")
        if rpr is None:
            rpr = r.makeelement(f"{W}rPr", {})
            r.insert(0, rpr)
        for b in rpr.findall(f"{W}b") + rpr.findall(f"{W}bCs"):
            rpr.remove(b)
        if i % 2:
            rpr.append(rpr.makeelement(f"{W}b", {}))
        t = r.makeelement(f"{W}t", {"{http://www.w3.org/XML/1998/namespace}space": "preserve"})
        t.text = seg
        r.append(t)
        el.append(r)


def _spacing(el):  # noqa: ANN001, ANN202
    sp = el.find(f"{W}pPr/{W}spacing")
    return copy.deepcopy(sp) if sp is not None else None


def _set_spacing(el, sp) -> None:  # noqa: ANN001
    """Paragraph spacing belongs to the position (the last bullet before a heading carries the gap), not to the text."""
    ppr = el.find(f"{W}pPr")
    if ppr is None:
        if sp is None:
            return
        ppr = el.makeelement(f"{W}pPr", {})
        el.insert(0, ppr)
    old = ppr.find(f"{W}spacing")
    if old is not None:
        ppr.remove(old)
    if sp is not None:
        # keep schema order: spacing comes before ind / jc / rPr and after numPr etc.
        later = [c for c in ppr if c.tag in (f"{W}ind", f"{W}contextualSpacing", f"{W}jc", f"{W}rPr", f"{W}sectPr", f"{W}outlineLvl")]
        if later:
            later[0].addprevious(copy.deepcopy(sp))
        else:
            ppr.append(copy.deepcopy(sp))


def _place(elements: list, anchor) -> None:  # noqa: ANN001
    for el in elements:
        anchor.addprevious(el)


def apply(st: dict[str, Any], p: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Carry out the allowed parts of the plan on the document. Returns the list of changes made."""
    changes: list[dict[str, Any]] = []
    mode = cfg.get("mode") or "select"
    by_entry = {b["entry"]: b["keep"] for b in p.get("bullets", [])}
    rewrites = {r["id"]: r["text"] for r in p.get("rewrites", [])} if mode == "rephrase" else {}
    orders = {o["section"]: o["entries"] for o in p.get("entry_order", [])}
    skills = {k["id"]: k["items"] for k in p.get("skills", [])} if cfg.get("reorder_skills") else {}
    which = cfg.get("reorder_entries") or "projects"
    min_b = max(1, int(cfg.get("min_bullets") or 2))

    for s in st["sections"]:
        for k in s["skills"]:
            new = skills.get(k["id"])
            if new and sorted(x.lower() for x in new) == sorted(x.lower() for x in k["items"]) and new != k["items"]:
                runs = k["el"].findall(f"{W}r")
                label_end = 0
                seen = ""
                for idx, r in enumerate(runs):  # the label is everything up to and including the colon
                    seen += _text(r)
                    if ":" in seen or "：" in seen:
                        label_end = idx + 1
                        break
                rest = runs[label_end:]
                if label_end and rest:
                    first = rest[0]
                    for r in rest[1:]:
                        k["el"].remove(r)
                    ts = first.findall(f"{W}t")
                    for t in ts[1:]:
                        first.remove(t)
                    ts[0].text = ", ".join(new)
                    ts[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
                    changes.append({"type": "skills", "where": k["label"], "before": ", ".join(k["items"]), "after": ", ".join(new)})
                    k["items"] = new
        if not s["entries"] or s["locked"]:
            continue
        ids = [e["id"] for e in s["entries"]]
        head_sp = [_spacing(e["heads"][0]) if e["heads"] else None for e in s["entries"]]  # by position, before anything moves
        tail_sp = [_spacing(e["bullets"][-1]["el"]) for e in s["entries"]]
        want = orders.get(s["id"]) or ids
        allowed = which == "all" or (which == "projects" and not CHRONO.search(s["name"]))
        order = want if allowed and sorted(want) == sorted(ids) else ids
        for e in s["entries"]:
            own = [b["id"] for b in e["bullets"]]
            keep = [i for i in dict.fromkeys(by_entry.get(e["id"]) or own) if i in own]
            if not cfg.get("allow_drop") or len(keep) < min(min_b, len(own)):
                keep += [i for i in own if i not in keep]  # nothing may be left out: missing ones go back at the end
            bmap = {b["id"]: b for b in e["bullets"]}
            inner_sp = [_spacing(b["el"]) for b in e["bullets"]]
            for i in own:
                if i not in keep:
                    changes.append({"type": "drop", "where": e["title"], "before": bmap[i]["text"]})
            if [i for i in own if i in keep] != keep:
                changes.append({"type": "reorder_bullets", "where": e["title"], "after": [bmap[i]["text"][:90] for i in keep]})
            for i in keep:
                b = bmap[i]
                new = (rewrites.get(i) or "").strip()
                if new and new.replace("**", "") != b["text"] and not b["links"]:
                    why = rewrite_problem(b["md"], new, st["text"])
                    if why:
                        changes.append({"type": "rewrite_rejected", "where": e["title"], "before": b["text"], "after": new.replace("**", ""), "why": why})
                    else:
                        _set_runs(b["el"], new)
                        changes.append({"type": "rewrite", "where": e["title"], "before": b["text"], "after": new.replace("**", "")})
                        b["text"], b["md"] = new.replace("**", ""), new
            e["bullets"] = [bmap[i] for i in keep]
            for pos, b in enumerate(e["bullets"]):
                _set_spacing(b["el"], inner_sp[min(pos, max(0, len(inner_sp) - 2))])
            e["dropped"] = [bmap[i] for i in own if i not in keep]
        emap = {e["id"]: e for e in s["entries"]}
        if order != ids:
            changes.append({"type": "reorder_entries", "where": s["name"], "after": [emap[i]["title"][:80] for i in order]})
        # rebuild this section's block in place
        block = [el for e in s["entries"] for el in (*e["heads"], *[b["el"] for b in e["bullets"]], *[b["el"] for b in e.get("dropped", [])])]
        last = max(block, key=lambda el: list(el.getparent()).index(el))
        anchor = last.getnext()
        if anchor is None:
            continue
        for el in block:
            el.getparent().remove(el)
        _place([el for i in order for el in (*emap[i]["heads"], *[b["el"] for b in emap[i]["bullets"]])], anchor)
        s["entries"] = [emap[i] for i in order]
        for pos, e in enumerate(s["entries"]):
            if e["heads"]:
                _set_spacing(e["heads"][0], head_sp[pos])
            _set_spacing(e["bullets"][-1]["el"], tail_sp[pos])
    return changes


# --- writing -----------------------------------------------------------------------------------


def render(doc, docx: Path) -> dict[str, Any]:  # noqa: ANN001
    """Save and export to PDF with Word. Returns {docx, pdf, pages}."""
    from pypdf import PdfReader

    docx.parent.mkdir(parents=True, exist_ok=True)
    pdf = docx.with_suffix(".pdf")
    pdf.unlink(missing_ok=True)
    doc.save(str(docx))
    from . import convert

    convert.docx_to_pdf(docx)
    return {"docx": str(docx), "pdf": str(pdf), "pages": len(PdfReader(str(pdf)).pages)}


def base_pages(base: dict[str, Any]) -> int:
    """Page count of the original (measured once per file)."""
    if base["meta"].get("pages"):
        return int(base["meta"]["pages"])
    from docx import Document as Docx

    out = render(Docx(base["path"]), config.MATERIALS / "resume_base" / f"base_{base['id']}.docx")
    with db.session() as s:
        d = s.get(Document, base["id"])
        d.meta = {**(d.meta or {}), "pages": out["pages"]}
    return out["pages"]


def existing(job_id: int) -> dict[str, Any] | None:
    with db.session() as s:
        d = s.query(Document).filter_by(kind=OUT_KIND, job_id=job_id, active=1).order_by(Document.id.desc()).first()
        if d is None or not Path(d.path).exists():
            return None
        return {"id": d.id, "name": d.name, "path": d.path, "kind": d.kind, "tailor": (d.meta or {}).get("tailor", {})}


def make(job: Job, *, instructions: str = "", automatic: bool = False) -> dict[str, Any]:
    """Plan -> apply -> render -> trim to the page limit. Stores a Document and returns its dict."""
    cfg = settings()
    base = base_doc()
    if base is None:
        raise RuntimeError("没有上传 Word 版简历（材料库 → 简历 Word 原稿），没法精调")
    st = parse(base["path"])
    n_bullets = sum(len(e["bullets"]) for s in st["sections"] for e in s["entries"])
    if n_bullets < 3:
        raise RuntimeError("这份 Word 简历里没有找到项目符号列表，程序看不懂它的结构，没法精调")
    target = int(cfg.get("target_pages") or 0) or base_pages(base)
    p = plan(job, st, cfg, instructions)
    changes = apply(st, p, cfg)
    name = re.sub(r"[^A-Za-z0-9]+", "_", f"Resume_{job.company}_{job.title}").strip("_")[:70]
    from . import materials

    # A folder of its own for this writing (materials.version_dir): the résumé written before it, which a draft may
    # have been approved with, is not written over - and stays the one in use unless this one passes.
    with materials.version_dir(job.id, OUT_KIND) as out_dir:
        docx = out_dir / f"{name}.docx"
        out = render(st["doc"], docx)
        problems: list[str] = []
        if out["pages"] > target:
            min_b = max(1, int(cfg.get("min_bullets") or 2))
            entries = [e for s in st["sections"] if not s["locked"] for e in s["entries"]]
            where = {b["id"]: e for e in entries for b in e["bullets"]}
            queue = [i for i in dict.fromkeys(p.get("least_relevant", [])) if i in where]
            for _ in range(12):
                if out["pages"] <= target or not queue:
                    break
                i = queue.pop(0)
                e = where[i]
                if len(e["bullets"]) <= min_b:
                    continue
                b = next(x for x in e["bullets"] if x["id"] == i)
                if b is e["bullets"][-1]:  # the gap after the entry moves to the bullet that is now last
                    _set_spacing(e["bullets"][-2]["el"], _spacing(b["el"]))
                b["el"].getparent().remove(b["el"])
                e["bullets"].remove(b)
                changes.append({"type": "drop", "where": e["title"], "before": b["text"], "why": "to fit the page"})
                out = render(st["doc"], docx)
            if out["pages"] > target:
                problems.append(f"精调后是 {out['pages']} 页，超过了 {target} 页的限制")
        real = [c for c in changes if c["type"] != "rewrite_rejected"]
        info = {"focus": p.get("focus", ""), "keywords": p.get("keywords", [])[:12], "changes": changes, "mode": cfg.get("mode"), "base_id": base["id"], "base_name": base["name"],
                "pages": out["pages"], "problems": problems, "unchanged": not real}
        # The one in use from here on only if it is fit to be sent: within the page limit - and, when the program wrote
        # it by itself, different from the résumé as uploaded (one the applicant asked for is theirs to look at).
        current = not problems and not (automatic and info["unchanged"])
        doc_id = materials.publish(OUT_KIND, job.id, out["pdf"], {"tailor": info, "docx": out["docx"], "pages": out["pages"]}, current=current)
    return {"id": doc_id, "name": Path(out["pdf"]).name, "path": out["pdf"], "kind": OUT_KIND, "tailor": info, "current": current}
