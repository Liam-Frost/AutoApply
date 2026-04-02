"""Batch job intake orchestrator.

Runs multiple scrapers across a list of company slugs, parses JDs,
and persists results to the database.

Config file format (config/companies.yaml):
  greenhouse:
    - stripe
    - airbnb
    - notion
  lever:
    - linear
    - vercel
    - ramp
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from src.intake.base import ScraperError
from src.intake.filters import JobFilter, load_filter_profiles
from src.intake.greenhouse import GreenhouseScraper
from src.intake.jd_parser import parse_requirements
from src.intake.lever import LeverScraper
from src.intake.schema import RawJob
from src.intake.storage import upsert_jobs

logger = logging.getLogger("autoapply.intake.batch")


def load_company_list(config_path: Path) -> dict[str, list[str]]:
    """Load company slugs from YAML config.

    Returns dict mapping ATS name to list of company slugs.
    """
    if not config_path.exists():
        logger.warning("Company config not found at %s", config_path)
        return {}
    with open(config_path) as f:
        data = yaml.safe_load(f) or {}
    return {k: v for k, v in data.items() if isinstance(v, list)}


def run_intake(
    session: Session,
    companies: dict[str, list[str]],
    parse_jds: bool = True,
    use_llm: bool = False,  # LLM parsing off by default to avoid slow CLI calls during bulk intake
    job_filter: JobFilter | None = None,
) -> dict[str, int]:
    """Run intake for all configured companies.

    Args:
        session: DB session.
        companies: {ats_name: [slug, ...]} mapping.
        parse_jds: Whether to run JD requirement extraction.
        use_llm: Whether to use LLM for JD parsing (slower but better).
        job_filter: Optional filter to apply before persisting.

    Returns:
        Summary dict with inserted/skipped/error/filtered counts.
    """
    totals: dict[str, int] = {"inserted": 0, "skipped": 0, "errors": 0, "filtered": 0}

    scraper_map = {
        "greenhouse": GreenhouseScraper,
        "lever": LeverScraper,
    }

    for ats, slugs in companies.items():
        scraper_cls = scraper_map.get(ats)
        if not scraper_cls:
            logger.warning("No scraper registered for ATS '%s', skipping", ats)
            continue

        with scraper_cls() as scraper:
            for slug in slugs:
                try:
                    jobs = scraper.fetch_jobs(slug)

                    if parse_jds:
                        jobs = enrich_requirements(jobs, use_llm=use_llm)

                    # Apply filter if provided
                    filtered_out = 0
                    if job_filter:
                        before = len(jobs)
                        jobs = job_filter.apply(jobs)
                        filtered_out = before - len(jobs)
                        totals["filtered"] += filtered_out

                    inserted, skipped = upsert_jobs(session, jobs)
                    totals["inserted"] += inserted
                    totals["skipped"] += skipped

                    logger.info(
                        "[%s/%s] +%d new, %d skipped, %d filtered out",
                        ats, slug, inserted, skipped, filtered_out,
                    )

                except ScraperError as e:
                    logger.error("[%s/%s] Scraper error: %s", ats, slug, e)
                    totals["errors"] += 1
                except Exception as e:
                    logger.error("[%s/%s] Unexpected error: %s", ats, slug, e, exc_info=True)
                    totals["errors"] += 1

    return totals


def enrich_requirements(jobs: list[RawJob], use_llm: bool) -> list[RawJob]:
    """Parse JD text to extract structured requirements for each job."""
    for job in jobs:
        if not job.description:
            continue
        try:
            job.requirements = parse_requirements(job.description, use_llm=use_llm)
        except Exception as e:
            logger.debug("JD parse failed for '%s': %s", job.title, e)
    return jobs
