"""JD parser — LLM-assisted structured requirement extraction.

Given a raw job description text, extracts structured JobRequirements:
skills, education level, experience range, visa/auth requirements, remote policy.
"""

from __future__ import annotations

import json
import logging
import re

from src.intake.schema import JobRequirements
from src.utils.llm import LLMError, claude_generate

logger = logging.getLogger("autoapply.intake.jd_parser")

EXTRACTION_SYSTEM = """You are a job description parser. Extract structured data from the job posting.
Return ONLY a JSON object with exactly these keys (use null for missing info):

{
  "must_have_skills": ["skill1", "skill2"],
  "preferred_skills": ["skill3"],
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
- us_work_auth_required: true only if posting says "must be authorized to work in the US" or "no sponsorship"
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
    raw = claude_generate(prompt, system=EXTRACTION_SYSTEM, timeout=90)

    # Strip markdown fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = [l for l in cleaned.split("\n") if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)

    data = json.loads(cleaned)

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

    return reqs
