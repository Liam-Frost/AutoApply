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

    def test_extract_job_id_from_public_slug_url(self):
        from src.intake.linkedin import _extract_job_id_from_url

        url = (
            "https://www.linkedin.com/jobs/view/software-engineer-at-example-4370317193?position=1"
        )
        assert _extract_job_id_from_url(url) == "4370317193"

    def test_extract_job_id_from_current_job_param(self):
        from src.intake.linkedin import _extract_job_id_from_url

        url = "/jobs/search/?currentJobId=5555555555&keywords=swe"
        assert _extract_job_id_from_url(url) == "5555555555"

    def test_canonical_linkedin_job_url_prefers_view_path_for_current_job_links(self):
        from src.intake.linkedin import _canonical_linkedin_job_url

        url = "/jobs/collections/recommended/?currentJobId=4316203097&trackingId=test"

        assert (
            _canonical_linkedin_job_url("4316203097", url)
            == "https://www.linkedin.com/jobs/view/4316203097/"
        )

    def test_is_primary_apply_candidate_accepts_company_apply_link(self):
        from src.intake.linkedin import _is_primary_apply_candidate

        assert _is_primary_apply_candidate(
            text="Apply",
            aria_label="Apply on company website",
            href="https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fjobs.example.com%2F123",
        )

    def test_is_primary_apply_candidate_rejects_similar_jobs_links(self):
        from src.intake.linkedin import _is_primary_apply_candidate

        assert not _is_primary_apply_candidate(
            text="Full Stack Engineer Easy Apply",
            aria_label="",
            href="https://www.linkedin.com/jobs/collections/similar-jobs/?currentJobId=123",
        )

    def test_normalize_url_ignores_about_blank(self):
        from src.intake.linkedin import _normalize_url

        assert _normalize_url("about:blank") is None

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

    def test_unwrap_linkedin_safety_redirect(self):
        from src.intake.linkedin import _normalize_url

        wrapped = (
            "https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fjobs.ashbyhq.com%2FExample"
            "%2Fabc%2Fapplication%3Futm_source%3Dlinkedin&urlhash=test"
        )

        assert (
            _normalize_url(wrapped)
            == "https://jobs.ashbyhq.com/Example/abc/application?utm_source=linkedin"
        )

    def test_manual_apply_destination_rejects_linkedin_detail_url(self):
        from src.intake.linkedin import _manual_apply_destination_url

        assert (
            _manual_apply_destination_url(
                "https://www.linkedin.com/jobs/view/123/?refId=abc",
                source_url="https://www.linkedin.com/jobs/view/123/",
            )
            is None
        )

    def test_manual_apply_destination_rejects_linkedin_internal_apply_url(self):
        from src.intake.linkedin import _manual_apply_destination_url

        assert (
            _manual_apply_destination_url(
                "https://www.linkedin.com/jobs/apply/123/",
                source_url="https://www.linkedin.com/jobs/view/123/",
            )
            is None
        )

    def test_manual_apply_destination_unwraps_safety_redirect(self):
        from src.intake.linkedin import _manual_apply_destination_url

        wrapped = (
            "https://www.linkedin.com/safety/go/?url=https%3A%2F%2Fcareers.example.com"
            "%2Fjobs%2F123%3Futm_source%3Dlinkedin&urlhash=test"
        )

        assert (
            _manual_apply_destination_url(
                wrapped,
                source_url="https://www.linkedin.com/jobs/view/123/",
            )
            == "https://careers.example.com/jobs/123"
        )


