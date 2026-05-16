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

from src.intake.base import ScraperError
from src.intake.batch import enrich_requirements, load_company_list
from src.intake.filters import load_filter_profiles
from src.intake.greenhouse import GreenhouseScraper
from src.intake.lever import LeverScraper
from src.intake.schema import RawJob

# Phase 13.8: the file-backed `src.intake.search_cache` module has been
# retired. Per-search caching is now the Job Index (Phase 13.4
# `src.jobs.search.cached_search`); end-to-end wiring of LinkedIn search
# into the Job Index lands with the daily run loop in Phase 17. Until
# then this function scrapes on every call (the previous file cache
# remained on disk only for the legacy import path -- see
# `src.jobs.legacy.import_legacy_file_cache`).

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
    max_keyword_detail_fetches: int = 5000,
    max_redirect_detail_fetches: int = 5000,
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
        max_keyword_detail_fetches: Max non-title matches to fetch and screen by JD text.
        max_redirect_detail_fetches: Max kept jobs to enrich for ATS redirect detection.
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
    precision_terms = _keyword_precision_terms(keyword_terms)
    linkedin_query = _linkedin_keyword_query(keyword_terms)

    # Phase 13.8: removed file-cache short-circuit. Every call now hits
    # LinkedIn; the Job Index will absorb the cache responsibility once
    # this function is wired into ``cached_search`` in Phase 17.
    jobs = None
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

            # Codex round-3 P2: the final redirect-enrichment pass now
            # covers EVERY kept job (title + description matches alike)
            # so the previous description_match_ids exclusion set has
            # been dropped. Description-only matches need apply-target
            # resolution too -- otherwise the downstream application
            # pipeline can't reach them.
            if keyword_terms:
                title_matches, detail_candidates = _partition_jobs_by_title_keywords(
                    jobs,
                    precision_terms,
                )
                description_matches: list[RawJob] = []

                if (
                    detail_candidates
                    and enrich_details
                    and scraper.last_search_mode == "authenticated"
                ):
                    keyword_detail_fetches = min(
                        _normalise_detail_fetch_limit(max_keyword_detail_fetches),
                        len(detail_candidates),
                    )
                    logger.info(
                        "LinkedIn description keyword filter fetching details for %d/%d "
                        "non-title matches",
                        keyword_detail_fetches,
                        len(detail_candidates),
                    )
                    if keyword_detail_fetches < len(detail_candidates):
                        logger.info(
                            "LinkedIn description keyword filter limited to %d/%d "
                            "non-title matches",
                            keyword_detail_fetches,
                            len(detail_candidates),
                        )
                    enriched_candidates = await scraper.enrich_jobs_with_details(
                        detail_candidates,
                        max_detail_fetches=keyword_detail_fetches,
                        include_apply_target=False,
                        delay_between_jobs=False,
                    )
                    _log_description_filter_coverage(enriched_candidates)
                    description_matches = _apply_keyword_precision_filter(
                        enriched_candidates,
                        precision_terms,
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
                    "LinkedIn keyword precision filter: %d title matches, "
                    "%d description matches, %d/%d jobs kept",
                    len(title_matches),
                    len(description_matches),
                    len(jobs),
                    len(title_matches) + len(detail_candidates),
                )

            if enrich_details and jobs and scraper.last_search_mode == "authenticated":
                # Codex P2 (round 3): description-only matches had
                # ``include_apply_target=False`` on their description-
                # fetch step (which is correct -- we don't want to pay
                # the apply-target click while screening). Excluding
                # them from the final redirect enrichment leaves their
                # external ATS URL unresolved, which breaks the
                # downstream apply pipeline. Enrich ALL kept jobs;
                # title matches that were already enriched will hit
                # LinkedIn's HTTP cache and cost ~nothing.
                jobs_to_enrich = list(jobs)
                if jobs_to_enrich:
                    logger.info(
                        "LinkedIn final redirect enrichment fetching details for %d "
                        "kept jobs (title + description matches)",
                        len(jobs_to_enrich),
                    )
                    enriched_jobs = await scraper.enrich_jobs_with_details(
                        jobs_to_enrich,
                        max_detail_fetches=_normalise_detail_fetch_limit(
                            max_redirect_detail_fetches
                        ),
                        delay_between_jobs=False,
                    )
                    enriched_by_id = {job.source_id: job for job in enriched_jobs}
                    jobs = [enriched_by_id.get(job.source_id, job) for job in jobs]
            elif enrich_details and jobs:
                logger.info("Skipping LinkedIn detail enrichment for public guest search results")

            jobs = _dedupe_linkedin_results(jobs)

        # Phase 13.8: file-cache save removed. The Job Index path takes
        # over when `cached_search` wraps this function (Phase 17).

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


def _normalise_detail_fetch_limit(value: int | None) -> int:
    try:
        limit = int(value) if value is not None else 5000
    except (TypeError, ValueError):
        return 5000
    return max(limit, 0)


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
        (include_title and _text_contains_keyword(job_title, keyword))
        or (include_description and _text_contains_keyword(job_description, keyword))
        for keyword in keywords
    )


def _text_contains_keyword(text: str, keyword: str) -> bool:
    keyword = keyword.strip().lower()
    if not keyword:
        return False
    if not re.fullmatch(r"[a-z0-9][a-z0-9\s-]*", keyword):
        return keyword in text
    pattern = (
        r"(?<![a-z0-9])"
        + re.escape(keyword).replace(r"\ ", r"[\s-]+")
        + r"(?![a-z0-9])"
    )
    return re.search(pattern, text) is not None


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


def _keyword_precision_terms(keywords: list[str]) -> list[str]:
    expansions = {
        "software": ["software", "developer", "programmer", "programming", "coding", "code"],
        "sde": ["sde", "software developer", "software engineer"],
        "fullstack": ["fullstack", "full stack", "full-stack"],
        "frontend": ["frontend", "front end", "front-end"],
        "backend": ["backend", "back end", "back-end"],
    }
    expanded: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        for term in expansions.get(keyword, [keyword]):
            if term not in seen:
                seen.add(term)
                expanded.append(term)
    return expanded


def _log_description_filter_coverage(jobs: list[RawJob]) -> None:
    if not jobs:
        return
    with_description = sum(1 for job in jobs if job.description)
    if with_description < len(jobs):
        logger.info(
            "LinkedIn description keyword filter inspected %d/%d non-empty descriptions",
            with_description,
            len(jobs),
        )


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
