"""JD parser — LLM-assisted structured requirement extraction.

Given a raw job description text, extracts structured JobRequirements:
skills, education level, experience range, visa/auth requirements, remote policy.
"""

from __future__ import annotations

import json
import logging
import re

from src.intake.schema import JobRequirements
from src.utils.llm import LLMError, generate_json

logger = logging.getLogger("autoapply.intake.jd_parser")

EXTRACTION_SYSTEM = """You are a job description parser.
Extract structured data from the job posting.
Return ONLY a JSON object with exactly these keys (use null for missing info):

{
  "must_have_skills": ["skill1", "skill2"],
  "preferred_skills": ["skill3"],
  "responsibilities": ["responsibility1"],
  "soft_skills": ["communication", "collaboration"],
  "keywords": ["backend", "debugging", "automation"],
  "seniority": "intern" | "entry" | "mid" | "senior" | "staff" | null,
  "domain": "software_engineering" | "data" | "machine_learning" | "devops" | null,
  "role_family": "backend" | "frontend" | "full_stack" | "data" | "mobile" | null,
  "education_level": "Bachelor's" | "Master's" | "PhD" | null,
  "experience_years_min": 0,
  "experience_years_max": null,
  "visa_sponsorship": true | false | null,
  "us_work_auth_required": true | false | null,
  "relocation_provided": true | false | null,
  "remote_ok": true | false | null
}

Rules:
- must_have_skills: only clearly required technologies/skills (e.g. "Python", "AWS", "SQL")
- preferred_skills: nice-to-have or bonus skills
- responsibilities: concrete job duties, not company marketing copy
- keywords: concise role/domain/search terms useful for matching and resume tailoring
- us_work_auth_required: true only if posting says
  "must be authorized to work in the US" or "no sponsorship"
- visa_sponsorship: true if posting explicitly offers sponsorship, false if it says no sponsorship
- Return raw JSON only, no markdown fences"""

# Fallback regex patterns when LLM is unavailable
_EXPERIENCE_RE = re.compile(
    r"(\d+)\+?\s*(?:to|-)\s*(\d+)\s*years?|(\d+)\+\s*years?|(\d+)\s*years?\s*of\s*experience",
    re.IGNORECASE,
)
_NO_SPONSOR_RE = re.compile(
    r"no\s+(?:visa\s+)?sponsorship|not\s+(?:able\s+to|going\s+to)\s+sponsor|"
    r"must\s+be\s+authorized|legally\s+authorized",
    re.IGNORECASE,
)
_TECH_KEYWORDS = {
    "python",
    "java",
    "javascript",
    "typescript",
    "react",
    "vue",
    "node",
    "fastapi",
    "spring",
    "sql",
    "postgresql",
    "mongodb",
    "redis",
    "aws",
    "gcp",
    "azure",
    "docker",
    "kubernetes",
    "graphql",
    "rest",
    "api",
    "apis",
    "testing",
    "automation",
    "debugging",
    "ci/cd",
    "machine learning",
    "data pipeline",
}
_SOFT_SKILLS = {
    "communication",
    "collaboration",
    "leadership",
    "ownership",
    "problem solving",
    "mentoring",
}


def parse_requirements(description: str, use_llm: bool = True) -> JobRequirements:
    """Extract structured requirements from a JD text.

    Tries LLM extraction first; falls back to regex heuristics on failure.
    """
    if not description or not description.strip():
        return JobRequirements()

    # Truncate very long descriptions to stay within CLI token limits
    text = description[:6000] if len(description) > 6000 else description

    if use_llm:
        try:
            return _parse_with_llm(text)
        except LLMError as e:
            logger.warning("LLM JD parsing failed (%s), using regex fallback", e)
        except Exception as e:
            logger.warning("Unexpected LLM error (%s), using regex fallback", e)

    return _parse_with_regex(text)


