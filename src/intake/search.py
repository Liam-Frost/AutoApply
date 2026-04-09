"""Batch search interface -- scrape + filter + return/persist matching jobs.

This is the main entry point for finding relevant jobs. It combines:
1. Scraping from configured ATS boards (Greenhouse, Lever)
2. LinkedIn job search (Playwright-based, authenticated)
3. JD parsing for structured requirements
4. Filter profiles to narrow results

Can be used standalone (dry-run, no DB) or with full persistence.

Usage (programmatic):
    results = search_jobs(profile="default")               # ATS boards
    results = search_linkedin(keywords="swe intern")       # LinkedIn
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
from pathlib import Path

from src.core.config import load_config
from src.intake.base import ScraperError
from src.intake.batch import enrich_requirements, load_company_list
from src.intake.filters import load_filter_profiles
from src.intake.greenhouse import GreenhouseScraper
from src.intake.lever import LeverScraper
from src.intake.schema import RawJob
from src.intake.search_cache import (
    build_linkedin_search_cache_key,
    load_cached_linkedin_search,
    save_cached_linkedin_search,
)

logger = logging.getLogger("autoapply.intake.search")

DEFAULT_CONFIG_DIR = Path("config")
KEYWORD_STOPWORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
SHORT_KEYWORD_EXCEPTIONS = {"ai", "ml", "qa", "ui", "ux", "c#", "c++"}


def search_jobs(
    profile: str | None = "default",
    config_dir: Path = DEFAULT_CONFIG_DIR,
    companies: dict[str, list[str]] | None = None,
    parse_jds: bool = True,
    use_llm: bool = False,
) -> list[RawJob]:
    """Search for jobs from ATS boards matching a filter profile.

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
    job_filter = None
    if profile:
        profiles = load_filter_profiles(config_dir / "filters.yaml")
        job_filter = profiles.get(profile)
        if not job_filter:
            logger.warning("Filter profile '%s' not found, returning unfiltered", profile)

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


async def search_linkedin(
    keywords: str | list[str],
    location: str = "",
    time_filter: str = "week",
    experience_levels: list[str] | None = None,
    job_types: list[str] | None = None,
    max_pages: int = 20,
    enrich_details: bool = True,
    max_detail_fetches: int = 8,
    headless: bool = False,
    filter_profile: str | None = None,
    config_dir: Path = DEFAULT_CONFIG_DIR,
    allow_public_fallback: bool = False,
) -> list[RawJob]:
    """Search LinkedIn for jobs and optionally enrich with detail pages.

    Args:
        keywords: Search keyword string or keyword list.
        location: Location filter (e.g. "United States").
        time_filter: Time filter: "24h", "week", "month".
        experience_levels: Experience levels: "internship", "entry", etc.
        job_types: Job types: "fulltime", "internship", etc.
        max_pages: Max result pages to scrape.
        enrich_details: If True, fetch detail pages for ATS redirect detection.
        max_detail_fetches: Max number of jobs to enrich with detail pages.
        headless: Run browser headless (first run requires non-headless for login).
        filter_profile: Optional filter profile name to apply after scraping.
        config_dir: Config directory for filter profiles.
        allow_public_fallback: When True, use LinkedIn's public guest search page if
            no authenticated session is available.

    Returns:
        List of RawJob objects from LinkedIn.
    """
    from src.intake.linkedin import LinkedInScraper

    keyword_terms = _keyword_terms(keywords)
    linkedin_query = _linkedin_keyword_query(keyword_terms)
    cache_settings = _search_cache_settings()
    cache_key = build_linkedin_search_cache_key(
        keywords=keyword_terms,
        location=location,
        time_filter=time_filter,
        experience_levels=experience_levels,
        job_types=job_types,
        enrich_details=enrich_details,
        max_detail_fetches=max_detail_fetches,
        allow_public_fallback=allow_public_fallback,
    )

    jobs = None
    if cache_settings["enabled"]:
        jobs = load_cached_linkedin_search(
            cache_key,
            ttl_hours=cache_settings["ttl_hours"],
            requested_max_pages=max_pages,
        )
        if jobs is not None:
            logger.info("LinkedIn search cache hit: %d jobs", len(jobs))

    if jobs is None:
        async with LinkedInScraper(headless=headless) as scraper:
            jobs = await scraper.search_jobs(
                keywords=linkedin_query,
                location=location,
                time_filter=time_filter,
                experience_levels=experience_levels,
                job_types=job_types,
                max_pages=max_pages,
                allow_public_fallback=allow_public_fallback,
            )

            if keyword_terms:
                title_matches, detail_candidates = _partition_jobs_by_title_keywords(
                    jobs,
                    keyword_terms,
                )
                description_matches: list[RawJob] = []

                if (
                    detail_candidates
                    and enrich_details
                    and scraper.last_search_mode == "authenticated"
                ):
                    keyword_detail_fetches = min(max_detail_fetches, len(detail_candidates))
                    if keyword_detail_fetches < len(detail_candidates):
                        logger.info(
                            "LinkedIn description keyword filter limited to %d/%d non-title matches",
                            keyword_detail_fetches,
                            len(detail_candidates),
                        )
                    enriched_candidates = await scraper.enrich_jobs_with_details(
                        detail_candidates,
                        max_detail_fetches=keyword_detail_fetches,
                        delay_between_jobs=False,
                    )
                    description_matches = _apply_keyword_precision_filter(
                        enriched_candidates,
                        keyword_terms,
                        include_title=False,
                        log_label="LinkedIn description keyword filter",
                    )
                elif detail_candidates:
                    reason = (
                        "public guest search results"
                        if enrich_details
                        else "detail enrichment disabled"
                    )
                    logger.info(
                        "Skipping LinkedIn description keyword filter for %d non-title matches: %s",
                        len(detail_candidates),
                        reason,
                    )

                jobs = _dedupe_linkedin_results([*title_matches, *description_matches])
                logger.info(
                    "LinkedIn keyword precision filter: %d title matches, %d description matches, %d/%d jobs kept",
                    len(title_matches),
                    len(description_matches),
                    len(jobs),
                    len(title_matches) + len(detail_candidates),
                )

            if enrich_details and jobs and scraper.last_search_mode == "authenticated":
                jobs = await scraper.enrich_jobs_with_details(
                    jobs,
                    max_detail_fetches=max_detail_fetches,
                )
            elif enrich_details and jobs:
                logger.info("Skipping LinkedIn detail enrichment for public guest search results")

        if cache_settings["enabled"]:
            save_cached_linkedin_search(cache_key, jobs, max_pages=max_pages)

    # Apply filter if requested
    if filter_profile:
        profiles = load_filter_profiles(config_dir / "filters.yaml")
        job_filter = profiles.get(filter_profile)
        if job_filter:
            jobs = job_filter.apply(jobs)

    logger.info("LinkedIn search: %d jobs returned", len(jobs))
    return jobs


