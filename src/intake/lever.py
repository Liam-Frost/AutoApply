"""Lever ATS scraper.

Uses Lever's public postings API (no auth required):
  GET https://api.lever.co/v0/postings/{company}
  GET https://api.lever.co/v0/postings/{company}/{id}

Company slugs match the Lever job board URL:
  https://jobs.lever.co/linear  → slug = "linear"
"""

from __future__ import annotations

import logging

from src.intake.base import BaseScraper, ScraperError
from src.intake.html_utils import strip_html
from src.intake.schema import RawJob, classify_employment_type, classify_seniority

logger = logging.getLogger("autoapply.intake.lever")

BASE_URL = "https://api.lever.co/v0/postings"


class LeverScraper(BaseScraper):
    """Scraper for Lever job boards."""

    source_name = "lever"

    def fetch_jobs(self, company_slug: str) -> list[RawJob]:
        """Fetch all open jobs for a company's Lever board.

        Args:
            company_slug: The Lever company slug (e.g. "linear", "notion").

        Returns:
            List of normalized RawJob objects.
        """
        url = f"{BASE_URL}/{company_slug}"
        params = {"mode": "json"}  # structured JSON mode

        logger.info("Fetching Lever jobs for '%s'", company_slug)

        try:
            resp = self._get(url, params=params)
            raw_list = resp.json()
        except ScraperError:
            raise
        except Exception as e:
            raise ScraperError(f"Failed to parse Lever response for {company_slug}: {e}") from e

        if not isinstance(raw_list, list):
            raise ScraperError(f"Unexpected Lever response shape for {company_slug}: {type(raw_list)}")

        jobs = []
        for item in raw_list:
            try:
                job = self._parse_job(company_slug, item)
                jobs.append(job)
            except Exception as e:
                logger.warning("Skipping malformed Lever job %s: %s", item.get("id"), e)

        logger.info("Fetched %d jobs from Lever/%s", len(jobs), company_slug)
        return jobs

    def _parse_job(self, company_slug: str, item: dict) -> RawJob:
        """Convert a raw Lever API posting to RawJob."""
        source_id = item.get("id", "")
        text = item.get("text", "").strip()       # Lever's field for title
        title = text or item.get("title", "").strip()

        # Location
        location_data = item.get("categories", {})
        location = location_data.get("location", "") or item.get("workplaceType", "")

        # Commitment = employment type in Lever (Full-time, Internship, Part-time, etc.)
        commitment = location_data.get("commitment", "")
        employment_type = classify_employment_type(commitment or title)
        seniority = classify_seniority(title)

        # Description: Lever structures content as a list of sections
        description = _extract_lever_description(item)

        # Application URL
        apply_url = item.get("applyUrl", "") or item.get("hostedUrl", "")
        if not apply_url:
            apply_url = f"https://jobs.lever.co/{company_slug}/{source_id}"

        company_name = _infer_company_name(company_slug, item)

        return RawJob(
            source="lever",
            source_id=source_id,
            company=company_name,
            title=title,
            location=location or None,
            employment_type=employment_type,
            seniority=seniority,
            description=description,
            application_url=apply_url,
            ats_type="lever",
            raw_data=item,
        )


def _extract_lever_description(item: dict) -> str | None:
    """Extract plain text description from Lever's structured content list."""
    description_parts = []

    # descriptionPlain is available on some Lever endpoints
    if item.get("descriptionPlain"):
        return item["descriptionPlain"].strip()

    # description field (may contain HTML)
    if item.get("description"):
        return strip_html(item["description"])

    # lists: [{text: "Responsibilities", content: [...]}, ...]
    for section in item.get("lists", []):
        heading = section.get("text", "")
        if heading:
            description_parts.append(heading)
        for line in section.get("content", []):
            if isinstance(line, str):
                # Strip basic HTML tags
                clean = line.replace("<li>", "• ").replace("</li>", "")
                for tag in ("<p>", "</p>", "<br>", "<br/>", "<strong>", "</strong>", "<em>", "</em>"):
                    clean = clean.replace(tag, "")
                description_parts.append(clean.strip())

    return "\n".join(description_parts) if description_parts else None


def _infer_company_name(slug: str, item: dict) -> str:
    """Get company name, falling back to slug formatting."""
    return slug.replace("-", " ").replace("_", " ").title()
