"""Who is using the program: career stage, field, target roles, region.

There is one program, not one per audience. The persona, asked once by the first-run guide and
editable afterwards, drives three things:

* defaults  - intake rules, scoring rules, where postings come from, how cautious submitting is;
* display   - which fields, columns and material types are shown (``features``);
* wording   - a short note about the applicant that goes into writing prompts (``note``).

Defaults are written once, when the guide finishes; after that the user's own settings win and the
persona never overwrites them again.
"""

from __future__ import annotations

from typing import Any

import logging

from . import db, knowledge, llm

STAGES: dict[str, dict[str, Any]] = {
    "student": {"name": "在校，找实习 / co-op", "kind_words": ["intern", "internship", "co-op", "coop", "student", "summer analyst", "placement"],
                "exclude": ["senior", "staff", "principal", "manager", "director", "lead", "phd"], "pages": 1, "min_draft": 8.0, "auto_submit": True},
    "new_grad": {"name": "应届 / 刚毕业", "kind_words": ["new grad", "graduate", "entry level", "entry-level", "junior", "associate", "analyst", "early career", "campus", "trainee"],
                 "exclude": ["senior", "staff", "principal", "manager", "director", "lead", "intern", "internship"], "pages": 1, "min_draft": 8.0, "auto_submit": True},
    "early": {"name": "工作 1–3 年", "kind_words": [], "exclude": ["senior", "staff", "principal", "director", "vp", "head of", "intern", "internship", "co-op"],
              "pages": 2, "min_draft": 7.5, "auto_submit": False},
    "mid": {"name": "工作 3–8 年", "kind_words": [], "exclude": ["intern", "internship", "co-op", "junior", "entry level", "graduate", "director", "vp"],
            "pages": 2, "min_draft": 8.0, "auto_submit": False},
    "senior": {"name": "8 年以上 / 管理岗", "kind_words": [], "exclude": ["intern", "internship", "co-op", "junior", "entry level", "graduate", "associate"],
               "pages": 0, "min_draft": 11.0, "auto_submit": False},  # 11 = never draft automatically: people at this level pick by hand
}

FIELDS: dict[str, dict[str, Any]] = {
    "software": {"name": "软件与数据", "roles": ["software", "developer", "engineer", "engineering", "swe", "sde", "machine learning", "ml", "ai", "data", "backend", "frontend",
                                             "full stack", "fullstack", "devops", "cloud", "security", "infrastructure"],
                 "not": ["sales", "marketing", "legal", "finance", "accounting", "recruiter", "retail", "mba"], "bigtech": True},
    "engineering": {"name": "硬件与工程（电气、机械、土木…）", "roles": ["engineer", "engineering", "hardware", "electrical", "mechanical", "civil", "firmware", "embedded", "manufacturing",
                                                              "process", "design", "test", "quality"],
                    "not": ["sales", "marketing", "legal", "accounting", "recruiter", "retail"], "bigtech": True},
    "business": {"name": "商科（金融、咨询、市场、运营）", "roles": ["analyst", "finance", "financial", "investment", "banking", "consulting", "consultant", "strategy", "marketing", "operations",
                                                          "business", "product", "sales", "account", "audit", "tax", "risk", "supply chain", "project"],
                 "not": ["software engineer", "developer", "nurse", "technician"], "bigtech": False},
    "design": {"name": "设计（UX、视觉、工业）", "roles": ["design", "designer", "ux", "ui", "product design", "visual", "graphic", "brand", "research", "creative", "motion"],
               "not": ["engineer", "sales", "accounting"], "bigtech": True},
    "hr": {"name": "人力资源", "roles": ["human resources", "hr", "people", "talent", "recruit", "recruiter", "recruiting", "compensation", "learning", "organizational"],
           "not": ["engineer", "developer", "sales"], "bigtech": False},
    "psych": {"name": "心理与社会科学", "roles": ["psychology", "psychologist", "counsel", "counselor", "counsellor", "therapist", "behavio", "mental health", "social work", "research assistant",
                                           "case manager", "clinical", "community"],
              "not": ["engineer", "developer", "sales"], "bigtech": False},
    "academic": {"name": "科研与学术", "roles": ["research", "researcher", "scientist", "postdoc", "postdoctoral", "lecturer", "professor", "faculty", "fellow", "lab"],
                 "not": ["sales", "marketing"], "bigtech": False},
    "health": {"name": "医疗", "roles": ["nurse", "nursing", "clinical", "medical", "pharmac", "therapist", "physician", "health", "care"], "not": ["engineer", "developer"], "bigtech": False},
    "education": {"name": "教育", "roles": ["teacher", "teaching", "tutor", "instructor", "education", "curriculum", "school", "learning"], "not": ["engineer", "developer"], "bigtech": False},
    "other": {"name": "其他（由 AI 根据目标岗位生成）", "roles": [], "not": [], "bigtech": False},
}

