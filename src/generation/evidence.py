"""Evidence retrieval for JD-grounded resume and cover letter generation."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.generation.ir import ResumeBullet
from src.matching.semantic import compute_keyword_similarity


class EvidenceBullet(BaseModel):
    """A profile bullet scored against target JD tags."""

    source_id: str
    source_type: str
    source_entity: str
    text: str
    tags: list[str] = Field(default_factory=list)
    impact: str = ""
    tech_stack: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    score: float = 0.0
    semantic_score: float = 0.0
    vector_score: float = 0.0
    original_index: int = 0
    render_text: str | None = None

    def to_resume_bullet(self, text: str | None = None) -> ResumeBullet:
        rendered = text or self.render_text or self.text
        return ResumeBullet(
            text=rendered,
            source_id=self.source_id,
            source_type=self.source_type,  # type: ignore[arg-type]
            source_entity=self.source_entity,
            original_text=self.text,
            tags=self.tags,
            matched_keywords=self.matched_keywords,
            score=self.score + self.semantic_score + self.vector_score,
            source_confidence="user_verified",
        )


def collect_profile_evidence(profile_data: dict[str, Any]) -> list[EvidenceBullet]:
    """Flatten work and project bullets into evidence records with stable IDs."""
    evidence: list[EvidenceBullet] = []

    for item_index, exp in enumerate(profile_data.get("work_experiences", [])):
        if not isinstance(exp, dict):
            continue
        company = str(exp.get("company") or "Unknown")
        title = str(exp.get("title") or "")
        entity = f"{company} - {title}".strip(" -")
        base_id = f"experience:{_slugify(entity) or item_index}"
        evidence.extend(
            _collect_item_bullets(
                item=exp,
                source_type="experience",
                source_entity=entity,
                base_id=base_id,
                tech_stack=[],
            )
        )

    for item_index, project in enumerate(profile_data.get("projects", [])):
        if not isinstance(project, dict):
            continue
        name = str(project.get("name") or "Unknown")
        tech_stack = [str(value) for value in project.get("tech_stack", [])]
        base_id = f"project:{_slugify(name) or item_index}"
        evidence.extend(
            _collect_item_bullets(
                item=project,
                source_type="project",
                source_entity=name,
                base_id=base_id,
                tech_stack=tech_stack,
            )
        )

    return evidence


def select_relevant_evidence(
    jd_tags: list[str],
    profile_data: dict[str, Any],
    *,
    max_bullets_per_entity: int = 4,
    max_total: int | None = None,
    query_text: str | None = None,
    db_session: Session | None = None,
    query_embedding: list[float] | None = None,
) -> list[EvidenceBullet]:
    """Score and select evidence records for the target JD tags."""
    normalized_tags = [_normalize_tag(tag) for tag in jd_tags if _normalize_tag(tag)]
    tag_set = set(normalized_tags)
    evidence = collect_profile_evidence(profile_data)

    vector_scores = _pgvector_scores(db_session, query_embedding)
    scored = [_score_evidence(item, tag_set, query_text, vector_scores) for item in evidence]
    scored.sort(
        key=lambda item: (
            item.score + item.semantic_score + item.vector_score,
            -item.original_index,
        ),
        reverse=True,
    )

    selected: list[EvidenceBullet] = []
    per_entity: dict[str, int] = {}
    for item in scored:
        count = per_entity.get(item.source_entity, 0)
        if count >= max_bullets_per_entity:
            continue
        selected.append(item)
        per_entity[item.source_entity] = count + 1
        if max_total is not None and len(selected) >= max_total:
            break

    return selected


def evidence_by_entity(evidence: list[EvidenceBullet]) -> dict[str, list[EvidenceBullet]]:
    grouped: dict[str, list[EvidenceBullet]] = {}
    for item in evidence:
        grouped.setdefault(item.source_entity, []).append(item)
    return grouped


def _collect_item_bullets(
    *,
    item: dict[str, Any],
    source_type: str,
    source_entity: str,
    base_id: str,
    tech_stack: list[str],
) -> list[EvidenceBullet]:
    records: list[EvidenceBullet] = []
    for index, bullet in enumerate(item.get("bullets", [])):
        if not isinstance(bullet, dict) or not bullet.get("text"):
            continue
        tags = [str(tag) for tag in bullet.get("tags", [])]
        tags.extend(tech_stack)
        records.append(
            EvidenceBullet(
                source_id=f"{base_id}:bullet:{index}",
                source_type=source_type,
                source_entity=source_entity,
                text=str(bullet["text"]),
                tags=_dedupe([_normalize_tag(tag) for tag in tags if _normalize_tag(tag)]),
                impact=str(bullet.get("impact") or ""),
                tech_stack=tech_stack,
                original_index=index,
            )
        )
    return records


def _score_evidence(
    item: EvidenceBullet,
    tag_set: set[str],
    query_text: str | None,
    vector_scores: dict[str, float],
) -> EvidenceBullet:
    item_tags = {_normalize_tag(tag) for tag in item.tags}
    text_tokens = set(_tokenize(item.text))
    tech_tokens = {_normalize_tag(tag) for tag in item.tech_stack}

    direct_matches = item_tags & tag_set
    text_matches = text_tokens & tag_set
    tech_matches = tech_tokens & tag_set
    matched = _dedupe([*direct_matches, *tech_matches, *text_matches])

    score = len(direct_matches) * 2.0 + len(tech_matches) * 1.5 + len(text_matches)
    if item.impact:
        score += 0.25
    if not tag_set:
        score = 0.0
    semantic_score = compute_keyword_similarity(query_text or "", item.text) if query_text else 0.0
    vector_score = vector_scores.get(item.text, 0.0)

    return item.model_copy(
        update={
            "matched_keywords": matched,
            "score": score,
            "semantic_score": round(semantic_score, 4),
            "vector_score": round(vector_score, 4),
        }
    )


def _pgvector_scores(
    db_session: Session | None,
    query_embedding: list[float] | None,
    *,
    limit: int = 50,
) -> dict[str, float]:
    """Return text->similarity scores from pgvector when embeddings are available."""
    if db_session is None or not query_embedding:
        return {}
    try:
        from src.core.models import BulletPool

        distance = BulletPool.text_embedding.cosine_distance(query_embedding).label("distance")
        rows = (
            db_session.query(BulletPool.text, distance)
            .filter(BulletPool.text_embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
            .all()
        )
        return {text: max(0.0, 1.0 - float(distance)) for text, distance in rows if text}
    except Exception:
        return {}


def _normalize_tag(value: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", "_", value.lower().strip()).strip("_")


def _tokenize(value: str) -> list[str]:
    return [_normalize_tag(token) for token in re.findall(r"[A-Za-z][A-Za-z0-9+#.]+", value)]


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")[:80]


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
