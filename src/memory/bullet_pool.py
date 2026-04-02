"""Resume bullet pool management.

Each bullet is a tagged, reusable resume line item.
Bullets are sourced from work experiences and projects in the applicant profile.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from src.core.models import BulletPool

logger = logging.getLogger("autoapply.memory.bullet_pool")


def ingest_bullets_from_profile(session: Session, profile_data: dict[str, Any]) -> list[BulletPool]:
    """Extract bullets from profile and store in bullet_pool table."""
    # Clear existing bullets
    session.query(BulletPool).delete()

    bullets = []

    # Extract from work experiences
    for exp in profile_data.get("work_experiences", []):
        if not isinstance(exp, dict):
            continue
        company = exp.get("company", "Unknown")
        title = exp.get("title", "")
        for bullet_data in exp.get("bullets", []):
            if not isinstance(bullet_data, dict):
                continue
            bullet = BulletPool(
                category="experience",
                source_entity=f"{company} - {title}",
                text=bullet_data["text"],
                tags=bullet_data.get("tags", []),
            )
            session.add(bullet)
            bullets.append(bullet)

    # Extract from projects
    for proj in profile_data.get("projects", []):
        if not isinstance(proj, dict):
            continue
        name = proj.get("name", "Unknown")
        for bullet_data in proj.get("bullets", []):
            if not isinstance(bullet_data, dict):
                continue
            bullet = BulletPool(
                category="project",
                source_entity=name,
                text=bullet_data["text"],
                tags=bullet_data.get("tags", []),
            )
            session.add(bullet)
            bullets.append(bullet)

    session.commit()
    logger.info("Ingested %d bullets into pool", len(bullets))
    return bullets


def query_bullets_by_tags(
    session: Session,
    tags: list[str],
    category: str | None = None,
    limit: int = 20,
) -> list[BulletPool]:
    """Find bullets matching any of the given tags, ordered by match count."""
    query = session.query(BulletPool)
    if category:
        query = query.filter(BulletPool.category == category)

    # Filter bullets that have overlap with requested tags
    query = query.filter(BulletPool.tags.overlap(tags))

    results = query.all()

    # Sort by number of matching tags (descending)
    tag_set = set(tags)
    results.sort(key=lambda b: len(tag_set & set(b.tags or [])), reverse=True)

    return results[:limit]


def get_all_bullets(session: Session, category: str | None = None) -> list[BulletPool]:
    """Get all bullets, optionally filtered by category."""
    query = session.query(BulletPool)
    if category:
        query = query.filter(BulletPool.category == category)
    return query.all()