class TestLinkedInSearchCache:
    def test_cache_hits_when_requested_pages_are_within_cached_range(self, tmp_path):
        from src.intake.schema import RawJob
        from src.intake.search_cache import (
            build_linkedin_search_cache_key,
            load_cached_linkedin_search,
            save_cached_linkedin_search,
        )

        job = RawJob(
            source="linkedin",
            source_id="1",
            company="Example",
            title="Software Engineer",
            location="California",
            ats_type="linkedin",
        )
        key = build_linkedin_search_cache_key(
            keywords=["software"],
            location="california",
            time_filter="month",
            experience_levels=None,
            job_types=None,
            enrich_details=False,
            max_detail_fetches=8,
            allow_public_fallback=False,
        )

        with patch("src.intake.search_cache.CACHE_DIR", tmp_path):
            save_cached_linkedin_search(key, [job], max_pages=20)

            cached = load_cached_linkedin_search(key, ttl_hours=24, requested_max_pages=10)
            missed = load_cached_linkedin_search(key, ttl_hours=24, requested_max_pages=25)

        assert cached is not None
        assert len(cached) == 1
        assert cached[0].title == "Software Engineer"
        assert missed is None

    def test_empty_results_are_not_cached(self, tmp_path):
        from src.intake.search_cache import (
            build_linkedin_search_cache_key,
            load_cached_linkedin_search,
            save_cached_linkedin_search,
        )

        key = build_linkedin_search_cache_key(
            keywords=["software"],
            location="toronto",
            time_filter="month",
            experience_levels=None,
            job_types=["internship"],
            enrich_details=True,
            max_detail_fetches=8,
            allow_public_fallback=False,
        )

        with patch("src.intake.search_cache.CACHE_DIR", tmp_path):
            save_cached_linkedin_search(key, [], max_pages=20)
            cached = load_cached_linkedin_search(key, ttl_hours=24, requested_max_pages=10)

        assert cached is None

    def test_cache_key_normalizes_order_insensitive_filters(self):
        from src.intake.search_cache import build_linkedin_search_cache_key

        first = build_linkedin_search_cache_key(
            keywords=["python", "django"],
            location="toronto",
            time_filter="month",
            experience_levels=["entry", "internship"],
            job_types=["fulltime", "internship"],
            enrich_details=True,
            max_detail_fetches=8,
            allow_public_fallback=False,
        )
        second = build_linkedin_search_cache_key(
            keywords=["django", "python"],
            location="toronto",
            time_filter="month",
            experience_levels=["internship", "entry"],
            job_types=["internship", "fulltime"],
            enrich_details=True,
            max_detail_fetches=8,
            allow_public_fallback=False,
        )

        assert first == second


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


