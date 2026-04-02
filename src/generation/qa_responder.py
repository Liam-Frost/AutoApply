"""QA auto-responder — answer common application questions.

Pipeline (descending confidence):
  1. Classify the question type
  2. Exact/pattern match from QA bank → return canonical/variant answer
  3. Template-based generation for known types
  4. LLM generation for custom/open-ended questions
  5. Flag high-risk or low-confidence answers for human review

Question types:
  authorization, sponsorship, experience_years, salary, start_date,
  why_company, why_role, strengths, weaknesses, custom
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from src.intake.schema import RawJob

logger = logging.getLogger("autoapply.generation.qa_responder")

# High-risk types that should always be flagged for review
HIGH_RISK_TYPES = {"salary", "authorization", "sponsorship"}


@dataclass
class QAResponse:
    """A generated answer for an application question."""

    question: str
    question_type: str
    answer: str
    confidence: str = "high"          # high / medium / low
    needs_review: bool = False
    source: str = "qa_bank"           # qa_bank / template / llm


def answer_questions(
    questions: list[str],
    job: RawJob,
    profile_data: dict[str, Any],
    qa_entries: list[dict] | None = None,
    use_llm: bool = True,
) -> list[QAResponse]:
    """Answer a batch of application questions.

    Args:
        questions: List of question texts from the application form.
        job: The target job (for context).
        profile_data: Full applicant profile dict.
        qa_entries: Pre-loaded QA bank entries (list of dicts with
            question_pattern, question_type, canonical_answer, variants,
            confidence, needs_review). If None, only template/LLM used.
        use_llm: Whether to use LLM for custom questions.

    Returns:
        List of QAResponse objects, one per question.
    """
    responses = []
    for question in questions:
        resp = _answer_single(question, job, profile_data, qa_entries, use_llm)
        responses.append(resp)

    review_count = sum(1 for r in responses if r.needs_review)
    logger.info(
        "Answered %d questions (%d need review)",
        len(responses), review_count,
    )
    return responses


def _answer_single(
    question: str,
    job: RawJob,
    profile_data: dict[str, Any],
    qa_entries: list[dict] | None,
    use_llm: bool,
) -> QAResponse:
    """Answer a single question through the confidence cascade."""
    qtype = classify_question(question)

    # Step 1: Try QA bank exact/pattern match
    if qa_entries:
        match = _find_qa_match(question, qtype, qa_entries)
        if match:
            answer = _get_variant_answer(match, job)
            return QAResponse(
                question=question,
                question_type=qtype,
                answer=answer,
                confidence=match.get("confidence", "high"),
                needs_review=match.get("needs_review", False) or qtype in HIGH_RISK_TYPES,
                source="qa_bank",
            )

    # Step 2: Try template-based answer
    template_answer = _template_answer(qtype, profile_data, job)
    if template_answer:
        return QAResponse(
            question=question,
            question_type=qtype,
            answer=template_answer,
            confidence="medium",
            needs_review=qtype in HIGH_RISK_TYPES,
            source="template",
        )

    # Step 3: Try LLM generation
    if use_llm:
        try:
            llm_answer = _llm_answer(question, job, profile_data)
            return QAResponse(
                question=question,
                question_type=qtype,
                answer=llm_answer,
                confidence="low",
                needs_review=True,  # LLM answers always need review
                source="llm",
            )
        except Exception as e:
            logger.warning("LLM QA generation failed: %s", e)

    # Step 4: Fallback — flag for manual response
    return QAResponse(
        question=question,
        question_type=qtype,
        answer="",
        confidence="low",
        needs_review=True,
        source="none",
    )


# ---------------------------------------------------------------------------
# Question classification
# ---------------------------------------------------------------------------

_CLASSIFICATION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("authorization", re.compile(
        r"(?i)(authorized|authorization|eligible|legally).*(work|employ)",
    )),
    ("sponsorship", re.compile(
        r"(?i)(sponsor|visa|work\s*permit|immigration)",
    )),
    ("experience_years", re.compile(
        r"(?i)(how\s+many\s+years|years?\s+of\s+experience|experience\s+level)",
    )),
    ("salary", re.compile(
        r"(?i)(salary|compensation|pay|wage|expected\s+rate|desired\s+pay)",
    )),
    ("start_date", re.compile(
        r"(?i)(start\s*date|when.*start|available.*start|earliest.*start|availability)",
    )),
    ("why_company", re.compile(
        r"(?i)(why.*(?:this|our)\s+company|why.*(?:join|work\s+(?:at|for|with)))",
    )),
    ("why_role", re.compile(
        r"(?i)(why.*(?:this|the)\s+(?:role|position)|interest.*(?:role|position))",
    )),
    ("strengths", re.compile(
        r"(?i)(strength|what.*good\s+at|superpower|best\s+qualit)",
    )),
    ("weaknesses", re.compile(
        r"(?i)(weakness|area.*improve|challenge.*face|biggest\s+(?:weakness|challenge))",
    )),
]


def classify_question(question: str) -> str:
    """Classify a question into a known type."""
    for qtype, pattern in _CLASSIFICATION_PATTERNS:
        if pattern.search(question):
            return qtype
    return "custom"


# ---------------------------------------------------------------------------
# QA bank matching
# ---------------------------------------------------------------------------

def _find_qa_match(
    question: str,
    qtype: str,
    qa_entries: list[dict],
) -> dict | None:
    """Find best QA bank match by type + word overlap."""
    q_words = set(question.lower().split())

    # First try type-specific matches
    typed = [e for e in qa_entries if e.get("question_type") == qtype]
    match = _best_overlap_match(typed, q_words)
    if match:
        return match

    # Then try all entries
    return _best_overlap_match(qa_entries, q_words)


def _best_overlap_match(entries: list[dict], q_words: set[str]) -> dict | None:
    """Return entry with highest pattern word overlap."""
    best = None
    best_score = 0

    for entry in entries:
        pattern = (entry.get("question_pattern") or "").lower()
        if not pattern:
            continue
        overlap = len(set(pattern.split()) & q_words)
        if overlap > best_score:
            best_score = overlap
            best = entry

    return best if best_score > 0 else None


def _get_variant_answer(entry: dict, job: RawJob) -> str:
    """Get answer with geography/role-type variant if available."""
    variants = entry.get("variants") or {}

    # Infer geography from job location
    location = (job.location or "").lower()
    geo = None
    if any(w in location for w in ("canada", "vancouver", "toronto", "montreal")):
        geo = "Canada"
    elif any(w in location for w in ("us", "united states", "usa")):
        geo = "US"

    if geo and "by_geography" in variants:
        variant = variants["by_geography"].get(geo)
        if variant:
            return variant

    # Role type variant
    role = job.employment_type or ""
    if role and "by_role_type" in variants:
        variant = variants["by_role_type"].get(role)
        if variant:
            return variant

    return entry.get("canonical_answer", "")


# ---------------------------------------------------------------------------
# Template-based answers
# ---------------------------------------------------------------------------

def _template_answer(
    qtype: str,
    profile_data: dict[str, Any],
    job: RawJob,
) -> str | None:
    """Generate an answer from a template for known question types."""
    identity = profile_data.get("identity", {})

    if qtype == "authorization":
        # Authorization is jurisdiction-sensitive — always flag for review
        # rather than auto-generating a potentially incorrect answer
        return None

    if qtype == "sponsorship":
        # Sponsorship is high-risk — always flag for review
        return None

    if qtype == "experience_years":
        # Calculate from work experiences
        exps = profile_data.get("work_experiences", [])
        total = _estimate_experience_years(exps)
        if total >= 0:
            return f"I have approximately {total} year{'s' if total != 1 else ''} of relevant experience."
        return None

    if qtype == "start_date":
        return "I am available to start immediately or at a mutually convenient date."

    return None


def _estimate_experience_years(experiences: list[dict]) -> int:
    """Estimate total experience years from work history using month precision.

    Merges overlapping periods to avoid double-counting.
    """
    from datetime import datetime

    # Collect (start_month, end_month) intervals
    intervals: list[tuple[int, int]] = []
    now_month = datetime.now().year * 12 + datetime.now().month

    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        start = exp.get("start_date", "")
        end = exp.get("end_date", "")
        if not start:
            continue
        try:
            parts = start.split("-")
            start_m = int(parts[0]) * 12 + int(parts[1]) if len(parts) >= 2 else int(parts[0]) * 12 + 1
            if end and end != "Present":
                eparts = end.split("-")
                end_m = int(eparts[0]) * 12 + int(eparts[1]) if len(eparts) >= 2 else int(eparts[0]) * 12 + 12
            else:
                end_m = now_month
            intervals.append((start_m, end_m))
        except (ValueError, IndexError):
            pass

    if not intervals:
        return 0

    # Merge overlapping intervals
    intervals.sort()
    merged: list[tuple[int, int]] = [intervals[0]]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    total_months = sum(end - start for start, end in merged)
    return max(0, total_months // 12)


# ---------------------------------------------------------------------------
# LLM-generated answers
# ---------------------------------------------------------------------------

_QA_SYSTEM = """You are answering a job application question on behalf of an applicant.

Rules:
- Answer concisely (1-3 sentences for short-answer, up to 150 words for open-ended)
- Only reference facts from the provided applicant profile
- Do NOT fabricate experiences, skills, or achievements
- Be professional and confident
- If the question is about a specific technology and the applicant knows it, mention it
- Output ONLY the answer text, nothing else"""


def _llm_answer(
    question: str,
    job: RawJob,
    profile_data: dict[str, Any],
) -> str:
    """Generate an answer using LLM."""
    from src.utils.llm import claude_generate

    identity = profile_data.get("identity", {})
    skills = profile_data.get("skills", {})

    skill_list = []
    for category, items in skills.items():
        if isinstance(items, list) and items:
            skill_list.extend(items[:5])

    prompt = f"""Answer this application question:

<question>{question}</question>

<context>
Company: {job.company}
Role: {job.title}
Applicant: {identity.get('full_name', '')}
Skills: {', '.join(skill_list[:20])}
Education: {identity.get('education', 'Not specified')}
</context>

Answer the question directly and concisely."""

    result = claude_generate(prompt, system=_QA_SYSTEM, timeout=60)
    return result.strip()
