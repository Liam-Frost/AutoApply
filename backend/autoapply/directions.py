"""What a posting's work is - its field ("direction"): one entry of a fixed list, kept as a key and said in the reader's
language.

It was whatever the model wrote ("backend", "全栈/后端", "other (mining engineering)", "MLE/时序预测" ...): 502
different labels on 1,200 postings, in two languages, and a new one with nearly every new posting. Now the model picks
from this list - a field and, within it, a specialty ("software.backend"); the field alone when no specialty fits;
"other" when no field does. The list covers work of every kind, so that it holds for an applicant in any field: finer
where postings for engineers and developers are (most of what the program reads), coarser elsewhere. What a key is
called is in the interface's catalogs (``direction.<field>._`` and ``direction.<field>.<specialty>``); the words here
are what the model reads.

A label from before the list (or one a table brought in) is "not sorted yet": the model sorts those postings into the
list in the background, by their title and summary (``sort_unsorted``)."""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("autoapply.directions")

FIELDS: dict[str, tuple[str, dict[str, str]]] = {
    "software": ("Software engineering: building software", {
        "backend": "server-side services, APIs, databases, distributed systems",
        "frontend": "web user interfaces",
        "fullstack": "both a web interface and its server side",
        "mobile": "iOS and Android apps",
        "ml": "building ML / AI systems and products: models in production, LLM applications, ML infrastructure",
        "data": "data engineering: pipelines, warehouses, ETL",
        "infra": "cloud, DevOps, SRE, platform and build infrastructure",
        "security": "security engineering of software and products",
        "qa": "testing, QA, test automation",
        "embedded": "embedded software, firmware",
        "systems": "systems software: operating systems, compilers, networking software, performance, HPC",
        "games": "games, graphics, AR / VR",
    }),
    "data": ("Data and analytics: analysing data rather than building software", {
        "science": "data science, statistics, models for decisions",
        "analytics": "data and business analytics, BI, reporting",
        "research": "ML / AI research (new methods, publications)",
        "quant": "quantitative analysis, trading research",
    }),
    "hardware": ("Electronics and computer hardware", {
        "digital": "digital design: RTL, ASIC, FPGA",
        "verification": "design and silicon verification",
        "analog": "analog, mixed-signal, IC layout",
        "board": "circuits and boards (PCB), electronics design",
        "architecture": "computer architecture, performance modelling",
        "test": "hardware test, validation, characterisation",
        "rf": "RF, wireless and communications hardware",
    }),
    "electrical": ("Electrical engineering and power", {
        "power": "power systems, grid, utilities, energy",
        "controls": "controls, automation, PLC, instrumentation",
        "design": "electrical design of buildings and equipment",
    }),
    "mechanical": ("Mechanical engineering and manufacturing", {
        "design": "mechanical design, CAD",
        "manufacturing": "manufacturing, process and industrial engineering",
        "robotics": "robotics, mechatronics",
        "vehicles": "aerospace, automotive, avionics",
        "maintenance": "maintenance, reliability",
    }),
    "civil": ("Civil engineering, construction and mining", {
        "structural": "civil and structural engineering",
        "geotechnical": "geotechnical engineering",
        "construction": "construction, estimating, site and project coordination",
        "mining": "mining",
        "environmental": "environmental and water engineering",
        "transportation": "transportation, rail",
    }),
    "process": ("Chemical, materials and process engineering", {
        "chemical": "chemical and process engineering",
        "materials": "materials engineering",
        "energy": "energy production, nuclear",
    }),
    "life": ("Life sciences and health technology", {
        "biomedical": "biomedical engineering, medical devices",
        "bioinformatics": "bioinformatics, computational biology",
        "lab": "laboratory research",
    }),
    "it": ("IT and operations: running technology for an organisation", {
        "support": "IT support, help desk",
        "networks": "networks, telecom operations",
        "sysadmin": "systems administration",
        "cybersecurity": "cybersecurity operations, governance, access management",
        "enterprise": "business systems (ERP, CRM) and their configuration",
    }),
    "product": ("Product, project and consulting", {
        "product": "product management",
        "project": "project and programme management, project controls",
        "analysis": "business analysis",
        "consulting": "consulting",
        "solutions": "solutions, sales and field engineering",
    }),
    "business": ("Business and finance", {
        "finance": "finance, accounting",
        "trading": "trading, investment",
        "operations": "operations, supply chain",
        "marketing": "marketing, communications",
        "sales": "sales, customer success",
        "people": "people, HR",
    }),
    "design": ("Design and content", {
        "ux": "UX and product design",
        "visual": "visual and graphic design",
        "content": "writing and content",
    }),
    "health": ("Healthcare", {
        "nursing": "nursing",
        "clinical": "clinical care, medicine",
        "pharmacy": "pharmacy",
        "therapy": "therapy, allied health",
    }),
    "education": ("Education", {
        "teaching": "teaching, tutoring",
        "edtech": "education technology",
    }),
    "legal": ("Law and compliance", {
        "law": "legal work",
        "compliance": "compliance, risk, privacy",
    }),
    "science": ("Natural sciences", {
        "physics": "physics, mathematics",
        "chemistry": "chemistry",
        "earth": "earth and environmental sciences, geology",
    }),
    "trades": ("Trades and technicians", {
        "technician": "technicians",
        "trade": "skilled trades",
    }),
    "other": ("Work that fits none of these fields", {}),
}