# What the first user of this program had before personas existed. An install that already has postings keeps
# exactly this until its owner changes it (see ``migrate``).
LEGACY: dict[str, Any] = {
    "intake.title_any": ["intern", "internship", "co-op", "coop", "student", "new grad"],
    "intake.title_role_any": ["software", "developer", "engineer", "engineering", "swe", "sde", "machine learning", "ml", "ai", "data", "backend", "frontend",
                              "full stack", "fullstack", "firmware", "embedded", "devops", "cloud", "security", "systems", "compiler", "infrastructure"],
    "intake.title_none": ["senior", "staff", "principal", "manager", "director", "phd", "mba", "sales", "marketing", "legal", "finance", "accounting", "recruiter", "retail"],
    "intake.countries": ["CA", "US"],
    "sources.search_terms": ["intern", "co-op"],
    "sources.bigtech": {"amazon": True, "apple": True, "google": True, "microsoft": True, "meta": True, "nvidia": True, "amd": True, "intel": True},
    "persona": {"stage": "student", "field": "software", "targets": ["backend", "full-stack", "machine learning engineer"], "countries": ["CA", "US"], "sponsorship": True,
                "portal": "ubc", "strategy": "volume"},
}

EMPTY: dict[str, Any] = {"stage": "", "field": "", "targets": [], "countries": [], "sponsorship": False, "portal": "", "strategy": "volume"}

RULES_SCHEMA = llm.obj({
    "title_role_any": {"type": "array", "items": {"type": "string"}, "description": "lower-case words or short phrases; a posting is kept when its title contains at least one. 15-30 items, including common synonyms and abbreviations."},
    "title_none": {"type": "array", "items": {"type": "string"}, "description": "lower-case words that mark a posting as clearly not for this applicant (other professions, wrong seniority). 8-20 items."},
    "scoring_md": {"type": "string", "description": "Markdown scoring rules: '# Scoring rules', a '## Hard exclusions' list, and a '## Fit (0-10)' list with four bands (9-10, 7-8.5, 5-6.5, below 5)."},
    "examples": {"type": "array", "items": {"type": "string"}, "description": "8 realistic posting titles as 'Title | City, Region, Country': 5 the applicant would want, 3 they would not."},
})

log = logging.getLogger("autoapply.persona")


def get() -> dict[str, Any]:
    return {**EMPTY, **(db.get_setting("persona") or {})}


def migrate() -> None:
    """Run once per data folder. An install that already has postings is the original, single-user set-up: pin down the
    values it was running with, so that making the built-in defaults neutral changes nothing for it."""
    from .models import Job, Setting

    with db.session() as s:
        if s.get(Setting, "onboarding.done") is not None:
            return
        has_jobs = s.query(Job.id).first() is not None
        present = {r.key for r in s.query(Setting.key)}
    if has_jobs:
        for k, v in LEGACY.items():
            if k not in present:
                db.set_setting(k, v)
        if not knowledge.DOCS["scoring"].exists():
            knowledge.DOCS["scoring"].parent.mkdir(parents=True, exist_ok=True)
            knowledge.DOCS["scoring"].write_text(knowledge.LEGACY_SCORING, encoding="utf-8")
    db.set_setting("onboarding.done", has_jobs)
    from . import employers

    employers.migrate_legacy()


