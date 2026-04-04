"""Tests for Phase 6: LinkedIn scraper integration.

Tests LinkedIn utility functions, URL building, ATS detection, and CLI integration.
Browser-dependent tests use mocks to avoid needing a real LinkedIn session.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

# ──────────────────────────────────────────────
# URL Utility Tests
# ──────────────────────────────────────────────


class TestLinkedInURLUtils:
    """Test LinkedIn URL parsing and ATS detection utilities."""

    def test_extract_job_id_from_view_url(self):
        from src.intake.linkedin import _extract_job_id_from_url

        assert _extract_job_id_from_url("/jobs/view/1234567890/") == "1234567890"

    def test_extract_job_id_from_full_url(self):
        from src.intake.linkedin import _extract_job_id_from_url

        url = "https://www.linkedin.com/jobs/view/9876543210?refId=abc"
        assert _extract_job_id_from_url(url) == "9876543210"

    def test_extract_job_id_from_current_job_param(self):
        from src.intake.linkedin import _extract_job_id_from_url

        url = "/jobs/search/?currentJobId=5555555555&keywords=swe"
        assert _extract_job_id_from_url(url) == "5555555555"

    def test_extract_job_id_returns_none_for_invalid(self):
        from src.intake.linkedin import _extract_job_id_from_url

        assert _extract_job_id_from_url("/some/other/path") is None
        assert _extract_job_id_from_url("") is None

    def test_is_known_ats_url_greenhouse(self):
        from src.intake.linkedin import _is_known_ats_url

        assert _is_known_ats_url("https://boards.greenhouse.io/stripe/jobs/123")

    def test_is_known_ats_url_lever(self):
        from src.intake.linkedin import _is_known_ats_url

        assert _is_known_ats_url("https://jobs.lever.co/notion/abc-def")

    def test_is_known_ats_url_workday(self):
        from src.intake.linkedin import _is_known_ats_url

        assert _is_known_ats_url("https://company.myworkdayjobs.com/en-US/jobs/123")

    def test_is_known_ats_url_unknown(self):
        from src.intake.linkedin import _is_known_ats_url

        assert not _is_known_ats_url("https://www.google.com")
        assert not _is_known_ats_url("https://careers.company.com/apply")

    def test_detect_ats_type(self):
        from src.intake.linkedin import _detect_ats_type

        assert _detect_ats_type("https://boards.greenhouse.io/stripe") == "greenhouse"
        assert _detect_ats_type("https://jobs.lever.co/notion") == "lever"
        assert _detect_ats_type("https://company.myworkdayjobs.com/job") == "workday"
        assert _detect_ats_type("https://careers.example.com") == "company_site"

    def test_clean_tracking_url(self):
        from src.intake.linkedin import _clean_tracking_url

        url = "https://boards.greenhouse.io/stripe/jobs/123?utm_source=linkedin&utm_medium=job"
        assert _clean_tracking_url(url) == "https://boards.greenhouse.io/stripe/jobs/123"

    def test_clean_tracking_url_no_tracking(self):
        from src.intake.linkedin import _clean_tracking_url

        url = "https://boards.greenhouse.io/stripe/jobs/123"
        assert _clean_tracking_url(url) == url


# ──────────────────────────────────────────────
# Search URL Builder Tests
# ──────────────────────────────────────────────


class TestSearchURLBuilder:
    """Test LinkedIn search URL construction."""

    def _make_scraper(self):
        from src.intake.linkedin import LinkedInScraper

        scraper = LinkedInScraper.__new__(LinkedInScraper)
        return scraper

    def test_basic_search_url(self):
        scraper = self._make_scraper()
        url = scraper._build_search_url(keywords="software engineer")

        assert "keywords=software+engineer" in url
        assert "linkedin.com/jobs/search/" in url

    def test_search_url_with_location(self):
        scraper = self._make_scraper()
        url = scraper._build_search_url(
            keywords="data scientist",
            location="San Francisco",
        )

        assert "keywords=data+scientist" in url
        assert "location=San+Francisco" in url

    def test_search_url_with_time_filter(self):
        scraper = self._make_scraper()

        url_24h = scraper._build_search_url(keywords="swe", time_filter="24h")
        assert "f_TPR=r86400" in url_24h

        url_week = scraper._build_search_url(keywords="swe", time_filter="week")
        assert "f_TPR=r604800" in url_week

        url_month = scraper._build_search_url(keywords="swe", time_filter="month")
        assert "f_TPR=r2592000" in url_month

    def test_search_url_with_experience_levels(self):
        scraper = self._make_scraper()
        url = scraper._build_search_url(
            keywords="swe",
            experience_levels=["internship", "entry"],
        )
        assert "f_E=1%2C2" in url or "f_E=1,2" in url

    def test_search_url_with_job_types(self):
        scraper = self._make_scraper()
        url = scraper._build_search_url(
            keywords="swe",
            job_types=["fulltime", "internship"],
        )
        assert "f_JT=" in url

    def test_search_url_sort_by_date(self):
        scraper = self._make_scraper()
        url = scraper._build_search_url(keywords="swe")
        assert "sortBy=DD" in url


# ──────────────────────────────────────────────
# Schema Integration Tests
# ──────────────────────────────────────────────


class TestLinkedInSchemaIntegration:
    """Test that LinkedIn jobs conform to the existing RawJob schema."""

    def test_linkedin_ats_type_in_schema(self):
        from src.intake.schema import RawJob

        job = RawJob(
            source="linkedin",
            source_id="1234567890",
            company="Test Corp",
            title="Software Engineer Intern",
            ats_type="linkedin",
        )
        assert job.source == "linkedin"
        assert job.ats_type == "linkedin"

    def test_linkedin_job_dedup_key(self):
        from src.intake.schema import RawJob

        job = RawJob(
            source="linkedin",
            source_id="123",
            company="Test Corp",
            title="SWE",
        )
        key = job.dedup_key()
        assert "linkedin" in key
        assert "123" in key

    def test_linkedin_job_with_ats_redirect(self):
        """Test that a LinkedIn job can be redirected to an external ATS."""
        from src.intake.schema import RawJob

        job = RawJob(
            source="linkedin",
            source_id="123",
            company="Stripe",
            title="Software Engineer Intern",
            application_url="https://boards.greenhouse.io/stripe/jobs/456",
            ats_type="greenhouse",
            raw_data={"linkedin_url": "https://www.linkedin.com/jobs/view/123"},
        )
        assert job.ats_type == "greenhouse"
        assert "greenhouse.io" in job.application_url
        assert "linkedin.com" in job.raw_data["linkedin_url"]


# ──────────────────────────────────────────────
# CLI Integration Tests
# ──────────────────────────────────────────────


class TestLinkedInCLI:
    """Test CLI integration for LinkedIn search."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_search_help_shows_linkedin_options(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["search", "--help"])
        assert result.exit_code == 0
        assert "--source" in result.output
        assert "linkedin" in result.output
        assert "--keyword" in result.output
        assert "--location" in result.output
        assert "--time-filter" in result.output

    def test_linkedin_search_requires_keyword(self, runner):
        from src.cli.main import cli

        result = runner.invoke(cli, ["search", "--source", "linkedin"])
        assert result.exit_code == 1
        assert "--keyword" in result.output

    @patch("src.cli.cmd_search.search_jobs_usecase", new_callable=AsyncMock)
    def test_linkedin_search_calls_scraper(self, mock_search, runner):
        mock_search.return_value = {
            "search_params": {"keyword": "software engineer intern"},
            "jobs": [
                {
                    "source": "linkedin",
                    "source_id": "111",
                    "company": "TestCo",
                    "title": "SWE Intern",
                    "location": "Remote",
                    "ats_type": "linkedin",
                    "employment_type": "unknown",
                    "application_url": None,
                }
            ],
            "errors": [],
            "error": None,
            "counts": {"ats": 0, "linkedin": 1, "linkedin_external_ats": 0, "total": 1},
            "scored": False,
        }

        from src.cli.main import cli

        result = runner.invoke(
            cli,
            [
                "search",
                "--source",
                "linkedin",
                "--keyword",
                "software engineer intern",
                "--location",
                "United States",
            ],
        )
        assert result.exit_code == 0
        assert "LinkedIn: 1 jobs found" in result.output
        mock_search.assert_called_once()

    @patch("src.cli.cmd_search.search_jobs_usecase", new_callable=AsyncMock)
    def test_linkedin_search_shows_ats_redirect_count(self, mock_search, runner):
        mock_search.return_value = {
            "search_params": {"keyword": "intern"},
            "jobs": [
                {
                    "source": "linkedin",
                    "source_id": "111",
                    "company": "Stripe",
                    "title": "SWE Intern",
                    "location": None,
                    "ats_type": "greenhouse",
                    "employment_type": "unknown",
                    "application_url": None,
                },
                {
                    "source": "linkedin",
                    "source_id": "222",
                    "company": "TestCo",
                    "title": "PM Intern",
                    "location": None,
                    "ats_type": "linkedin",
                    "employment_type": "unknown",
                    "application_url": None,
                },
            ],
            "errors": [],
            "error": None,
            "counts": {"ats": 0, "linkedin": 2, "linkedin_external_ats": 1, "total": 2},
            "scored": False,
        }

        from src.cli.main import cli

        result = runner.invoke(
            cli,
            [
                "search",
                "--source",
                "linkedin",
                "--keyword",
                "intern",
            ],
        )
        assert result.exit_code == 0
        assert "1 with external ATS links" in result.output