def _apply_keyword_precision_filter(
    jobs: list[RawJob],
    keywords: str | list[str],
    *,
    include_title: bool = True,
    include_description: bool = True,
    log_label: str = "LinkedIn keyword precision filter",
) -> list[RawJob]:
    keyword_terms = _keyword_terms(keywords)
    if not keyword_terms or not (include_title or include_description):
        return jobs

    matched = [
        job
        for job in jobs
        if _job_matches_keywords(
            job,
            keyword_terms,
            include_title=include_title,
            include_description=include_description,
        )
    ]
    logger.info("%s: %d/%d jobs kept", log_label, len(matched), len(jobs))
    return matched


def _partition_jobs_by_title_keywords(
    jobs: list[RawJob],
    keywords: str | list[str],
) -> tuple[list[RawJob], list[RawJob]]:
    keyword_terms = _keyword_terms(keywords)
    if not keyword_terms:
        return jobs, []

    title_matches: list[RawJob] = []
    remaining: list[RawJob] = []
    for job in jobs:
        if _job_matches_keywords(job, keyword_terms, include_description=False):
            title_matches.append(job)
        else:
            remaining.append(job)
    return title_matches, remaining


def _job_matches_keywords(
    job: RawJob,
    keywords: list[str],
    *,
    include_title: bool = True,
    include_description: bool = True,
) -> bool:
    job_title = (job.title or "").lower()
    job_description = (job.description or "").lower()
    return any(
        (include_title and keyword in job_title)
        or (include_description and keyword in job_description)
        for keyword in keywords
    )


def _keyword_terms(keywords: str | list[str]) -> list[str]:
    if isinstance(keywords, str):
        candidates = re.split(r"[\r\n,;]+", keywords)
    else:
        candidates = keywords

    terms = []
    for candidate in candidates:
        value = " ".join(str(candidate).strip().lower().split())
        if not value or value in KEYWORD_STOPWORDS:
            continue
        if len(value) < 3 and value not in SHORT_KEYWORD_EXCEPTIONS:
            continue
        terms.append(value)
    return terms


def _linkedin_keyword_query(keywords: list[str]) -> str:
    if not keywords:
        return ""
    if len(keywords) == 1:
        return keywords[0]
    return " OR ".join(keywords)


def _dedupe_linkedin_results(jobs: list[RawJob]) -> list[RawJob]:
    deduped: list[RawJob] = []
    seen: set[tuple[str, str, str]] = set()
    for job in jobs:
        signature = (
            (job.company or "").strip().lower(),
            (job.title or "").strip().lower(),
            (job.location or "").strip().lower(),
        )
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(job)
    if len(deduped) != len(jobs):
        logger.info("LinkedIn duplicate collapse: %d/%d jobs kept", len(deduped), len(jobs))
    return deduped


def _search_cache_settings() -> dict:
    config = load_config()
    cache_cfg = config.get("search_cache", {})
    return {
        "enabled": bool(cache_cfg.get("enabled", True)),
        "ttl_hours": int(cache_cfg.get("ttl_hours", 24)),
    }


def search_linkedin_sync(
    keywords: str,
    location: str = "",
    **kwargs,
) -> list[RawJob]:
    """Synchronous wrapper for search_linkedin (for CLI use)."""
    return asyncio.run(search_linkedin(keywords=keywords, location=location, **kwargs))


def _print_results(jobs: list[RawJob]) -> None:
    """Pretty-print search results to stdout."""
    if not jobs:
        print("No matching jobs found.")
        return

    print(f"\n{'=' * 80}")
    print(f" Found {len(jobs)} matching jobs")
    print(f"{'=' * 80}\n")

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
