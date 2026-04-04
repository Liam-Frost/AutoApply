"""Generic job filter engine.

Loads filter profiles from YAML and applies them to RawJob lists.
Each profile defines AND-combined criteria; within each criterion items are OR'd.

Usage:
    from src.intake.filters import JobFilter, load_filter_profiles

    profiles = load_filter_profiles(Path("config/filters.yaml"))
    filt = profiles["default"]
    matched = filt.apply(jobs)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from src.intake.schema import EmploymentType, RawJob, SeniorityLevel

logger = logging.getLogger("autoapply.intake.filters")


@dataclass
class LocationRule:
    """A location filter entry: name substring + allowed work modes."""

    name: str  # case-insensitive substring match
    work_modes: list[str] = field(default_factory=lambda: ["remote", "hybrid", "onsite"])


@dataclass
class JobFilter:
    """Filter profile — all criteria are AND'd; items within each are OR'd."""

    name: str = "default"
    description: str = ""
    locations: list[LocationRule] = field(default_factory=list)
    employment_types: list[EmploymentType] = field(default_factory=list)
    seniority: list[SeniorityLevel] = field(default_factory=list)
    title_include: list[str] = field(default_factory=list)
    title_exclude: list[str] = field(default_factory=list)
    description_exclude_patterns: list[re.Pattern] = field(default_factory=list)
    max_experience_years: int | None = None

    def apply(self, jobs: list[RawJob]) -> list[RawJob]:
        """Return jobs that pass all filter criteria."""
        matched = []
        for job in jobs:
            if self._passes(job):
                matched.append(job)
        logger.info(
            "Filter '%s': %d/%d jobs passed",
            self.name,
            len(matched),
            len(jobs),
        )
        return matched

    def _passes(self, job: RawJob) -> bool:
        """Check if a single job passes all criteria."""
        if not self._check_title(job):
            return False
        if not self._check_employment_type(job):
            return False
        if not self._check_seniority(job):
            return False
        if not self._check_location(job):
            return False
        if not self._check_description_exclusions(job):
            return False
        if not self._check_experience(job):
            return False
        return True

    def _check_title(self, job: RawJob) -> bool:
        title_lower = job.title.lower()

        # Exclude check first
        if self.title_exclude:
            for kw in self.title_exclude:
                if kw.lower() in title_lower:
                    return False

        # Include check: must match at least one
        if self.title_include:
            return any(kw.lower() in title_lower for kw in self.title_include)

        return True

    def _check_employment_type(self, job: RawJob) -> bool:
        if not self.employment_types:
            return True
        # Allow "unknown" through if we can't determine type
        if job.employment_type == "unknown":
            return True
        return job.employment_type in self.employment_types

    def _check_seniority(self, job: RawJob) -> bool:
        if not self.seniority:
            return True
        if job.seniority == "unknown":
            return True
        return job.seniority in self.seniority

    def _check_location(self, job: RawJob) -> bool:
        if not self.locations:
            return True

        loc = (job.location or "").lower()
        title_lower = job.title.lower()
        desc_lower = (job.description or "").lower()[:500]  # first 500 chars

        # Determine the job's work mode from available signals
        work_mode = _infer_work_mode(loc, title_lower, desc_lower)

        # Check if any location rule matches
        for rule in self.locations:
            name_lower = rule.name.lower()

            # "remote" as location name is special: matches any job tagged remote
            if name_lower == "remote":
                if work_mode == "remote":
                    return True
                continue

            # Substring match on location field
            if name_lower in loc:
                if not rule.work_modes or work_mode in rule.work_modes:
                    return True

        return False

    def _check_description_exclusions(self, job: RawJob) -> bool:
        if not self.description_exclude_patterns:
            return True
        text = job.description or ""
        if not text:
            return True
        for pat in self.description_exclude_patterns:
            if pat.search(text):
                logger.debug("Job '%s' excluded by pattern: %s", job.title, pat.pattern)
                return False
        return True

    def _check_experience(self, job: RawJob) -> bool:
        if self.max_experience_years is None:
            return True
        min_yrs = job.requirements.experience_years_min
        if min_yrs is not None and min_yrs > self.max_experience_years:
            return False
        return True


def _infer_work_mode(location: str, title: str, desc_snippet: str) -> str:
    """Infer work mode (remote/hybrid/onsite) from job signals.

    Returns one of: "remote", "hybrid", "onsite", "unknown".
    """
    combined = f"{location} {title} {desc_snippet}"

    if any(kw in combined for kw in ("hybrid",)):
        return "hybrid"
    if any(kw in combined for kw in ("remote", "work from home", "wfh", "anywhere")):
        return "remote"
    if any(kw in combined for kw in ("on-site", "onsite", "in-office", "in office")):
        return "onsite"

    # If location is set but none of the above matched, assume onsite
    if location.strip():
        return "onsite"

    return "unknown"


def load_filter_profiles(config_path: Path) -> dict[str, JobFilter]:
    """Load all filter profiles from YAML config.

    Returns dict mapping profile name to JobFilter instance.
    """
    if not config_path.exists():
        logger.warning("Filter config not found at %s", config_path)
        return {}

    with open(config_path) as f:
        data = yaml.safe_load(f) or {}

    profiles_data = data.get("profiles", {})
    profiles: dict[str, JobFilter] = {}

    for name, cfg in profiles_data.items():
        profiles[name] = _parse_profile(name, cfg)

    logger.info("Loaded %d filter profiles: %s", len(profiles), list(profiles.keys()))
    return profiles


def _parse_profile(name: str, cfg: dict) -> JobFilter:
    """Parse a single profile dict into a JobFilter."""
    locations = []
    for loc in cfg.get("locations", []):
        if isinstance(loc, str):
            locations.append(LocationRule(name=loc))
        elif isinstance(loc, dict):
            locations.append(
                LocationRule(
                    name=loc["name"],
                    work_modes=loc.get("work_modes", ["remote", "hybrid", "onsite"]),
                )
            )

    title_cfg = cfg.get("title_keywords", {})
    desc_patterns = []
    for pat_str in cfg.get("description_exclude_patterns", []):
        try:
            desc_patterns.append(re.compile(pat_str, re.IGNORECASE))
        except re.error as e:
            logger.warning("Invalid regex pattern '%s': %s", pat_str, e)

    return JobFilter(
        name=name,
        description=cfg.get("description", ""),
        locations=locations,
        employment_types=cfg.get("employment_types", []),
        seniority=cfg.get("seniority", []),
        title_include=title_cfg.get("include", []),
        title_exclude=title_cfg.get("exclude", []),
        description_exclude_patterns=desc_patterns,
        max_experience_years=cfg.get("max_experience_years"),
    )