# ──────────────────────────────────────────────
# Async Scraper Tests (with mocked Playwright)
# ──────────────────────────────────────────────


class TestLinkedInScraperMocked:
    """Test scraper logic with mocked Playwright."""

    def test_parse_job_card_extracts_fields(self):
        """Test that _parse_job_card correctly extracts job data from a card element."""
        from src.intake.linkedin import LinkedInScraper

        scraper = LinkedInScraper.__new__(LinkedInScraper)

        # Create mock card element
        card = AsyncMock()

        # Mock title element
        title_el = AsyncMock()
        title_el.inner_text = AsyncMock(return_value="  Software Engineer Intern  ")
        title_el.get_attribute = AsyncMock(return_value="/jobs/view/999888777/")

        # Mock company element
        company_el = AsyncMock()
        company_el.inner_text = AsyncMock(return_value="Google")

        # Mock location element
        location_el = AsyncMock()
        location_el.inner_text = AsyncMock(return_value="Mountain View, CA")

        def mock_query_selector(selector):
            if "title" in selector or "link" in selector:
                return title_el
            elif "company" in selector:
                return company_el
            elif "location" in selector or "metadata" in selector:
                return location_el
            return None

        card.query_selector = AsyncMock(side_effect=mock_query_selector)

        job = asyncio.run(scraper._parse_job_card(card))

        assert job is not None
        assert job.source_id == "999888777"
        assert job.title == "Software Engineer Intern"
        assert job.company == "Google"
        assert job.location == "Mountain View, CA"
        assert job.source == "linkedin"

    def test_parse_job_card_returns_none_without_title(self):
        from src.intake.linkedin import LinkedInScraper

        scraper = LinkedInScraper.__new__(LinkedInScraper)

        card = AsyncMock()
        card.query_selector = AsyncMock(return_value=None)

        job = asyncio.run(scraper._parse_job_card(card))
        assert job is None

    def test_search_linkedin_sync_wrapper(self):
        """Test that the sync wrapper correctly invokes the async function."""
        from src.intake.search import search_linkedin_sync

        with patch("src.intake.search.search_linkedin") as mock_async:
            mock_async.return_value = []
            result = search_linkedin_sync(keywords="test")
            assert result == []


# ──────────────────────────────────────────────
# Filter Mapping Tests
# ──────────────────────────────────────────────


class TestLinkedInFilterMaps:
    """Test that LinkedIn filter constants are correctly defined."""

    def test_time_filter_map_values(self):
        from src.intake.linkedin import TIME_FILTER_MAP

        assert "24h" in TIME_FILTER_MAP
        assert "week" in TIME_FILTER_MAP
        assert "month" in TIME_FILTER_MAP
        # Verify they're valid LinkedIn f_TPR values
        for v in TIME_FILTER_MAP.values():
            assert v.startswith("r")
            assert v[1:].isdigit()

    def test_experience_level_map(self):
        from src.intake.linkedin import EXPERIENCE_LEVEL_MAP

        assert "internship" in EXPERIENCE_LEVEL_MAP
        assert "entry" in EXPERIENCE_LEVEL_MAP

    def test_job_type_map(self):
        from src.intake.linkedin import JOB_TYPE_MAP

        assert "fulltime" in JOB_TYPE_MAP
        assert "internship" in JOB_TYPE_MAP
        assert "contract" in JOB_TYPE_MAP
