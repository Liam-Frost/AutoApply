"""Greenhouse ATS scraper.

Uses Greenhouse's public Job Board API (no auth required):
  GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs
  GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{id}

Company tokens can be found in the URL of any Greenhouse job board:
  https://boards.greenhouse.io/stripe  → token = "stripe"
"""

from __future__ import annotations

import logging

from src.intake.base import BaseScraper, ScraperError
from src.intake.html_utils import strip_html
from src.intake.schema import RawJob, classify_employment_type, classify_seniority

logger = logging.getLogger("autoapply.intake.greenhouse")

BASE_URL = "https://boards-api.greenhouse.io/v1/boards"


class GreenhouseScraper(BaseScraper):
    """Scraper for Greenhouse job boards."""

    source_name = "greenhouse"

    def fetch_jobs(self, company_slug: str) -> list[RawJob]:
        """Fetch all open jobs for a company's Greenhouse board.

        Args:
            company_slug: The Greenhouse board token (e.g. "stripe", "airbnb").

        Returns:
            List of normalized RawJob objects.
        """
        url = f"{BASE_URL}/{company_slug}/jobs"
        params = {"content": "true"}  # include full description

        logger.info("Fetching Greenhouse jobs for '%s'", company_slug)

        try:
            data = self._get(url, params=params).json()
        except ScraperError:
            raise
        except Exception as e:
            raise ScraperError(
                f"Failed to parse Greenhouse response for {company_slug}: {e}"
            ) from e

        raw_jobs_list = data.get("jobs", [])
        if not isinstance(raw_jobs_list, list):
            raise ScraperError(f"Unexpected Greenhouse response shape for {company_slug}")

        jobs = []
        for item in raw_jobs_list:
            try:
                job = self._parse_job(company_slug, item)
                jobs.append(job)
            except Exception as e:
                logger.warning("Skipping malformed Greenhouse job %s: %s", item.get("id"), e)

        logger.info("Fetched %d jobs from Greenhouse/%s", len(jobs), company_slug)
        return jobs

    def fetch_job(self, company_slug: str, job_id: str) -> RawJob:
        """Fetch a single Greenhouse job posting."""
        url = f"{BASE_URL}/{company_slug}/jobs/{job_id}"
        params = {"content": "true"}

        logger.info("Fetching Greenhouse job %s/%s", company_slug, job_id)

        try:
            item = self._get(url, params=params).json()
        except ScraperError:
            raise
        except Exception as e:
            raise ScraperError(
                f"Failed to parse Greenhouse job {company_slug}/{job_id}: {e}"
            ) from e

        if not isinstance(item, dict) or not item.get("id"):
            raise ScraperError(f"Unexpected Greenhouse job response for {company_slug}/{job_id}")

        return self._parse_job(company_slug, item)

    def _parse_job(self, company_slug: str, item: dict) -> RawJob:
        """Convert a raw Greenhouse API job dict to RawJob."""
        job_id = str(item["id"])
        title = item.get("title", "").strip()

        # Location: Greenhouse returns a list of offices
        offices = item.get("offices", [])
        location = (
            offices[0].get("name", "")
            if offices and isinstance(offices[0], dict)
            else item.get("location", {}).get("name", "")
        )

        # Employment type from departments or metadata (Greenhouse doesn't always expose this)
        # Fall back to title-based inference
        employment_type = classify_employment_type(item.get("employment_type", "") or title)
        seniority = classify_seniority(title)

        # Description
        description_html = item.get("content", "")
        description = strip_html(description_html) if description_html else None

        # Application URL
        absolute_url = item.get("absolute_url", "")
        if not absolute_url:
            absolute_url = f"https://boards.greenhouse.io/{company_slug}/jobs/{job_id}"

        return RawJob(
            source="greenhouse",
            source_id=job_id,
            company=_infer_company_name(company_slug, item),
            title=title,
            location=location or None,
            employment_type=employment_type,
            seniority=seniority,
            description=description,
            application_url=absolute_url,
            ats_type="greenhouse",
            raw_data=item,
        )


def _infer_company_name(slug: str, item: dict) -> str:
    """Try to get a proper company name from the job data."""
    # Some Greenhouse responses include a company field
    if "company" in item and item["company"]:
        name = item["company"].get("name", "")
        if name:
            return name.strip()
    # Fall back to slug with basic formatting
    return slug.replace("-", " ").replace("_", " ").title()