KEYS: list[str] = [k for f, (_, specs) in FIELDS.items() for k in (f, *(f"{f}.{s}" for s in specs))]
_VALID = set(KEYS)


def valid(value: str | None) -> bool:
    """Is it a key of the list (a field, or a field and a specialty)?"""
    return (value or "") in _VALID


def sorted_out(value: str | None) -> bool:
    """A label from before the list, or one brought in from elsewhere: to be sorted into it. (No label at all is not:
    a posting not read yet has none.)"""
    return bool((value or "").strip()) and not valid(value)


def coerce(value: str | None) -> str:
    """What the model gave, as a key of the list: itself when it is one, else '' (the posting keeps what it had)."""
    v = (value or "").strip().lower()
    return v if v in _VALID else ""


def for_model() -> str:
    """The list as the model reads it: each field with its specialties, one line each."""
    lines = []
    for f, (what, specs) in FIELDS.items():
        lines.append(f"- {f}: {what}" + ("" if not specs else "; " + "; ".join(f"{f}.{s} = {d}" for s, d in specs.items())))
    return "\n".join(lines)


HOW = ("The posting's field, from this list ONLY: a field and specialty (\"software.backend\"); the field alone when it is "
       "that field but no specialty fits; \"other\" when no field fits. Judge the work the posting describes (not the "
       "applicant's wishes, not the title's wording alone); a role spanning two specialties: the one most of the work is in.")


def schema_property() -> dict[str, Any]:
    """The ``direction`` property of a schema the model answers in: one of the keys."""
    return {"type": "string", "enum": KEYS, "description": HOW + "\n" + for_model()}


# --- the postings labelled before the list -----------------------------------------------------------------------------

BATCH = 40


def unsorted_ids(limit: int = 10_000) -> list[int]:
    from . import db
    from .models import Job

    with db.session() as s:
        return [j.id for j in s.query(Job.id, Job.direction).filter(Job.direction != "").order_by(Job.id.desc()) if not valid(j.direction)][:limit]


def sort_unsorted(limit: int = 400) -> dict[str, int]:
    """Sort postings whose label is not a key of the list into it: the model reads each one's title, employer, old label
    and summary - forty at a time - and gives a key. What it does not give a key for keeps its label and is tried again
    next time. Returns {"sorted": n, "left": n}."""
    from . import db, llm
    from .models import Job

    ids = unsorted_ids(limit)
    done = 0
    for i in range(0, len(ids), BATCH):
        part = ids[i:i + BATCH]
        with db.session() as s:
            rows = [{"id": j.id, "title": j.title, "employer": j.company, "label": j.direction,
                     "summary": (j.summary or (j.jd_text or "")[:400]).strip()[:400]} for j in (s.get(Job, x) for x in part) if j is not None]
        if not rows:
            continue
        schema = llm.obj({"postings": {"type": "array", "items": llm.obj({"id": {"type": "integer"}, "direction": {"type": "string", "enum": KEYS}})}})
        out = llm.json("Sort each of these job postings into the list of fields below. Each has a label someone gave it before "
                       "(in any language, often vague); use it with the title and the summary.\n\n" + HOW + "\n\n<fields>\n" + for_model()
                       + "\n</fields>\n\n<postings>\n" + "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n</postings>",
                       schema, small=True)
        got = {int(x.get("id", 0)): coerce(x.get("direction")) for x in (out or {}).get("postings", []) if isinstance(x, dict)}
        with db.session() as s:
            for jid, key in got.items():
                j = s.get(Job, jid)
                if key and j is not None and jid in part and not valid(j.direction):
                    j.direction = key
                    done += 1
    left = len(unsorted_ids())
    log.info("directions: %d postings sorted into the list, %d left", done, left)
    return {"sorted": done, "left": left}