def template(p: dict[str, Any]) -> dict[str, Any]:
    """Settings that follow from a persona without asking a model."""
    st, fd = STAGES.get(p.get("stage") or "", {}), FIELDS.get(p.get("field") or "", {})
    targets = [t.strip().lower() for t in p.get("targets") or [] if t.strip()]
    roles = list(dict.fromkeys([*targets, *[w for t in targets for w in t.split() if len(w) > 3], *fd.get("roles", [])]))
    out: dict[str, Any] = {
        "intake.enabled": True,
        "intake.title_any": list(st.get("kind_words", [])),
        "intake.title_role_any": roles,
        "intake.title_none": list(dict.fromkeys([*st.get("exclude", []), *fd.get("not", [])])),
        "intake.countries": [c.upper() for c in p.get("countries") or []],
        "queue.min_score_for_draft": st.get("min_draft", 8.0) if p.get("strategy") != "targeted" else 11.0,
        "policy.default": "approve_then_submit" if st.get("auto_submit") and p.get("strategy") != "targeted" else "manual",
        "tailor.target_pages": 0 if p.get("field") == "academic" else st.get("pages", 0),   # an academic CV has no page limit
        "tailor.allow_drop": False,
        "sources.bigtech": {k: bool(fd.get("bigtech")) for k in LEGACY["sources.bigtech"]},
        "sources.search_terms": (st.get("kind_words") or [])[:2] or targets[:3] or ["analyst"],
    }
    return out


def describe(p: dict[str, Any]) -> str:
    st, fd = STAGES.get(p.get("stage") or "", {}), FIELDS.get(p.get("field") or "", {})
    bits = [st.get("name", ""), fd.get("name", "").split("（")[0], ("目标：" + "、".join(p["targets"])) if p.get("targets") else "",
            ("地区：" + "、".join(p["countries"])) if p.get("countries") else "", "需要工作签证担保" if p.get("sponsorship") else ""]
    return "；".join(b for b in bits if b)


def note(p: dict[str, Any] | None = None) -> str:
    """One paragraph about the applicant for writing prompts ('' when nothing is known)."""
    p = p or get()
    if not p.get("stage") and not p.get("field"):
        return ""
    stage = {"student": "a student looking for an internship or co-op", "new_grad": "a new graduate looking for a first full-time role", "early": "an early-career professional (1-3 years)",
             "mid": "an experienced professional (3-8 years)", "senior": "a senior professional or manager (8+ years)"}.get(p.get("stage") or "", "")
    field = {"software": "software and data", "engineering": "engineering", "business": "business (finance, consulting, marketing, operations)", "design": "design",
             "hr": "human resources", "psych": "psychology and social science", "academic": "research and academia", "health": "healthcare", "education": "education"}.get(p.get("field") or "", "")
    out = f"The applicant is {stage or 'a job seeker'}" + (f" in {field}" if field else "") + "."
    if p.get("targets"):
        out += " Target roles: " + ", ".join(p["targets"]) + "."
    return out + " Write at the level and in the register that fits this."