class TestLinkedInGuestSearchParsing:
    def test_extract_public_job_cards(self):
        from src.intake.linkedin import _extract_public_job_cards

        html = """
        <ul class="jobs-search__results-list">
          <li>
            <div
              class="base-card base-search-card job-search-card"
              data-entity-urn="urn:li:jobPosting:4370317193"
            >
              <a
                class="base-card__full-link"
                href="https://www.linkedin.com/jobs/view/software-engineer-at-example-4370317193?position=1&amp;pageNum=0"
              >
                <span class="sr-only">Software Engineer</span>
              </a>
              <div class="base-search-card__info">
                <h3 class="base-search-card__title">Software Engineer</h3>
                <h4 class="base-search-card__subtitle">
                  <a class="hidden-nested-link" href="https://www.linkedin.com/company/example"
                    >Example Corp</a
                  >
                </h4>
                <div class="base-search-card__metadata">
                  <span class="job-search-card__location">Remote</span>
                </div>
              </div>
            </div>
          </li>
        </ul>
        """

        jobs = _extract_public_job_cards(html)

        assert len(jobs) == 1
        assert jobs[0].source == "linkedin"
        assert jobs[0].source_id == "4370317193"
        assert jobs[0].company == "Example Corp"
        assert jobs[0].title == "Software Engineer"
        assert jobs[0].location == "Remote"
        assert jobs[0].raw_data["search_mode"] == "public_guest"

    def test_normalize_linkedin_title_text_removes_duplicate_verification_suffix(self):
        from src.intake.linkedin import _normalize_linkedin_title_text

        value = (
            "Security Engineer (Bangkok Based, Relocation Support) "
            "Security Engineer (Bangkok Based, Relocation Support) with verification"
        )

        assert (
            _normalize_linkedin_title_text(value)
            == "Security Engineer (Bangkok Based, Relocation Support)"
        )

    def test_normalize_linkedin_title_text_keeps_short_repeated_titles(self):
        from src.intake.linkedin import _normalize_linkedin_title_text

        assert _normalize_linkedin_title_text("Intern Intern") == "Intern Intern"
        assert (
            _normalize_linkedin_title_text("Data Analyst Data Analyst")
            == "Data Analyst Data Analyst"
        )

    def test_normalize_linkedin_title_text_collapses_long_repeated_titles(self):
        from src.intake.linkedin import _normalize_linkedin_title_text

        assert (
            _normalize_linkedin_title_text(
                "Senior Software Engineer Senior Software Engineer"
            )
            == "Senior Software Engineer"
        )

    def test_normalize_job_description_text_strips_about_the_job_heading(self):
        from src.intake.linkedin import _normalize_job_description_text

        value = "About the job\nBuild software systems for analytics workflows."

        assert _normalize_job_description_text(value) == (
            "Build software systems for analytics workflows."
        )

    def test_normalize_job_description_text_returns_none_for_empty(self):
        from src.intake.linkedin import _normalize_job_description_text

        assert _normalize_job_description_text("   ") is None

    def test_page_has_no_results_text_detects_empty_search_message(self):
        from src.intake.linkedin import _page_has_no_results_text

        assert _page_has_no_results_text("No matching jobs found. Try changing your filters.")
        assert not _page_has_no_results_text("software in Toronto, Ontario, Canada 100+ results")

    def test_summarize_search_page_state_includes_key_fields(self):
        from src.intake.linkedin import _summarize_search_page_state

        summary = _summarize_search_page_state(
            {
                "status": "unknown",
                "card_count": 0,
                "title_count": 0,
                "pagination_text": "Page 5 of 8",
                "has_no_results_text": True,
            }
        )

        assert "status=unknown" in summary
        assert "cards=0" in summary
        assert "pagination=Page 5 of 8" in summary
        assert "no-results-text=true" in summary


