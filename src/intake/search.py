"""Batch search interface — scrape + filter + return/persist matching jobs.

This is the main entry point for finding relevant jobs. It combines:
1. Scraping from configured ATS boards
2. JD parsing for structured requirements
3. Filter profiles to narrow results

Can be used standalone (dry-run, no DB) or with full persistence.

Usage (programmatic):
    results = search_jobs(profile="default")  # dry-run, returns list
    results = search_jobs(profile="default", session=db_session)  # persist

Usage (CLI):
    python -m src.intake.search --profile default --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.intake.batch import load_company_list, enrich_requirements
from src.intake.base import ScraperError
from src.intake.filters import JobFilter, load_filter_profiles
from src.intake.greenhouse import GreenhouseScraper
from src.intake.lever import LeverScraper
from src.intake.schema import RawJob

logger = logging.getLogger("autoapply.intake.search")

DEFAULT_CONFIG_DIR = Path("config")


def search_jobs(
    profile: str = "default",
    config_dir: Path = DEFAULT_CONFIG_DIR,
    companies: dict[str, list[str]] | None = None,
    parse_jds: bool = True,
    use_llm: bool = False,
) -> list[RawJob]:
    """Search for jobs matching a filter profile. Returns matched jobs without persisting.

    Args:
        profile: Name of the filter profile from filters.yaml.
        config_dir: Directory containing companies.yaml and filters.yaml.
        companies: Override company slugs (if None, loaded from companies.yaml).
        parse_jds: Whether to parse JDs for structured requirements.
        use_llm: Whether to use LLM for JD parsing.

    Returns:
        List of RawJob objects that passed the filter.
    """
    # Load companies
    if companies is None:
        companies = load_company_list(config_dir / "companies.yaml")
    if not companies:
        logger.warning("No companies configured")
        return []

    # Load filter
    profiles = load_filter_profiles(config_dir / "filters.yaml")
    job_filter = profiles.get(profile)
    if not job_filter:
        logger.warning("Filter profile '%s' not found, returning unfiltered", profile)
        job_filter = None

    # Scrape
    scraper_map = {
        "greenhouse": GreenhouseScraper,
        "lever": LeverScraper,
    }

    all_jobs: list[RawJob] = []
    errors = 0

    for ats, slugs in companies.items():
        scraper_cls = scraper_map.get(ats)
        if not scraper_cls:
            logger.warning("No scraper for ATS '%s'", ats)
            continue

        with scraper_cls() as scraper:
            for slug in slugs:
                try:
                    jobs = scraper.fetch_jobs(slug)
                    if parse_jds:
                        jobs = enrich_requirements(jobs, use_llm=use_llm)
                    all_jobs.extend(jobs)
                    logger.info("[%s/%s] fetched %d jobs", ats, slug, len(jobs))
                except ScraperError as e:
                    logger.error("[%s/%s] %s", ats, slug, e)
                    errors += 1
                except Exception as e:
                    logger.error("[%s/%s] %s", ats, slug, e, exc_info=True)
                    errors += 1

    logger.info("Total scraped: %d jobs (%d errors)", len(all_jobs), errors)

    # Filter
    if job_filter:
        matched = job_filter.apply(all_jobs)
    else:
        matched = all_jobs

    logger.info("Matched: %d/%d jobs", len(matched), len(all_jobs))
    return matched


def _print_results(jobs: list[RawJob]) -> None:
    """Pretty-print search results to stdout."""
    if not jobs:
        print("No matching jobs found.")
        return

    print(f"\n{'='*80}")
    print(f" Found {len(jobs)} matching jobs")
    print(f"{'='*80}\n")

    for i, job in enumerate(jobs, 1):
        print(f"  [{i:3d}] {job.company} — {job.title}")
        parts = []
        if job.location:
            parts.append(job.location)
        if job.employment_type != "unknown":
            parts.append(job.employment_type)
        if parts:
            print(f"        {' | '.join(parts)}")
        if job.application_url:
            print(f"        {job.application_url}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Search for matching jobs")
    parser.add_argument("--profile", default="default", help="Filter profile name")
    parser.add_argument("--config-dir", default="config", help="Config directory")
    parser.add_argument("--no-parse", action="store_true", help="Skip JD parsing")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM for JD parsing")
    parser.add_argument("--ats", help="Only scrape this ATS (greenhouse/lever)")
    parser.add_argument("--company", help="Only scrape this company slug")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Build company override if specific ATS/company requested
    companies = None
    if args.ats and args.company:
        companies = {args.ats: [args.company]}
    elif args.company:
        # Try both ATS types
        companies = {"greenhouse": [args.company], "lever": [args.company]}

    jobs = search_jobs(
        profile=args.profile,
        config_dir=Path(args.config_dir),
        companies=companies,
        parse_jds=not args.no_parse,
        use_llm=args.use_llm,
    )

    _print_results(jobs)


if __name__ == "__main__":
    main()