PROFILE_ASKS = {
    "student": ["work terms available (season, year, 4 or 8 months)", "expected graduation month and year", "GPA (if the applicant wants it stated)",
                "whether the program requires a co-op / internship agreement and who the school contact is"],
    "new_grad": ["graduation month and year", "earliest start date", "GPA (if the applicant wants it stated)", "willingness to relocate"],
    "early": ["current job title and employer", "notice period", "earliest start date", "salary expectation (range and currency)", "willingness to relocate"],
    "mid": ["current job title and employer", "notice period", "salary expectation (range and currency)", "whether they manage people and how many", "willingness to relocate or travel"],
    "senior": ["current title and scope (team size, budget)", "notice period", "compensation expectation (base, bonus, equity)", "board / executive exposure", "non-compete or other restrictions"],
}
FIELD_ASKS = {
    "business": ["professional designations held or in progress (CPA, CFA level ...)", "languages spoken"],
    "design": ["portfolio link", "tools used daily"],
    "academic": ["ORCID or publication list link", "names and contact details of referees", "research areas"],
    "health": ["licences / registrations and their jurisdiction", "immunisation or background-check status if forms ask"],
    "psych": ["licences / registrations and their jurisdiction", "supervised practice hours"],
    "education": ["teaching certification and jurisdiction", "grade levels / subjects"],
    "engineering": ["professional registration (P.Eng, EIT, FE) if any", "security-clearance eligibility"],
    "software": ["GitHub / portfolio link"],
    "hr": ["HR designations (CHRP, SHRM-CP ...)"],
}
WRITING = {
    "student": "Co-op / internship letter: availability and term length up front or in the close, coursework and projects as evidence, eager but concrete.",
    "new_grad": "Entry-level letter: one or two strongest projects or internships as evidence, clear about start date; no apologising for limited experience.",
    "early": "Lead with results from the current job; show growth in responsibility. Do not list coursework.",
    "mid": "Lead with outcomes and scope (numbers, ownership). Mention leading or mentoring others where true. No coursework, no generic enthusiasm.",
    "senior": "Executive register: business outcomes, scale, teams built and led, strategy. Short paragraphs. No task lists.",
}
FIELD_WRITING = {
    "business": "Business readers look for commercial judgement, numbers, and client or stakeholder work; name the industry and the firm's actual practice or product.",
    "design": "Point to specific pieces in the portfolio and the problem each solved; process and outcome over tools.",
    "academic": "Academic register: research fit with the group or department, publications and methods, teaching where relevant.",
    "health": "Lead with licence / registration and patient populations served; be exact about settings and scope of practice.",
    "psych": "Be exact about populations, modalities and supervised experience; no clinical claims beyond what the résumé states.",
    "education": "Name certification, grade levels and subjects; give one concrete classroom outcome.",
    "hr": "Tie experience to HR outcomes (time to hire, retention, programs delivered) and to the organisation's size and sector.",
}


def profile_asks(p: dict[str, Any] | None = None) -> list[str]:
    """Things forms will ask this kind of applicant that a résumé usually does not state."""
    p = p or get()
    from . import regions

    return [*PROFILE_ASKS.get(p.get("stage") or "", []), *FIELD_ASKS.get(p.get("field") or "", []), *regions.asks(p.get("countries") or [])]


def writing_guide(p: dict[str, Any] | None = None) -> str:
    p = p or get()
    return " ".join(x for x in (WRITING.get(p.get("stage") or "", ""), FIELD_WRITING.get(p.get("field") or "", "")) if x)


def suggest(p: dict[str, Any]) -> dict[str, Any]:
    """Intake words, scoring rules and example titles for this persona. Uses the model when there is one; the built-in
    templates otherwise, so the guide can always go on."""
    base = template(p)
    out = {"settings": base, "scoring_md": default_scoring(p), "examples": [], "by": "template"}
    try:
        prompt = (f"Applicant: {note(p) or 'unknown'}\nCountries: {', '.join(p.get('countries') or []) or 'any'}\nNeeds visa sponsorship: {'yes' if p.get('sponsorship') else 'no'}\n"
                  f"Words that mark the right kind of posting for this career stage (already decided, do not repeat them): {base['intake.title_any']}\n"
                  f"Starting list of role words: {base['intake.title_role_any']}\nStarting list of excluded words: {base['intake.title_none']}\n\n"
                  "Improve the two word lists for filtering job-posting TITLES for this applicant, and write scoring rules for reading full postings. "
                  "Hard exclusions should be things a posting states that rule the applicant out (wrong seniority, a licence they would need, no sponsorship when they need it, wrong location). "
                  "Do not invent facts about the applicant.")
        r = llm.json(prompt, RULES_SCHEMA, system="You set up a job-search filter. Be concrete and conservative: a word that would also match unrelated jobs does not belong in a list.")
        roles = [w.strip().lower() for w in r["title_role_any"] if 1 < len(w.strip()) <= 40][:40]
        none = [w.strip().lower() for w in r["title_none"] if 1 < len(w.strip()) <= 40 and w.strip().lower() not in roles][:30]
        md = r["scoring_md"].strip()
        if md.startswith('"') and md.endswith('"'):  # some models wrap the text in a second layer of JSON quoting
            import json as _json

            try:
                md = str(_json.loads(md)).strip()
            except ValueError:
                md = md.strip('"').replace("\\n", "\n")
        if md and not md.startswith("#"):
            md = "# Scoring rules\n\n" + md
        if len(roles) < 5 or "Fit" not in md:
            out["note"] = "AI 给的建议不完整，先用了通用模板。可以点“重新生成建议”再试一次。"
        else:
            r["scoring_md"] = md
            out = {"settings": {**base, "intake.title_role_any": roles, "intake.title_none": list(dict.fromkeys([*base["intake.title_none"], *none]))},
                   "scoring_md": r["scoring_md"].strip() + "\n", "examples": [e for e in r["examples"] if "|" in e][:10], "by": "ai"}
    except llm.LLMError:
        # why is in the program's log; the page gets the fact, not the text of an internal error
        log.warning("persona suggestions fell back to the template", exc_info=True)
        out["note"] = "AI 暂时用不了，先给了一份通用模板，可以直接改；AI 服务的状态在“设置 → 账号与连接 → AI 服务”里可以测试。"
    return out