class TestLinkedInKeywordPrecision:
    def test_keyword_precision_filter_removes_unrelated_jobs(self):
        from src.intake.schema import RawJob
        from src.intake.search import _apply_keyword_precision_filter

        jobs = [
            RawJob(
                source="linkedin",
                source_id="1",
                company="Example",
                title="Software Engineer",
                description="We are hiring a software engineer intern.",
                location="Vancouver, BC",
                ats_type="linkedin",
            ),
            RawJob(
                source="linkedin",
                source_id="2",
                company="TD",
                title="Customer Experience Associate - Mandarin language skills an asset",
                description="This branch role supports daily teller operations.",
                location="Vancouver, BC",
                ats_type="linkedin",
            ),
        ]

        matched = _apply_keyword_precision_filter(jobs, "Software")

        assert len(matched) == 1
        assert matched[0].title == "Software Engineer"

    def test_partition_jobs_by_title_keywords_only_keeps_title_hits(self):
        from src.intake.schema import RawJob
        from src.intake.search import _partition_jobs_by_title_keywords

        jobs = [
            RawJob(
                source="linkedin",
                source_id="1",
                company="Example",
                title="Software Engineer Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
            RawJob(
                source="linkedin",
                source_id="2",
                company="Example",
                title="Platform Developer Intern",
                description="Build software tooling after detail enrichment.",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
        ]

        title_matches, detail_candidates = _partition_jobs_by_title_keywords(jobs, "Software")

        assert [job.source_id for job in title_matches] == ["1"]
        assert [job.source_id for job in detail_candidates] == ["2"]

    @pytest.mark.asyncio
    async def test_search_linkedin_uses_title_then_description_keyword_matching(self):
        from src.intake.schema import RawJob
        from src.intake.search import search_linkedin

        initial_jobs = [
            RawJob(
                source="linkedin",
                source_id="1",
                company="Example",
                title="Software Engineer Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
            RawJob(
                source="linkedin",
                source_id="2",
                company="Example",
                title="Platform Engineering Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
            RawJob(
                source="linkedin",
                source_id="3",
                company="Example",
                title="Human Resources Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
        ]

        enriched_candidates = {
            "2": initial_jobs[1].model_copy(
                update={"description": "Build software tools for internal systems."}
            ),
            "3": initial_jobs[2].model_copy(
                update={"description": "Support recruiting and onboarding workflows."}
            ),
        }

        enrich_calls: list[list[str]] = []

        class FakeScraper:
            def __init__(self, *args, **kwargs):
                self.last_search_mode = "authenticated"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def search_jobs(self, **kwargs):
                return [job.model_copy(deep=True) for job in initial_jobs]

            async def enrich_jobs_with_details(self, jobs, max_detail_fetches=20, **kwargs):
                enrich_calls.append([job.source_id for job in jobs])
                enriched = []
                for job in jobs:
                    enriched.append(enriched_candidates.get(job.source_id, job))
                return enriched

        with patch(
            "src.intake.search._search_cache_settings",
            return_value={"enabled": False, "ttl_hours": 24},
        ):
            with patch("src.intake.linkedin.LinkedInScraper", FakeScraper):
                jobs = await search_linkedin(
                    keywords="software",
                    location="Toronto",
                    enrich_details=True,
                )

        assert [job.source_id for job in jobs] == ["1", "2"]
        assert enrich_calls == [["2", "3"], ["1"]]

    @pytest.mark.asyncio
    async def test_search_linkedin_limits_description_enrichment_to_max_detail_fetches(self):
        from src.intake.schema import RawJob
        from src.intake.search import search_linkedin

        initial_jobs = [
            RawJob(
                source="linkedin",
                source_id="1",
                company="Example",
                title="Platform Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
            RawJob(
                source="linkedin",
                source_id="2",
                company="Example",
                title="Backend Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
            RawJob(
                source="linkedin",
                source_id="3",
                company="Example",
                title="Systems Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
        ]

        enrichment_limits: list[int] = []

        class FakeScraper:
            def __init__(self, *args, **kwargs):
                self.last_search_mode = "authenticated"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def search_jobs(self, **kwargs):
                return [job.model_copy(deep=True) for job in initial_jobs]

            async def enrich_jobs_with_details(self, jobs, max_detail_fetches=20, **kwargs):
                enrichment_limits.append(max_detail_fetches)
                enriched = []
                for job in jobs[:max_detail_fetches]:
                    enriched.append(
                        job.model_copy(update={"description": "software platform engineering"})
                    )
                enriched.extend(jobs[max_detail_fetches:])
                return enriched

        with patch(
            "src.intake.search._search_cache_settings",
            return_value={"enabled": False, "ttl_hours": 24},
        ):
            with patch("src.intake.linkedin.LinkedInScraper", FakeScraper):
                jobs = await search_linkedin(
                    keywords="software",
                    location="Toronto",
                    enrich_details=True,
                    max_detail_fetches=2,
                )

        assert enrichment_limits == [2]
        assert [job.source_id for job in jobs] == ["1", "2"]

    @pytest.mark.asyncio
    async def test_search_linkedin_dedupes_after_description_keyword_matching(self):
        from src.intake.schema import RawJob
        from src.intake.search import search_linkedin

        initial_jobs = [
            RawJob(
                source="linkedin",
                source_id="1",
                company="Example",
                title="Platform Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
            RawJob(
                source="linkedin",
                source_id="2",
                company="Example",
                title="Platform Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
        ]

        class FakeScraper:
            def __init__(self, *args, **kwargs):
                self.last_search_mode = "authenticated"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def search_jobs(self, **kwargs):
                return [job.model_copy(deep=True) for job in initial_jobs]

            async def enrich_jobs_with_details(self, jobs, max_detail_fetches=20, **kwargs):
                enriched = []
                for job in jobs:
                    if job.source_id == "2":
                        enriched.append(
                            job.model_copy(update={"description": "software platform engineering"})
                        )
                    else:
                        enriched.append(job)
                return enriched

        with patch(
            "src.intake.search._search_cache_settings",
            return_value={"enabled": False, "ttl_hours": 24},
        ):
            with patch("src.intake.linkedin.LinkedInScraper", FakeScraper):
                jobs = await search_linkedin(
                    keywords="software",
                    location="Toronto",
                    enrich_details=True,
                )

        assert [job.source_id for job in jobs] == ["2"]

    @pytest.mark.asyncio
    async def test_search_linkedin_keeps_final_enrichment_order_for_title_matches(self):
        from src.intake.schema import RawJob
        from src.intake.search import search_linkedin

        initial_jobs = [
            RawJob(
                source="linkedin",
                source_id="1",
                company="Example",
                title="Software Engineer Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
            RawJob(
                source="linkedin",
                source_id="2",
                company="Example",
                title="Software Developer Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
            RawJob(
                source="linkedin",
                source_id="3",
                company="Example",
                title="Platform Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
        ]

        final_enrichment_batches: list[list[str]] = []

        class FakeScraper:
            def __init__(self, *args, **kwargs):
                self.last_search_mode = "authenticated"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def search_jobs(self, **kwargs):
                return [job.model_copy(deep=True) for job in initial_jobs]

            async def enrich_jobs_with_details(self, jobs, max_detail_fetches=20, **kwargs):
                if kwargs.get("delay_between_jobs") is False:
                    enriched = []
                    for job in jobs[:max_detail_fetches]:
                        if job.source_id == "3":
                            enriched.append(
                                job.model_copy(update={"description": "software platform systems"})
                            )
                        else:
                            enriched.append(job)
                    enriched.extend(jobs[max_detail_fetches:])
                    return enriched

                final_enrichment_batches.append(
                    [job.source_id for job in jobs[:max_detail_fetches]]
                )
                return jobs

        with patch(
            "src.intake.search._search_cache_settings",
            return_value={"enabled": False, "ttl_hours": 24},
        ):
            with patch("src.intake.linkedin.LinkedInScraper", FakeScraper):
                jobs = await search_linkedin(
                    keywords="software",
                    location="Toronto",
                    enrich_details=True,
                    max_detail_fetches=2,
                )

        assert [job.source_id for job in jobs] == ["1", "2", "3"]
        assert final_enrichment_batches == [["1", "2"]]

    @pytest.mark.asyncio
    async def test_search_linkedin_dedupes_without_keyword_filter(self):
        from src.intake.schema import RawJob
        from src.intake.search import search_linkedin

        initial_jobs = [
            RawJob(
                source="linkedin",
                source_id="1",
                company="Example",
                title="Software Engineer Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
            RawJob(
                source="linkedin",
                source_id="2",
                company="Example",
                title="Software Engineer Intern",
                location="Toronto, ON",
                ats_type="linkedin",
            ),
        ]

        class FakeScraper:
            def __init__(self, *args, **kwargs):
                self.last_search_mode = "authenticated"

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def search_jobs(self, **kwargs):
                return [job.model_copy(deep=True) for job in initial_jobs]

        with patch(
            "src.intake.search._search_cache_settings",
            return_value={"enabled": False, "ttl_hours": 24},
        ):
            with patch("src.intake.linkedin.LinkedInScraper", FakeScraper):
                jobs = await search_linkedin(
                    keywords="",
                    location="Toronto",
                    enrich_details=False,
                )

        assert [job.source_id for job in jobs] == ["1"]


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
        assert "1 with external apply links" in result.output


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
            if "company" in selector or "subtitle" in selector:
                return company_el
            elif "location" in selector or "metadata" in selector or "caption" in selector:
                return location_el
            elif "title" in selector or "link" in selector:
                return title_el
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