def _parse_with_llm(text: str) -> JobRequirements:
    """Use Claude CLI to extract structured requirements."""
    prompt = f"Parse this job description:\n\n<job_description>\n{text}\n</job_description>"
    data = generate_json(prompt, system=EXTRACTION_SYSTEM, timeout=90)
    if isinstance(data, str):
        data = json.loads(data)

    return JobRequirements.model_validate(data)


def _parse_with_regex(text: str) -> JobRequirements:
    """Regex-based fallback extractor for when LLM is unavailable."""
    reqs = JobRequirements()

    # Experience years
    m = _EXPERIENCE_RE.search(text)
    if m:
        g = m.groups()
        if g[0] and g[1]:
            reqs.experience_years_min = int(g[0])
            reqs.experience_years_max = int(g[1])
        elif g[2]:
            reqs.experience_years_min = int(g[2])
        elif g[3]:
            reqs.experience_years_min = int(g[3])

    # Visa / sponsorship
    if _NO_SPONSOR_RE.search(text):
        reqs.visa_sponsorship = False
        reqs.us_work_auth_required = True

    # Remote
    t = text.lower()
    if "remote" in t:
        reqs.remote_ok = True
    if "on-site" in t or "onsite" in t or "in-office" in t:
        reqs.remote_ok = False

    # Education
    if "phd" in t or "doctorate" in t:
        reqs.education_level = "PhD"
    elif "master" in t:
        reqs.education_level = "Master's"
    elif "bachelor" in t or "b.s." in t or "b.a." in t:
        reqs.education_level = "Bachelor's"

    reqs.keywords = _extract_keyword_hits(t)
    reqs.soft_skills = [skill for skill in sorted(_SOFT_SKILLS) if skill in t]
    reqs.responsibilities = _extract_responsibilities(text)
    reqs.seniority = _infer_seniority(t)
    reqs.domain = _infer_domain(t)
    reqs.role_family = _infer_role_family(t)

    return reqs


def _extract_keyword_hits(text: str) -> list[str]:
    hits = []
    for keyword in sorted(_TECH_KEYWORDS):
        if keyword in text:
            hits.append("REST APIs" if keyword == "apis" else keyword)
    return _dedupe(hits)


def _extract_responsibilities(text: str, max_items: int = 5) -> list[str]:
    candidates = []
    for raw_line in text.splitlines():
        line = raw_line.strip(" -•\t")
        lower = line.lower()
        if not line or len(line) > 180:
            continue
        if any(
            token in lower
            for token in (
                "build",
                "develop",
                "design",
                "implement",
                "maintain",
                "collaborate",
                "test",
                "debug",
                "ship",
            )
        ):
            candidates.append(line)
        if len(candidates) >= max_items:
            break
    return candidates


def _infer_seniority(text: str) -> str | None:
    if any(token in text for token in ("intern", "internship", "co-op", "student")):
        return "intern"
    if any(token in text for token in ("new grad", "entry level", "junior")):
        return "entry"
    if any(token in text for token in ("senior", "lead")):
        return "senior"
    if any(token in text for token in ("staff", "principal")):
        return "staff"
    return None


def _infer_domain(text: str) -> str | None:
    if "machine learning" in text or "ai model" in text or re.search(r"\bml\b", text):
        return "machine_learning"
    if any(token in text for token in ("data pipeline", "analytics", "etl")):
        return "data"
    if any(token in text for token in ("infrastructure", "devops", "kubernetes", "ci/cd")):
        return "devops"
    if any(token in text for token in ("software", "backend", "frontend", "api")):
        return "software_engineering"
    return None


def _infer_role_family(text: str) -> str | None:
    if "full stack" in text or "full-stack" in text:
        return "full_stack"
    if "frontend" in text or "front-end" in text:
        return "frontend"
    if "backend" in text or "back-end" in text or "server-side" in text:
        return "backend"
    if "mobile" in text or "ios" in text or "android" in text:
        return "mobile"
    if re.search(r"\bdata\b", text):
        return "data"
    return None


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