def default_scoring(p: dict[str, Any]) -> str:
    st = p.get("stage") or ""
    targets = "、".join(p.get("targets") or []) or FIELDS.get(p.get("field") or "", {}).get("name", "target roles").split("（")[0]
    ex = ["- The posting requires a licence, clearance or citizenship the applicant does not have."]
    if p.get("sponsorship"):
        ex.append("- States that no visa sponsorship is available.")
    if st in ("student", "new_grad"):
        ex.append("- Requires several years of full-time experience.")
    if st in ("mid", "senior"):
        ex.append("- Internship, co-op or entry-level posting.")
    if p.get("countries"):
        ex.append(f"- Located outside {', '.join(p['countries'])} with no remote option.")
    return ("# Scoring rules\n\nScore every posting 0-10 for fit after reading the FULL job description.\nNever score from the title alone; if the description is missing, leave the job unscored.\n\n"
            "## Hard exclusions (do not apply; score 0 and name the rule)\n\n" + "\n".join(ex) + "\n\n## Fit (0-10)\n\n"
            f"- 9-10: the core of what the applicant is looking for ({targets}).\n- 7-8.5: closely related roles where most of the work matches.\n"
            "- 5-6.5: adjacent roles; some overlap, not the target.\n- below 5: off-target.\n")


def apply(p: dict[str, Any], settings: dict[str, Any], scoring_md: str = "") -> None:
    """Finish the guide: store the persona, write the defaults it implies, mark onboarding done."""
    from . import config

    clean = {**EMPTY, **{k: v for k, v in p.items() if k in EMPTY}}
    db.set_setting("persona", clean)
    for k, v in {**template(clean), **settings}.items():
        if k in config.DEFAULT_SETTINGS:
            db.set_setting(k, v)
    if scoring_md.strip():
        knowledge.write("scoring", scoring_md.strip() + "\n", source="user", note="first-run guide")
    db.set_setting("onboarding.done", True)
    from . import employers

    employers.ensure_builtin([k for k, on in (settings.get("sources.bigtech") or {}).items() if on])


def features(p: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the pages show. With no persona (an install from before the guide existed) everything is shown."""
    p = p or get()
    st, fd = p.get("stage") or "", p.get("field") or ""
    known = bool(st or fd)
    student = st in ("student", "") or not known
    experienced = st in ("early", "mid", "senior")
    kinds = ["resume_site", "resume_docx", "cl_template", "cl_example", "certificate", "reference", "other", "source"]
    if student or st == "new_grad":
        kinds += ["transcript"]
    if p.get("portal") or not known:
        kinds += ["resume_portal", "summary_sheet"]
    if fd in ("design", "academic", "") or not known:
        kinds += ["portfolio", "writing_sample"]
    if fd == "academic" or not known:
        kinds += ["research_statement", "teaching_statement", "publications", "diversity_statement"]
    return {
        "known": known, "stage": st, "field": fd, "summary": describe(p),
        "term": student,                       # work term / months columns and profile fields
        "portal": p.get("portal") or ("ubc" if not known else ""),   # school portal import
        "salary_first": experienced,           # show pay in the jobs table by default
        "referrals": st in ("mid", "senior") or p.get("strategy") == "targeted",
        "doc_kinds": kinds,
        "job_columns": (["source", "salary"] if experienced else ["source"]),
        "resume_word": "CV" if fd == "academic" else "简历",
    }
