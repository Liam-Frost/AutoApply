"""Story bank management.

Stores reusable STAR-format stories (Situation, Action, Result) for interviews
and application questions like "why this company" or "tell me about a challenge."
"""

from __future__ import annotations

import logging
from typing import Any

import yaml
from sqlalchemy.orm import Session

from src.core.models import ApplicantProfile

logger = logging.getLogger("autoapply.memory.story_bank")

STORY_SECTION = "story_bank"


def ingest_stories(session: Session, profile_data: dict[str, Any]) -> int:
    """Load stories from profile data into the DB."""
    stories = profile_data.get("story_bank", [])
    if not stories:
        logger.info("No stories found in profile data")
        return 0

    # Remove existing story bank record
    session.query(ApplicantProfile).filter_by(section=STORY_SECTION).delete()

    record = ApplicantProfile(
        section=STORY_SECTION,
        content={"stories": stories},
        tags=_extract_story_tags(stories),
    )
    session.add(record)
    session.commit()

    logger.info("Ingested %d stories", len(stories))
    return len(stories)


def get_stories(session: Session, theme: str | None = None) -> list[dict]:
    """Retrieve stories, optionally filtered by theme."""
    record = session.query(ApplicantProfile).filter_by(section=STORY_SECTION).first()
    if record is None:
        return []

    stories = record.content.get("stories", [])
    if theme:
        stories = [s for s in stories if s.get("theme") == theme]
    return stories


def get_stories_for_context(session: Session, applicable_to: str) -> list[dict]:
    """Find stories applicable to a given context (e.g., 'backend_roles', 'startup')."""
    record = session.query(ApplicantProfile).filter_by(section=STORY_SECTION).first()
    if record is None:
        return []

    stories = record.content.get("stories", [])
    return [
        s for s in stories
        if applicable_to in s.get("applicable_to", [])
    ]


def _extract_story_tags(stories: list[dict]) -> list[str]:
    """Extract unique tags from all stories."""
    tags = set()
    for story in stories:
        if isinstance(story, dict):
            if story.get("theme"):
                tags.add(story["theme"])
            tags.update(story.get("applicable_to", []))
    return list(tags)
