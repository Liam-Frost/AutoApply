"""QA bank management.

Structured storage for common application quick questions and their answers.
Each question has a canonical answer, optional variants, confidence level,
and a flag for whether human review is needed.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from src.core.models import QABank

logger = logging.getLogger("autoapply.memory.qa_bank")

QUESTION_TYPES = {
    "authorization",
    "sponsorship",
    "experience_years",
    "salary",
    "start_date",
    "why_company",
    "why_role",
    "strengths",
    "weaknesses",
    "custom",
}


def ingest_qa_from_profile(session: Session, profile_data: dict[str, Any]) -> list[QABank]:
    """Load QA entries from profile data into the database."""
    qa_items = profile_data.get("qa_bank", [])
    if not qa_items:
        logger.info("No QA entries found in profile data")
        return []

    # Clear existing QA entries
    session.query(QABank).delete()

    records = []
    for item in qa_items:
        if not isinstance(item, dict):
            continue

        qtype = item.get("question_type", "custom")
        if qtype not in QUESTION_TYPES:
            logger.warning("Unknown question type '%s', defaulting to 'custom'", qtype)
            qtype = "custom"

        record = QABank(
            question_pattern=item.get("question_pattern", ""),
            question_type=qtype,
            canonical_answer=item.get("canonical_answer", ""),
            variants=item.get("variants"),
            confidence=item.get("confidence", "high"),
            needs_review=item.get("needs_review", False),
        )
        session.add(record)
        records.append(record)

    session.commit()
    logger.info("Ingested %d QA entries", len(records))
    return records


def find_answer(
    session: Session,
    question: str,
    question_type: str | None = None,
) -> QABank | None:
    """Find the best matching QA entry for a given question.

    Matching priority:
    1. Best keyword-overlap pattern match within the question_type pool (if provided)
    2. Best keyword-overlap pattern match across all entries
    3. First entry of the matching type (fallback with no question text)

    This avoids returning an arbitrary first-of-type entry when there are
    multiple QA entries with the same question_type (P2 fix).
    """
    query = session.query(QABank)
    candidates = query.filter(QABank.question_type == question_type).all() if question_type else query.all()

    if not candidates:
        return None

    question_lower = question.strip().lower()

    # If no question text given, return first candidate of the type
    if not question_lower:
        return candidates[0]

    best_match = None
    best_score = 0
    question_words = set(question_lower.split())

    for entry in candidates:
        pattern = (entry.question_pattern or "").lower()
        if not pattern:
            continue
        pattern_words = set(pattern.split())
        overlap = len(pattern_words & question_words)
        if overlap > best_score:
            best_score = overlap
            best_match = entry

    # If pattern matching found nothing, fall back to first candidate
    return best_match if best_match is not None else candidates[0]


def get_answer_text(
    entry: QABank,
    geography: str | None = None,
    role_type: str | None = None,
) -> str:
    """Get the appropriate answer text, checking variants first."""
    variants = entry.variants or {}

    # Check geography variant
    if geography and "by_geography" in variants:
        geo_variant = variants["by_geography"].get(geography)
        if geo_variant:
            return geo_variant

    # Check role type variant
    if role_type and "by_role_type" in variants:
        role_variant = variants["by_role_type"].get(role_type)
        if role_variant:
            return role_variant

    return entry.canonical_answer or ""


def get_all_qa(session: Session, question_type: str | None = None) -> list[QABank]:
    """Get all QA entries, optionally filtered by type."""
    query = session.query(QABank)
    if question_type:
        query = query.filter(QABank.question_type == question_type)
    return query.all()
