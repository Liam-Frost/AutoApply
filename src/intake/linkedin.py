"""LinkedIn job scraper.

Uses Playwright to scrape LinkedIn job search results from an authenticated session.
LinkedIn requires JavaScript rendering and authentication, so we use browser automation
instead of the httpx-based approach used for Greenhouse/Lever.

Key flow:
1. Start browser with persistent cookie storage (avoids re-login each run)
2. Check login state; if not logged in, open browser for manual login
3. Build search URL from keywords/location/filters
4. Paginate through search results, extracting job cards
5. For each job, detect if it redirects to an external ATS (Greenhouse/Lever)
6. Return normalized RawJob objects compatible with the existing pipeline

Usage:
    async with LinkedInScraper() as scraper:
        jobs = await scraper.search_jobs(keywords="software engineer intern", location="United States")
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import quote_plus, urlencode

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from src.core.config import PROJECT_ROOT
from src.intake.schema import (
    RawJob,
    classify_employment_type,
    classify_seniority,
)

logger = logging.getLogger("autoapply.intake.linkedin")

LINKEDIN_BASE = "https://www.linkedin.com"
LINKEDIN_JOBS_SEARCH = "https://www.linkedin.com/jobs/search/"

# Persistent storage for cookies/session
DEFAULT_SESSION_DIR = PROJECT_ROOT / "data" / ".linkedin_session"

# LinkedIn time filter mapping
TIME_FILTER_MAP = {
    "24h": "r86400",
    "week": "r604800",
    "month": "r2592000",
}

# LinkedIn experience level filter (maps to LinkedIn's f_E parameter)
EXPERIENCE_LEVEL_MAP = {
    "internship": "1",
    "entry": "2",
    "associate": "3",
    "mid_senior": "4",
    "director": "5",
    "executive": "6",
}

# LinkedIn job type filter (maps to LinkedIn's f_JT parameter)
JOB_TYPE_MAP = {
    "fulltime": "F",
    "parttime": "P",
    "contract": "C",
    "temporary": "T",
    "internship": "I",
}

# Selectors for job search results page
SELECTORS = {
    "job_card": "div.job-card-container, li.jobs-search-results__list-item",
    "job_title": "a.job-card-list__title, a.job-card-container__link",
    "job_company": "span.job-card-container__primary-description, span.job-card-container__company-name",
    "job_location": "li.job-card-container__metadata-item, span.job-card-container__metadata-wrapper",
    "job_link": "a.job-card-list__title, a.job-card-container__link",
    "pagination_next": "button[aria-label='View next page'], li.artdeco-pagination__indicator--number button",
    "login_form": "form.login__form, #username",
    "feed_indicator": "div.feed-identity-module, nav.global-nav",
    "job_detail_panel": "div.jobs-search__job-details, div.job-details",
    "apply_button": "button.jobs-apply-button, a.jobs-apply-button",
    "external_apply_link": "a[data-tracking-control-name*='apply'], a.jobs-apply-button--top-card",
}


class LinkedInSession:
    """Manages LinkedIn authenticated browser sessions with cookie persistence.

    Stores cookies/local storage in a persistent directory so the user only
    needs to log in once. Subsequent runs reuse the saved session.
    """

    def __init__(
        self,
        session_dir: Path = DEFAULT_SESSION_DIR,
        headless: bool = False,
    ):
        self.session_dir = session_dir
        self.headless = headless
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def __aenter__(self) -> LinkedInSession:
        await self.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def start(self) -> None:
        """Launch browser with persistent context for cookie reuse."""
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()

        # Use persistent context -- cookies and localStorage are saved automatically
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.session_dir),
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",
            ],
            java_script_enabled=True,
        )

        logger.info("LinkedIn session started (session_dir=%s)", self.session_dir)

    async def close(self) -> None:
        """Close browser and save session state."""
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("LinkedIn session closed")

    async def get_page(self) -> Page:
        """Get or create a page in the persistent context."""
        if not self._context:
            raise RuntimeError("Session not started")
        pages = self._context.pages
        if pages:
            return pages[0]
        return await self._context.new_page()

    async def ensure_logged_in(self) -> bool:
        """Check if logged in; if not, navigate to login and wait for user.

        Returns True if logged in, False if login was cancelled/timed out.
        """
        page = await self.get_page()

        # Navigate to LinkedIn and check login state
        await page.goto(LINKEDIN_BASE, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        if await self._is_logged_in(page):
            logger.info("LinkedIn session is authenticated")
            return True

        # Not logged in -- navigate to login page
        logger.info("Not logged in to LinkedIn -- opening login page")
        await page.goto(
            f"{LINKEDIN_BASE}/login",
            wait_until="domcontentloaded",
            timeout=30000,
        )

        if self.headless:
            logger.error(
                "LinkedIn login required but running headless. "
                "Run with --no-headless first to log in."
            )
            return False

        # Wait for user to complete login (up to 5 minutes)
        logger.info("Please log in to LinkedIn in the browser window...")
        try:
            # Wait until we detect the feed or nav that indicates logged-in state
            await page.wait_for_selector(
                SELECTORS["feed_indicator"],
                timeout=300000,  # 5 minutes
                state="visible",
            )
            logger.info("LinkedIn login successful")
            return True
        except Exception:
            logger.error("LinkedIn login timed out or failed")
            return False

    async def _is_logged_in(self, page: Page) -> bool:
        """Check if the current page indicates a logged-in LinkedIn session."""
        try:
            # Check for logged-in indicators
            indicator = await page.query_selector(SELECTORS["feed_indicator"])
            if indicator:
                return True

            # Check URL -- /feed or /in/ paths indicate logged in
            url = page.url
            if "/feed" in url or "/in/" in url or "/jobs/" in url:
                return True

            return False
        except Exception:
            return False


class LinkedInScraper:
    """Scrapes LinkedIn job search results.

    Usage:
        async with LinkedInScraper() as scraper:
            jobs = await scraper.search_jobs(
                keywords="software engineer intern",
                location="United States",
            )
    """

    def __init__(
        self,
        session_dir: Path = DEFAULT_SESSION_DIR,
        headless: bool = False,
        min_delay: float = 3.0,
        max_delay: float = 7.0,
    ):
        self._session = LinkedInSession(session_dir=session_dir, headless=headless)
        self.min_delay = min_delay
        self.max_delay = max_delay

    async def __aenter__(self) -> LinkedInScraper:
        await self._session.start()
        return self

    async def __aexit__(self, *args) -> None:
        await self._session.close()

    async def search_jobs(
        self,
        keywords: str,
        location: str = "",
        time_filter: str = "week",
        experience_levels: list[str] | None = None,
        job_types: list[str] | None = None,
        max_pages: int = 5,
    ) -> list[RawJob]:
        """Search LinkedIn for jobs matching the given criteria.

        Args:
            keywords: Search keywords (e.g. "software engineer intern").
            location: Location filter (e.g. "United States", "San Francisco").
            time_filter: Time posted filter: "24h", "week", "month".
            experience_levels: List of experience levels: "internship", "entry", etc.
            job_types: List of job types: "fulltime", "internship", etc.
            max_pages: Maximum number of result pages to scrape.

        Returns:
            List of RawJob objects.
        """
        # Ensure logged in
        if not await self._session.ensure_logged_in():
            logger.error("Cannot search -- not logged in to LinkedIn")
            return []

        page = await self._session.get_page()

        # Build search URL
        url = self._build_search_url(
            keywords=keywords,
            location=location,
            time_filter=time_filter,
            experience_levels=experience_levels,
            job_types=job_types,
        )

        all_jobs: list[RawJob] = []
        seen_ids: set[str] = set()

        for page_num in range(max_pages):
            page_url = f"{url}&start={page_num * 25}" if page_num > 0 else url
            logger.info("Scraping LinkedIn page %d: %s", page_num + 1, page_url)

            try:
                await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
                await self._random_delay()

                # Wait for job cards to load
                await page.wait_for_selector(
                    SELECTORS["job_card"],
                    timeout=15000,
                    state="visible",
                )

                # Scroll down to load more results
                await self._scroll_results(page)

                # Extract job cards
                jobs = await self._extract_job_cards(page)

                new_jobs = 0
                for job in jobs:
                    if job.source_id not in seen_ids:
                        seen_ids.add(job.source_id)
                        all_jobs.append(job)
                        new_jobs += 1

                logger.info(
                    "Page %d: extracted %d jobs (%d new)",
                    page_num + 1, len(jobs), new_jobs,
                )

                # Stop if no new results (end of listings)
                if new_jobs == 0:
                    logger.info("No new jobs on page %d, stopping", page_num + 1)
                    break

            except Exception as e:
                logger.error("Error scraping page %d: %s", page_num + 1, e)
                break

        logger.info("LinkedIn search complete: %d total jobs", len(all_jobs))
        return all_jobs

    async def get_job_detail(self, page: Page, job: RawJob) -> RawJob:
        """Navigate to a job detail page and extract additional info.

        Enriches the job with:
        - Full description
        - External ATS application URL (if redirected to Greenhouse/Lever)
        """
        if not job.application_url:
            return job

        try:
            await page.goto(job.application_url, wait_until="domcontentloaded", timeout=30000)
            await self._random_delay()

            # Extract full description
            desc_el = await page.query_selector(
                "div.jobs-description__content, "
                "div.show-more-less-html__markup, "
                "article.jobs-description"
            )
            if desc_el:
                job.description = await desc_el.inner_text()

            # Detect external apply link (ATS redirect)
            ats_url = await self._detect_external_ats(page)
            if ats_url:
                job.raw_data["linkedin_url"] = job.application_url
                job.application_url = ats_url
                job.ats_type = _detect_ats_type(ats_url)
                logger.info(
                    "Detected external ATS for %s: %s -> %s",
                    job.title, job.raw_data["linkedin_url"], ats_url,
                )

        except Exception as e:
            logger.warning("Failed to get detail for job %s: %s", job.source_id, e)

        return job

    async def enrich_jobs_with_details(
        self,
        jobs: list[RawJob],
        max_detail_fetches: int = 20,
    ) -> list[RawJob]:
        """Fetch detail pages for jobs to get full descriptions and ATS links."""
        page = await self._session.get_page()

        enriched = []
        for i, job in enumerate(jobs[:max_detail_fetches]):
            logger.info(
                "Enriching job %d/%d: %s at %s",
                i + 1, min(len(jobs), max_detail_fetches), job.title, job.company,
            )
            enriched_job = await self.get_job_detail(page, job)
            enriched.append(enriched_job)
            await self._random_delay()

        # Append remaining non-enriched jobs
        enriched.extend(jobs[max_detail_fetches:])
        return enriched

    def _build_search_url(
        self,
        keywords: str,
        location: str = "",
        time_filter: str = "week",
        experience_levels: list[str] | None = None,
        job_types: list[str] | None = None,
    ) -> str:
        """Build LinkedIn job search URL with filters."""
        params: dict[str, str] = {
            "keywords": keywords,
            "refresh": "true",
            "sortBy": "DD",  # Sort by date
        }

        if location:
            params["location"] = location

        # Time filter
        if time_filter in TIME_FILTER_MAP:
            params["f_TPR"] = TIME_FILTER_MAP[time_filter]

        # Experience level filter
        if experience_levels:
            levels = []
            for level in experience_levels:
                if level in EXPERIENCE_LEVEL_MAP:
                    levels.append(EXPERIENCE_LEVEL_MAP[level])
            if levels:
                params["f_E"] = ",".join(levels)

        # Job type filter
        if job_types:
            types = []
            for jt in job_types:
                if jt in JOB_TYPE_MAP:
                    types.append(JOB_TYPE_MAP[jt])
            if types:
                params["f_JT"] = ",".join(types)

        return f"{LINKEDIN_JOBS_SEARCH}?{urlencode(params)}"

    async def _extract_job_cards(self, page: Page) -> list[RawJob]:
        """Extract job information from search result cards on the page."""
        jobs: list[RawJob] = []

        # Get all job card elements
        cards = await page.query_selector_all(SELECTORS["job_card"])

        for card in cards:
            try:
                job = await self._parse_job_card(card)
                if job:
                    jobs.append(job)
            except Exception as e:
                logger.debug("Failed to parse job card: %s", e)

        return jobs

    async def _parse_job_card(self, card) -> RawJob | None:
        """Parse a single job card element into a RawJob."""
        # Extract title
        title_el = await card.query_selector(SELECTORS["job_title"])
        if not title_el:
            return None
        title = (await title_el.inner_text()).strip()
        if not title:
            return None

        # Extract link / job ID
        href = await title_el.get_attribute("href") or ""
        source_id = _extract_job_id_from_url(href)
        if not source_id:
            return None

        # Build application URL
        if href.startswith("/"):
            application_url = f"{LINKEDIN_BASE}{href.split('?')[0]}"
        elif href.startswith("http"):
            application_url = href.split("?")[0]
        else:
            application_url = f"{LINKEDIN_BASE}/jobs/view/{source_id}/"

        # Extract company
        company_el = await card.query_selector(SELECTORS["job_company"])
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        # Extract location
        location_el = await card.query_selector(SELECTORS["job_location"])
        location = (await location_el.inner_text()).strip() if location_el else None

        return RawJob(
            source="linkedin",
            source_id=source_id,
            company=company,
            title=title,
            location=location,
            employment_type=classify_employment_type(title),
            seniority=classify_seniority(title),
            description=None,  # Populated in detail fetch
            application_url=application_url,
            ats_type="linkedin",
            raw_data={"linkedin_href": href},
        )

    async def _detect_external_ats(self, page: Page) -> str | None:
        """Detect if the apply button redirects to an external ATS.

        Checks the apply button for external links to Greenhouse, Lever, etc.
        Returns the external URL if found, None if it's LinkedIn Easy Apply.
        """
        try:
            # Look for the apply button
            apply_btn = await page.query_selector(SELECTORS["apply_button"])
            if not apply_btn:
                return None

            btn_text = (await apply_btn.inner_text()).strip().lower()

            # "Easy Apply" means LinkedIn native -- no external ATS
            if "easy apply" in btn_text:
                return None

            # "Apply" (without "Easy") often means external redirect
            # Check if it's a link
            href = await apply_btn.get_attribute("href")
            if href and _is_known_ats_url(href):
                return _clean_tracking_url(href)

            # Try clicking and intercepting the navigation
            # Open in new tab to avoid losing current page
            async with page.expect_popup(timeout=10000) as popup_info:
                await apply_btn.click()

            popup = await popup_info.value
            await popup.wait_for_load_state("domcontentloaded", timeout=10000)
            external_url = popup.url
            await popup.close()

            if _is_known_ats_url(external_url):
                return _clean_tracking_url(external_url)

            return None

        except Exception as e:
            logger.debug("External ATS detection failed: %s", e)
            return None

    async def _scroll_results(self, page: Page) -> None:
        """Scroll the job results list to trigger lazy loading."""
        try:
            results_container = await page.query_selector(
                "div.jobs-search-results-list, ul.jobs-search__results-list"
            )
            if results_container:
                for _ in range(3):
                    await page.evaluate(
                        """(el) => el.scrollBy(0, 500)""",
                        results_container,
                    )
                    await page.wait_for_timeout(800)
        except Exception:
            # Fallback: scroll the entire page
            for _ in range(3):
                await page.keyboard.press("End")
                await page.wait_for_timeout(800)

    async def _random_delay(self) -> None:
        """Random delay to mimic human browsing behavior."""
        import random
        delay = random.uniform(self.min_delay, self.max_delay)
        await asyncio.sleep(delay)


def _extract_job_id_from_url(href: str) -> str | None:
    """Extract LinkedIn job ID from a job URL.

    Examples:
        /jobs/view/1234567890/ -> "1234567890"
        /jobs/view/1234567890?refId=... -> "1234567890"
    """
    match = re.search(r"/jobs/view/(\d+)", href)
    if match:
        return match.group(1)

    # Also try jobId parameter
    match = re.search(r"currentJobId=(\d+)", href)
    if match:
        return match.group(1)

    return None


def _is_known_ats_url(url: str) -> bool:
    """Check if a URL belongs to a known ATS platform."""
    known_patterns = [
        "greenhouse.io",
        "lever.co",
        "boards.greenhouse.io",
        "jobs.lever.co",
        "myworkdayjobs.com",
        "workday.com",
    ]
    url_lower = url.lower()
    return any(p in url_lower for p in known_patterns)


def _detect_ats_type(url: str) -> str:
    """Detect ATS type from URL."""
    url_lower = url.lower()
    if "greenhouse.io" in url_lower:
        return "greenhouse"
    elif "lever.co" in url_lower:
        return "lever"
    elif "workday" in url_lower:
        return "workday"
    return "company_site"


def _clean_tracking_url(url: str) -> str:
    """Remove tracking parameters from ATS URLs."""
    # Remove common tracking params but keep the base URL
    for sep in ["?utm_", "&utm_", "?ref=", "&ref="]:
        if sep in url:
            url = url.split(sep)[0]
    return url
