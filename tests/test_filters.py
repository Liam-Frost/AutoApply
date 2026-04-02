"""Tests for src.intake.filters — job filter engine."""

import re
from pathlib import Path

import pytest

from src.intake.filters import (
    JobFilter,
    LocationRule,
    _infer_work_mode,
    load_filter_profiles,
)
from src.intake.schema import JobRequirements, RawJob


def _make_job(**overrides) -> RawJob:
    """Create a RawJob with sensible defaults, overriding as needed."""
    defaults = {
        "source": "greenhouse",
        "source_id": "123",
        "company": "TestCo",
        "title": "Software Engineering Intern",
        "location": "Vancouver, BC",
        "employment_type": "internship",
        "seniority": "internship",
        "description": "We are looking for a software engineering intern.",
        "ats_type": "greenhouse",
    }
    defaults.update(overrides)
    return RawJob(**defaults)


class TestInferWorkMode:
    def test_remote(self):
        assert _infer_work_mode("remote", "", "") == "remote"

    def test_hybrid(self):
        assert _infer_work_mode("toronto - hybrid", "", "") == "hybrid"

    def test_onsite(self):
        assert _infer_work_mode("on-site in sf", "", "") == "onsite"

    def test_location_with_no_keywords(self):
        assert _infer_work_mode("new york, ny", "", "") == "onsite"

    def test_empty(self):
        assert _infer_work_mode("", "", "") == "unknown"

    def test_remote_in_title(self):
        assert _infer_work_mode("", "software intern (remote)", "") == "remote"


class TestJobFilterTitle:
    def test_include_match(self):
        f = JobFilter(title_include=["intern", "software"])
        job = _make_job(title="Software Engineering Intern")
        assert f._passes(job)

    def test_include_no_match(self):
        f = JobFilter(title_include=["manager"])
        job = _make_job(title="Software Engineering Intern")
        assert not f._passes(job)

    def test_exclude_match(self):
        f = JobFilter(title_exclude=["manager"])
        job = _make_job(title="Engineering Manager")
        assert not f._passes(job)

    def test_no_keywords_passes_all(self):
        f = JobFilter()
        job = _make_job(title="Anything Goes")
        assert f._passes(job)


class TestJobFilterEmploymentType:
    def test_match(self):
        f = JobFilter(employment_types=["internship"])
        assert f._passes(_make_job(employment_type="internship"))

    def test_no_match(self):
        f = JobFilter(employment_types=["internship"])
        assert not f._passes(_make_job(employment_type="fulltime"))

    def test_unknown_passes(self):
        f = JobFilter(employment_types=["internship"])
        assert f._passes(_make_job(employment_type="unknown"))


class TestJobFilterLocation:
    def test_vancouver_onsite(self):
        f = JobFilter(locations=[
            LocationRule(name="vancouver", work_modes=["remote", "hybrid", "onsite"]),
        ])
        job = _make_job(location="Vancouver, BC")
        assert f._passes(job)

    def test_us_remote_only_rejects_onsite(self):
        f = JobFilter(locations=[
            LocationRule(name="united states", work_modes=["remote"]),
        ])
        job = _make_job(location="United States - New York")
        assert not f._passes(job)  # inferred onsite

    def test_us_remote_passes(self):
        f = JobFilter(locations=[
            LocationRule(name="united states", work_modes=["remote"]),
        ])
        job = _make_job(location="United States - Remote")
        assert f._passes(job)

    def test_no_location_rules_passes(self):
        f = JobFilter()
        assert f._passes(_make_job(location="Anywhere"))

    def test_toronto_hybrid(self):
        f = JobFilter(locations=[
            LocationRule(name="toronto", work_modes=["hybrid"]),
        ])
        job = _make_job(location="Toronto, ON - Hybrid")
        assert f._passes(job)


class TestJobFilterDescription:
    def test_exclude_canadian_pr(self):
        f = JobFilter(description_exclude_patterns=[
            re.compile(r"(?i)canadian\s+permanent\s+residen"),
        ])
        job = _make_job(description="Must be a Canadian permanent resident.")
        assert not f._passes(job)

    def test_no_pattern_passes(self):
        f = JobFilter()
        job = _make_job(description="Open to all candidates.")
        assert f._passes(job)


class TestJobFilterExperience:
    def test_under_max(self):
        f = JobFilter(max_experience_years=3)
        job = _make_job()
        job.requirements = JobRequirements(experience_years_min=1)
        assert f._passes(job)

    def test_over_max(self):
        f = JobFilter(max_experience_years=3)
        job = _make_job()
        job.requirements = JobRequirements(experience_years_min=5)
        assert not f._passes(job)

    def test_none_passes(self):
        f = JobFilter(max_experience_years=3)
        job = _make_job()
        assert f._passes(job)


class TestApply:
    def test_filters_batch(self):
        f = JobFilter(
            title_include=["intern"],
            employment_types=["internship"],
        )
        jobs = [
            _make_job(title="Software Intern", employment_type="internship"),
            _make_job(title="Senior Engineer", employment_type="fulltime"),
            _make_job(title="Data Intern", employment_type="internship"),
        ]
        matched = f.apply(jobs)
        assert len(matched) == 2
        assert all("intern" in j.title.lower() for j in matched)


class TestLoadFilterProfiles:
    def test_loads_real_config(self):
        config_path = Path("config/filters.yaml")
        if not config_path.exists():
            pytest.skip("config/filters.yaml not found")
        profiles = load_filter_profiles(config_path)
        assert "default" in profiles
        p = profiles["default"]
        assert len(p.locations) > 0
        assert len(p.title_include) > 0

    def test_missing_file(self):
        profiles = load_filter_profiles(Path("/nonexistent/filters.yaml"))
        assert profiles == {}
