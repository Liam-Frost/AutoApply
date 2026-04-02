"""Applicant profile management.

Loads structured profile from YAML, stores in DB, supports querying by section.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.orm import Session

from src.core.models import ApplicantProfile

logger = logging.getLogger("autoapply.memory.profile")

VALID_SECTIONS = {"identity", "education", "work_experiences", "projects", "skills"}


def load_profile_yaml(path: Path) -> dict[str, Any]:
    """Load and validate an applicant profile YAML file."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"Profile YAML must be a mapping, got {type(data)}")

    missing = VALID_SECTIONS - set(data.keys())
    if missing:
        logger.warning("Profile missing sections: %s", missing)

    return data


def ingest_profile(session: Session, profile_data: dict[str, Any]) -> list[ApplicantProfile]:
    """Ingest profile data into the database, replacing existing records."""
    # Clear existing profile data
    session.query(ApplicantProfile).delete()

    records = []
    for section, content in profile_data.items():
        if section in ("story_bank", "qa_bank"):
            continue  # Handled by their own modules

        tags = _extract_tags(section, content)
        record = ApplicantProfile(
            section=section,
            content=content if isinstance(content, dict) else {"items": content},
            tags=tags,
        )
        session.add(record)
        records.append(record)

    session.commit()
    logger.info("Ingested %d profile sections", len(records))
    return records


def get_profile_section(session: Session, section: str) -> dict[str, Any] | None:
    """Retrieve a specific profile section from the database."""
    record = session.query(ApplicantProfile).filter_by(section=section).first()
    if record is None:
        return None
    return record.content


def get_full_profile(session: Session) -> dict[str, Any]:
    """Retrieve all profile sections as a unified dict."""
    records = session.query(ApplicantProfile).all()
    return {r.section: r.content for r in records}


def _extract_tags(section: str, content: Any) -> list[str]:
    """Extract tags from profile content for indexing."""
    tags = [section]

    if section == "skills" and isinstance(content, dict):
        for category, items in content.items():
            if isinstance(items, list):
                tags.extend(str(item).lower() for item in items)

    elif section == "education" and isinstance(content, list):
        for edu in content:
            if isinstance(edu, dict):
                if edu.get("field"):
                    tags.append(edu["field"].lower())
                for course in edu.get("relevant_courses", []):
                    if isinstance(course, dict):
                        tags.extend(course.get("tags", []))

    elif section in ("work_experiences", "projects") and isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                for bullet in item.get("bullets", []):
                    if isinstance(bullet, dict):
                        tags.extend(bullet.get("tags", []))

    return list(set(tags))
