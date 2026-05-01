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
        jobs = await scraper.search_jobs(
            keywords="software engineer intern",
            location="United States",
        )
"""

from __future__ import annotations

import asyncio
import html
import logging
import re
import shutil
from contextlib import suppress
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from src.core.config import PROJECT_ROOT
from src.intake.html_utils import strip_html
from src.intake.schema import (
    RawJob,
    classify_employment_type,
    classify_seniority,
)

logger = logging.getLogger("autoapply.intake.linkedin")

LINKEDIN_BASE = "https://www.linkedin.com"
LINKEDIN_JOBS_SEARCH = "https://www.linkedin.com/jobs/search/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

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
    "job_card": (
        "div.job-card-container, li.jobs-search-results__list-item, li.scaffold-layout__list-item"
    ),
    "job_title": (
        "a.job-card-list__title, a.job-card-list__title--link, "
        "a.job-card-container__link, .artdeco-entity-lockup__title a"
    ),
    "job_company": (
        "span.job-card-container__primary-description, span.job-card-container__company-name, "
        "div.artdeco-entity-lockup__subtitle, div.artdeco-entity-lockup__subtitle span, "
        "a.job-card-container__company-name"
    ),
    "job_location": (
        "li.job-card-container__metadata-item, span.job-card-container__metadata-wrapper, "
        "ul.job-card-container__metadata-wrapper li, .artdeco-entity-lockup__caption, "
        ".artdeco-entity-lockup__caption li"
    ),
    "job_link": (
        "a.job-card-list__title, a.job-card-list__title--link, a.job-card-container__link"
    ),
    "pagination_next": (
        "button[aria-label='View next page'], li.artdeco-pagination__indicator--number button"
    ),
    "login_form": "form.login__form, #username",
    "feed_indicator": "div.feed-identity-module, nav.global-nav",
    "job_detail_panel": "div.jobs-search__job-details, div.job-details",
    "apply_button": (
        "button.jobs-apply-button, a.jobs-apply-button, "
        "[data-live-test-job-apply-button], "
        "main#workspace a[aria-label*='Apply'], main#workspace button[aria-label*='Apply'], "
        "main#workspace a[href*='/safety/go/']"
    ),
    "external_apply_link": "a[data-tracking-control-name*='apply'], a.jobs-apply-button--top-card",
}

PUBLIC_JOB_CARD_RE = re.compile(
    r'<li>\s*<div[^>]*class="base-card[^"]*base-search-card[^"]*job-search-card[^"]*"'
    r"(?P<attrs>[^>]*)>(?P<body>.*?)</div>\s*</li>",
    re.IGNORECASE | re.DOTALL,
)
PUBLIC_JOB_ID_RE = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"', re.IGNORECASE)
PUBLIC_JOB_LINK_RE = re.compile(
    r'href="(?P<value>https://www\.linkedin\.com/jobs/view/[^"]+)"',
    re.IGNORECASE,
)
PUBLIC_JOB_TITLE_RE = re.compile(
    r'<h3[^>]*class="base-search-card__title[^"]*"[^>]*>(?P<value>.*?)</h3>',
    re.IGNORECASE | re.DOTALL,
)
PUBLIC_JOB_COMPANY_RE = re.compile(
    r'<h4[^>]*class="base-search-card__subtitle[^"]*"[^>]*>(?P<value>.*?)</h4>',
    re.IGNORECASE | re.DOTALL,
)
PUBLIC_JOB_LOCATION_RE = re.compile(
    r'<span[^>]*class="job-search-card__location[^"]*"[^>]*>(?P<value>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)


class LinkedInAuthRequiredError(RuntimeError):
    """Raised when LinkedIn authenticated scraping is required but unavailable."""


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
            user_agent=DEFAULT_USER_AGENT,
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

    def has_saved_session_data(self) -> bool:
        """Return True when the persistent profile already contains browser state."""
        if not self.session_dir.exists():
            return False
        ignored = {"SingletonCookie", "SingletonLock", "SingletonSocket"}
        return any(entry.name not in ignored for entry in self.session_dir.iterdir())

    async def is_authenticated(self) -> bool:
        """Check whether the saved browser profile still has a valid LinkedIn session."""
        page = await self.get_page()
        await page.goto(LINKEDIN_BASE, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)
        return await self._is_logged_in(page)

    async def ensure_logged_in(self, timeout_ms: int = 300000) -> bool:
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
                "Run with --no-headless first to log in or use the web Connect LinkedIn flow."
            )
            return False

        # Poll the persistent context so the login flow succeeds as soon as
        # LinkedIn writes a valid authenticated session.
        logger.info("Please log in to LinkedIn in the browser window...")
        try:
            authenticated = await self._wait_for_authentication(timeout_ms=timeout_ms, page=page)
            if authenticated:
                logger.info("LinkedIn login successful")
                return True
        except Exception:
            logger.exception("LinkedIn login polling failed")

        logger.error("LinkedIn login timed out or failed")
        return False

    async def _is_logged_in(self, page: Page) -> bool:
        """Check if the current page indicates a logged-in LinkedIn session."""
        try:
            if await self._has_auth_cookie():
                return True

            # Check for logged-in indicators
            indicator = await page.query_selector(SELECTORS["feed_indicator"])
            if indicator:
                return True

            # Public jobs pages are accessible while logged out, so do not treat
            # generic /jobs URLs as proof of authentication.
            url = page.url.lower()
            if any(path in url for path in ("/feed", "/in/", "/mynetwork/", "/messaging/")):
                return True

            return False
        except Exception:
            return False

    async def _has_auth_cookie(self) -> bool:
        if not self._context:
            return False
        try:
            cookies = await self._context.cookies([LINKEDIN_BASE])
        except Exception:
            return False
        return any(cookie.get("name") == "li_at" and cookie.get("value") for cookie in cookies)

    async def _wait_for_authentication(self, *, timeout_ms: int, page: Page | None = None) -> bool:
        deadline = asyncio.get_running_loop().time() + (timeout_ms / 1000)

        while asyncio.get_running_loop().time() < deadline:
            if await self._has_auth_cookie():
                return True

            current_page = page
            if current_page is None or current_page.is_closed():
                try:
                    current_page = await self.get_page()
                except Exception:
                    await asyncio.sleep(1)
                    continue

            if await self._is_logged_in(current_page):
                return True

            await asyncio.sleep(1)

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
        self.last_search_mode = "authenticated"

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
        max_pages: int = 20,
        allow_public_fallback: bool = False,
    ) -> list[RawJob]:
        """Search LinkedIn for jobs matching the given criteria.

        Args:
            keywords: Search keywords (e.g. "software engineer intern").
            location: Location filter (e.g. "United States", "San Francisco").
            time_filter: Time posted filter: "24h", "week", "month".
            experience_levels: List of experience levels: "internship", "entry", etc.
            job_types: List of job types: "fulltime", "internship", etc.
            max_pages: Maximum number of result pages to scrape.
            allow_public_fallback: When True, fall back to guest search results if
                the saved LinkedIn session is not authenticated.

        Returns:
            List of RawJob objects.
        """
        # Ensure logged in
        if not await self._session.ensure_logged_in():
            if allow_public_fallback:
                logger.warning(
                    "LinkedIn session unavailable; falling back to public guest search results"
                )
                self.last_search_mode = "public_guest"
                return await self.search_public_jobs(
                    keywords=keywords,
                    location=location,
                    time_filter=time_filter,
                    experience_levels=experience_levels,
                    job_types=job_types,
                    max_pages=max_pages,
                )

            message = (
                "LinkedIn login required. Connect LinkedIn in the web app or run "
                "`autoapply search --source linkedin --keyword ... --no-headless` once."
            )
            logger.error("Cannot search -- not logged in to LinkedIn")
            raise LinkedInAuthRequiredError(message)

        self.last_search_mode = "authenticated"
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
        page_num = 0

        while page_num < max_pages:
            page_url = f"{url}&start={page_num * 25}" if page_num > 0 else url
            logger.info("Scraping LinkedIn page %d: %s", page_num + 1, page_url)

            try:
                jobs, page_state = await self._load_authenticated_search_page(
                    page,
                    page_url,
                    page_index=page_num + 1,
                    max_attempts=4,
                )

                if not jobs:
                    if page_num + 1 < max_pages:
                        probe_url = f"{url}&start={(page_num + 1) * 25}"
                        logger.warning(
                            "LinkedIn page %d stayed empty after retries (%s); "
                            "probing page %d once before stopping",
                            page_num + 1,
                            _summarize_search_page_state(page_state),
                            page_num + 2,
                        )
                        probe_jobs, probe_state = await self._load_authenticated_search_page(
                            page,
                            probe_url,
                            page_index=page_num + 2,
                            max_attempts=2,
                        )
                        if probe_jobs:
                            logger.warning(
                                "LinkedIn page %d stayed empty, but page %d has results "
                                "(%s); stopping to avoid skipping page %d jobs",
                                page_num + 1,
                                page_num + 2,
                                _summarize_search_page_state(probe_state),
                                page_num + 1,
                            )
                        else:
                            logger.info(
                                "Stopping LinkedIn search after empty page %d and empty "
                                "probe page %d; current=%s; next=%s",
                                page_num + 1,
                                page_num + 2,
                                _summarize_search_page_state(page_state),
                                _summarize_search_page_state(probe_state),
                            )
                        break

                    logger.info(
                        "Stopping LinkedIn search after empty page %d; last page state: %s",
                        page_num + 1,
                        _summarize_search_page_state(page_state),
                    )
                    break

                new_jobs = 0
                for job in jobs:
                    if job.source_id not in seen_ids:
                        seen_ids.add(job.source_id)
                        all_jobs.append(job)
                        new_jobs += 1

                logger.info(
                    "Page %d: extracted %d jobs (%d new)",
                    page_num + 1,
                    len(jobs),
                    new_jobs,
                )

                # Stop if no new results (end of listings)
                if new_jobs == 0:
                    logger.info("No new jobs on page %d, stopping", page_num + 1)
                    break

            except Exception as e:
                logger.error("Error scraping page %d: %s", page_num + 1, e)
                break

            page_num += 1

        logger.info("LinkedIn search complete: %d total jobs", len(all_jobs))
        return all_jobs

    async def _load_authenticated_search_page(
        self,
        page: Page,
        page_url: str,
        *,
        page_index: int,
        max_attempts: int,
    ) -> tuple[list[RawJob], dict[str, object] | None]:
        jobs: list[RawJob] = []
        page_state: dict[str, object] | None = None

        for attempt in range(1, max_attempts + 1):
            response = await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            await self._random_delay()

            jobs = []
            if response is not None:
                try:
                    jobs = _extract_html_job_cards(
                        await response.text(),
                        search_mode="authenticated_html",
                    )
                    jobs = _dedupe_jobs(jobs)
                except Exception as exc:
                    logger.debug("Failed to parse LinkedIn search response HTML: %s", exc)

            page_state = await self._wait_for_search_page_state(page)
            if page_state["status"] == "results":
                rendered_jobs = await self._collect_result_cards(page)
                if len(rendered_jobs) > len(jobs):
                    jobs = rendered_jobs
                elif rendered_jobs:
                    jobs = _dedupe_jobs([*jobs, *rendered_jobs])

            if jobs:
                return jobs, page_state

            if attempt < max_attempts:
                logger.warning(
                    "LinkedIn page %d returned no jobs on attempt %d/%d (%s); retrying",
                    page_index,
                    attempt,
                    max_attempts,
                    _summarize_search_page_state(page_state),
                )
                await page.wait_for_timeout(1500)

        return jobs, page_state

    async def search_public_jobs(
        self,
        keywords: str,
        location: str = "",
        time_filter: str = "week",
        experience_levels: list[str] | None = None,
        job_types: list[str] | None = None,
        max_pages: int = 20,
    ) -> list[RawJob]:
        """Search LinkedIn's public guest jobs pages without a saved session."""
        self.last_search_mode = "public_guest"
        url = self._build_search_url(
            keywords=keywords,
            location=location,
            time_filter=time_filter,
            experience_levels=experience_levels,
            job_types=job_types,
        )

        page = await self._session.get_page()
        all_jobs: list[RawJob] = []
        seen_ids: set[str] = set()

        for page_num in range(max_pages):
            page_url = f"{url}&start={page_num * 25}" if page_num > 0 else url
            logger.info("Scraping LinkedIn public page %d: %s", page_num + 1, page_url)

            response = await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)
            html_text = await response.text() if response is not None else await page.content()
            jobs = _extract_public_job_cards(html_text)

            new_jobs = 0
            for job in jobs:
                if job.source_id not in seen_ids:
                    seen_ids.add(job.source_id)
                    all_jobs.append(job)
                    new_jobs += 1

            logger.info(
                "Public page %d: extracted %d jobs (%d new)",
                page_num + 1,
                len(jobs),
                new_jobs,
            )

            if new_jobs == 0:
                break

            if page_num + 1 < max_pages:
                await self._random_delay()

        logger.info("LinkedIn public guest search complete: %d total jobs", len(all_jobs))
        return all_jobs

    async def get_job_detail(
        self,
        page: Page,
        job: RawJob,
        *,
        include_apply_target: bool = True,
        pause_after_load: bool = True,
    ) -> RawJob:
        """Navigate to a job detail page and extract additional info.

        Enriches the job with:
        - Full description
        - External ATS application URL (if redirected to Greenhouse/Lever)
        """
        if not job.application_url:
            return job

        try:
            detail_url = _canonical_linkedin_job_url(
                job.source_id,
                job.raw_data.get("linkedin_url")
                or job.raw_data.get("detail_url")
                or job.application_url,
            )
            job.raw_data["detail_url"] = detail_url

            await page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
            if pause_after_load:
                await self._random_delay()

            # Extract full description
            job.description = await self._extract_job_description_text(page)

            if not include_apply_target:
                return job

            # Resolve the visible Apply button target for manual apply first.
            apply_target = await self._resolve_apply_target(page, fallback_url=detail_url)
            if apply_target.get("manual_apply_url"):
                job.raw_data["manual_apply_url"] = apply_target["manual_apply_url"]

            # Detect external apply link (ATS redirect or company-hosted apply page).
            manual_apply_url = apply_target.get("manual_apply_url")
            external_apply_url = (
                manual_apply_url
                if manual_apply_url and "linkedin.com" not in manual_apply_url.lower()
                else None
            )
            if external_apply_url:
                job.raw_data["linkedin_url"] = detail_url
                job.application_url = external_apply_url
                job.ats_type = _detect_ats_type(external_apply_url)
                logger.info(
                    "Detected external apply target for %s: %s -> %s",
                    job.title,
                    job.raw_data["linkedin_url"],
                    external_apply_url,
                )

        except Exception as e:
            logger.warning("Failed to get detail for job %s: %s", job.source_id, e)

        return job

    async def _extract_job_description_text(self, page: Page) -> str | None:
        selectors = [
            "div.jobs-description__content",
            "div.show-more-less-html__markup",
            "article.jobs-description",
        ]

        for selector in selectors:
            elements = await page.query_selector_all(selector)
            candidates: list[str] = []
            for element in elements:
                try:
                    text = _normalize_job_description_text(await element.inner_text())
                except Exception:
                    continue
                if text:
                    candidates.append(text)
            if candidates:
                return max(candidates, key=len)

        try:
            fallback_text = await page.evaluate(
                """() => {
                    const root = document.querySelector('main#workspace') || document.body;
                    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
                    let best = null;
                    while (walker.nextNode()) {
                        const el = walker.currentNode;
                        const text = (el.innerText || '').trim();
                        if (!text || !/about the job/i.test(text) || text.length < 40) {
                            continue;
                        }
                        if (best === null || text.length > best.length) {
                            best = text;
                        }
                    }
                    return best;
                }"""
            )
        except Exception:
            return None

        return _normalize_job_description_text(fallback_text)

    async def resolve_manual_apply_url(self, job_url: str) -> str:
        """Resolve the destination of LinkedIn's Apply button for a job detail page."""
        await self._session.ensure_logged_in(timeout_ms=5000)
        page = await self._session.get_page()
        await page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1200)
        apply_target = await self._resolve_apply_target(page, fallback_url=job_url)
        return apply_target.get("manual_apply_url") or job_url

    async def enrich_jobs_with_details(
        self,
        jobs: list[RawJob],
        max_detail_fetches: int = 20,
        *,
        include_apply_target: bool = True,
        delay_between_jobs: bool = True,
    ) -> list[RawJob]:
        """Fetch detail pages for jobs to get full descriptions and ATS links."""
        page = await self._session.get_page()

        enriched = []
        for i, job in enumerate(jobs[:max_detail_fetches]):
            logger.info(
                "Enriching job %d/%d: %s at %s",
                i + 1,
                min(len(jobs), max_detail_fetches),
                job.title,
                job.company,
            )
            enriched_job = await self.get_job_detail(
                page,
                job,
                include_apply_target=include_apply_target,
                pause_after_load=delay_between_jobs,
            )
            enriched.append(enriched_job)
            if delay_between_jobs:
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
        title = _normalize_linkedin_title_text(await title_el.inner_text())
        if not title:
            return None

        # Extract link / job ID
        href = await title_el.get_attribute("href") or ""
        source_id = _extract_job_id_from_url(href)
        if not source_id:
            return None

        # Build application URL
        application_url = _canonical_linkedin_job_url(source_id, href)

        # Extract company
        company_el = await card.query_selector(SELECTORS["job_company"])
        company = _clean_html_text(await company_el.inner_text()) if company_el else "Unknown"

        # Extract location
        location_el = await card.query_selector(SELECTORS["job_location"])
        location = _clean_html_text(await location_el.inner_text()) if location_el else None

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
            raw_data={
                "linkedin_href": href,
                "detail_url": application_url,
                "manual_apply_url": application_url,
            },
        )

    async def _resolve_apply_target(self, page: Page, fallback_url: str) -> dict[str, str | None]:
        """Resolve the destination of the Apply button and classify ATS if possible."""
        try:
            apply_btn = await self._find_primary_apply_button(page)
            if not apply_btn:
                return {"manual_apply_url": fallback_url, "ats_url": None}

            btn_text = _clean_html_text(await apply_btn.inner_text()).lower()
            aria_label = _clean_html_text(await apply_btn.get_attribute("aria-label") or "").lower()
            href = _manual_apply_destination_url(
                await apply_btn.get_attribute("href"),
                source_url=fallback_url,
            )
            if href:
                clean_href = _clean_tracking_url(href)
                return {
                    "manual_apply_url": clean_href,
                    "ats_url": clean_href if _is_known_ats_url(clean_href) else None,
                }

            if "easy apply" in btn_text or "easy apply" in aria_label:
                return {"manual_apply_url": fallback_url, "ats_url": None}

            external_url = await self._resolve_click_apply_target(page, apply_btn)

            if external_url:
                clean_url = _clean_tracking_url(external_url)
                return {
                    "manual_apply_url": clean_url,
                    "ats_url": clean_url if _is_known_ats_url(clean_url) else None,
                }

            return {"manual_apply_url": fallback_url, "ats_url": None}

        except Exception as e:
            logger.debug("Apply target detection failed: %s", e)
            return {"manual_apply_url": fallback_url, "ats_url": None}

    async def _find_primary_apply_button(self, page: Page):
        candidates: list[tuple[float, object]] = []
        for element in await page.query_selector_all(SELECTORS["apply_button"]):
            try:
                if not await element.is_visible():
                    continue
                text = _clean_html_text(await element.inner_text())
                aria_label = _clean_html_text(await element.get_attribute("aria-label") or "")
                href = await element.get_attribute("href")
                if not _is_primary_apply_candidate(text, aria_label, href):
                    continue
                box = await element.bounding_box()
                y = box["y"] if box else float("inf")
                candidates.append((y, element))
            except Exception:
                continue

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    async def _resolve_click_apply_target(self, page: Page, apply_btn) -> str | None:
        baseline_url = _normalize_url(page.url)
        seen_document_targets: list[str] = []
        existing_pages = set(page.context.pages)

        def record_document_request(request) -> None:
            try:
                if request.resource_type != "document":
                    return
                target_url = _manual_apply_destination_url(
                    request.url,
                    source_url=baseline_url,
                )
                if target_url:
                    seen_document_targets.append(target_url)
            except Exception:
                return

        page.context.on("request", record_document_request)
        popup_task = asyncio.create_task(page.wait_for_event("popup", timeout=12000))
        new_page_task = asyncio.create_task(
            page.context.wait_for_event(
                "page",
                predicate=lambda candidate: candidate not in existing_pages,
                timeout=12000,
            )
        )

        try:
            await apply_btn.click()
        except Exception:
            await _cancel_pending_task(popup_task)
            await _cancel_pending_task(new_page_task)
            with suppress(Exception):
                page.context.remove_listener("request", record_document_request)
            raise

        try:
            handled_pages = set()
            for _ in range(48):
                if seen_document_targets:
                    return seen_document_targets[0]

                for task in (popup_task, new_page_task):
                    if not task.done():
                        continue
                    try:
                        opened_page = task.result()
                    except Exception:
                        continue
                    if opened_page in handled_pages:
                        continue
                    handled_pages.add(opened_page)

                    target_url = await self._wait_for_page_target_url(
                        opened_page,
                        baseline_url="about:blank",
                        source_url=baseline_url,
                        timeout_ms=12000,
                    )
                    try:
                        await opened_page.close()
                    except Exception:
                        pass
                    if target_url:
                        return target_url

                current_url = _manual_apply_destination_url(page.url, source_url=baseline_url)
                if current_url:
                    return current_url

                await page.wait_for_timeout(250)
        finally:
            if not popup_task.done():
                await _cancel_pending_task(popup_task)
            if not new_page_task.done():
                await _cancel_pending_task(new_page_task)
            with suppress(Exception):
                page.context.remove_listener("request", record_document_request)

        return None

    async def _wait_for_page_target_url(
        self,
        page: Page,
        *,
        baseline_url: str | None,
        source_url: str | None = None,
        timeout_ms: int,
    ) -> str | None:
        deadline = max(timeout_ms // 250, 1)
        for _ in range(deadline):
            current_url = _manual_apply_destination_url(
                page.url,
                source_url=source_url or baseline_url,
            )
            if current_url:
                return current_url
            await page.wait_for_timeout(250)
        return None

    async def _wait_for_search_page_state(self, page: Page) -> dict[str, object]:
        try:
            await page.wait_for_selector(
                SELECTORS["job_card"],
                timeout=15000,
                state="visible",
            )
        except PlaywrightTimeoutError:
            try:
                await page.wait_for_load_state("networkidle", timeout=3000)
            except PlaywrightTimeoutError:
                pass

        card_count = await page.locator(SELECTORS["job_card"]).count()
        title_count = await page.locator(SELECTORS["job_title"]).count()
        pagination_text = None

        for selector in (".artdeco-pagination__state--a11y", ".jobs-search-pagination__info"):
            locator = page.locator(selector)
            if await locator.count():
                try:
                    pagination_text = (await locator.first.inner_text()).strip() or None
                except Exception:
                    pagination_text = None
                if pagination_text:
                    break

        body_text = ""
        if card_count == 0 and title_count == 0:
            try:
                body_text = await page.locator("body").inner_text()
            except Exception:
                body_text = ""

        status = "unknown"
        if card_count > 0 or title_count > 0:
            status = "results"
        elif _page_has_no_results_text(body_text):
            status = "no_results"

        return {
            "status": status,
            "card_count": card_count,
            "title_count": title_count,
            "pagination_text": pagination_text,
            "has_no_results_text": _page_has_no_results_text(body_text),
        }

    async def _get_results_scroll_container(self, page: Page):
        candidates = [
            "div.scaffold-layout__list > div",
            "div.jobs-search-results-list",
            "ul.jobs-search__results-list",
        ]
        best_container = None
        best_score = -1

        for selector in candidates:
            for candidate in await page.query_selector_all(selector):
                try:
                    score = await page.evaluate(
                        """(el) => {
                            const cardCount = el.querySelectorAll([
                                'div.job-card-container',
                                'li.jobs-search-results__list-item',
                                'li.scaffold-layout__list-item',
                            ].join(', ')).length;
                            if (cardCount === 0) {
                                return -1;
                            }
                            return Math.max(el.scrollHeight - el.clientHeight, 0);
                        }""",
                        candidate,
                    )
                except Exception:
                    continue

                if score > best_score:
                    best_container = candidate
                    best_score = score

        return best_container

    async def _scroll_results(self, page: Page) -> None:
        """Scroll the job results list to trigger lazy loading."""
        try:
            results_container = await self._get_results_scroll_container(page)
            if results_container:
                stable_rounds = 0
                previous_count = -1
                for _ in range(10):
                    await page.evaluate(
                        """(el) => el.scrollBy(0, 500)""",
                        results_container,
                    )
                    await page.wait_for_timeout(800)
                    current_count = len(await page.query_selector_all(SELECTORS["job_card"]))
                    if current_count == previous_count:
                        stable_rounds += 1
                        if stable_rounds >= 2:
                            break
                    else:
                        stable_rounds = 0
                        previous_count = current_count
        except Exception:
            # Fallback: scroll the entire page
            for _ in range(8):
                await page.keyboard.press("End")
                await page.wait_for_timeout(800)

    async def _random_delay(self) -> None:
        """Random delay to mimic human browsing behavior."""
        import random

        delay = random.uniform(self.min_delay, self.max_delay)
        await asyncio.sleep(delay)

    async def _collect_result_cards(self, page: Page) -> list[RawJob]:
        """Collect result cards while scrolling through LinkedIn's virtualized list."""
        collected: list[RawJob] = []
        seen: set[str] = set()

        async def capture_visible_cards() -> int:
            new_count = 0
            for job in await self._extract_job_cards(page):
                if not job.source_id or job.source_id in seen:
                    continue
                seen.add(job.source_id)
                collected.append(job)
                new_count += 1
            return new_count

        await capture_visible_cards()

        try:
            results_container = await self._get_results_scroll_container(page)
            if results_container:
                stable_rounds = 0
                for _ in range(18):
                    await page.evaluate(
                        """(el) => el.scrollBy(0, 600)""",
                        results_container,
                    )
                    await page.wait_for_timeout(700)
                    if await capture_visible_cards() == 0:
                        stable_rounds += 1
                        if stable_rounds >= 3:
                            break
                    else:
                        stable_rounds = 0
                return _dedupe_jobs(collected)
        except Exception:
            logger.debug("Falling back to full-page result collection", exc_info=True)

        stable_rounds = 0
        for _ in range(18):
            await page.keyboard.press("End")
            await page.wait_for_timeout(700)
            if await capture_visible_cards() == 0:
                stable_rounds += 1
                if stable_rounds >= 3:
                    break
            else:
                stable_rounds = 0

        return _dedupe_jobs(collected)


def _dedupe_jobs(jobs: list[RawJob]) -> list[RawJob]:
    unique: list[RawJob] = []
    seen: set[str] = set()
    for job in jobs:
        if not job.source_id or job.source_id in seen:
            continue
        seen.add(job.source_id)
        unique.append(job)
    return unique


def _extract_job_id_from_url(href: str) -> str | None:
    """Extract LinkedIn job ID from a job URL.

    Examples:
        /jobs/view/1234567890/ -> "1234567890"
        /jobs/view/1234567890?refId=... -> "1234567890"
    """
    match = re.search(r"/jobs/view/(?:[^/?]+-)?(\d+)", href)
    if match:
        return match.group(1)

    match = re.search(r"-(\d+)(?:\?|/|$)", href)
    if match:
        return match.group(1)

    # Also try jobId parameter
    match = re.search(r"currentJobId=(\d+)", href)
    if match:
        return match.group(1)

    return None


def _canonical_linkedin_job_url(source_id: str | None, href: str | None) -> str | None:
    source_id = (source_id or "").strip()
    raw_href = (href or "").strip()

    if source_id:
        return f"{LINKEDIN_BASE}/jobs/view/{source_id}/"

    if not raw_href:
        return None

    if raw_href.startswith("http"):
        return raw_href.split("?")[0]
    if raw_href.startswith("/"):
        return f"{LINKEDIN_BASE}{raw_href.split('?')[0]}"
    return raw_href.split("?")[0]


def _is_known_ats_url(url: str) -> bool:
    """Check if a URL belongs to a known ATS platform."""
    known_patterns = [
        "greenhouse.io",
        "lever.co",
        "ashbyhq.com",
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
    elif "ashbyhq.com" in url_lower:
        return "ashby"
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


def _normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    normalized = url.strip()
    if not normalized or normalized in {"#", "about:blank", "javascript:void(0)", "javascript:;"}:
        return None
    normalized = _unwrap_linkedin_redirect(normalized)
    if normalized.startswith("/"):
        return f"{LINKEDIN_BASE}{normalized}"
    return normalized


def _manual_apply_destination_url(url: str | None, *, source_url: str | None = None) -> str | None:
    """Return a real Apply destination, ignoring LinkedIn job-detail navigation."""
    normalized = _normalize_url(url)
    if not normalized:
        return None

    clean_url = _clean_tracking_url(normalized)
    source_normalized = _normalize_url(source_url)
    if source_normalized and clean_url.rstrip("/") == source_normalized.rstrip("/"):
        return None

    parsed = urlparse(clean_url)
    netloc = parsed.netloc.lower()
    if "linkedin.com" in netloc:
        return None

    return clean_url


def _is_primary_apply_candidate(text: str, aria_label: str, href: str | None) -> bool:
    combined = " ".join(part for part in (text, aria_label) if part).lower()
    href_lower = (href or "").lower()

    if any(
        blocked in href_lower for blocked in ("/jobs/collections/", "/jobs/search/", "/jobs/view/")
    ):
        return False
    if "/safety/go/" in href_lower:
        return True
    if not combined or "apply" not in combined:
        return False
    if "apply on company website" in combined:
        return True

    normalized_text = text.lower().strip()
    if normalized_text in {"apply", "easy apply", "apply now"}:
        return True

    return bool(aria_label and "apply" in aria_label.lower())


def _unwrap_linkedin_redirect(url: str) -> str:
    parsed = urlparse(url)
    is_linkedin_redirect = parsed.path.startswith("/safety/go") and (
        not parsed.netloc or "linkedin.com" in parsed.netloc
    )
    if not is_linkedin_redirect:
        return url

    params = parse_qs(parsed.query)
    destination = params.get("url", [""])[0].strip()
    return destination or url


def _clean_html_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(strip_html(value))).strip()


def _page_has_no_results_text(body_text: str) -> bool:
    normalized = " ".join(body_text.lower().split())
    return any(
        phrase in normalized
        for phrase in (
            "no matching jobs found",
            "no jobs found",
            "try changing your filters",
            "there are no jobs that match your search",
        )
    )


def _summarize_search_page_state(state: dict[str, object] | None) -> str:
    if not state:
        return "unknown state"

    summary = [
        f"status={state.get('status', 'unknown')}",
        f"cards={state.get('card_count', 0)}",
        f"titles={state.get('title_count', 0)}",
    ]
    pagination_text = state.get("pagination_text")
    if pagination_text:
        summary.append(f"pagination={pagination_text}")
    if state.get("has_no_results_text"):
        summary.append("no-results-text=true")
    return ", ".join(summary)


def _normalize_linkedin_title_text(value: str) -> str:
    cleaned = _clean_html_text(value)
    cleaned = re.sub(r"\s+with verification(?:\s+at\s+.+)?$", "", cleaned, flags=re.IGNORECASE)
    parts = cleaned.split()
    if len(parts) >= 6 and len(parts) % 2 == 0:
        midpoint = len(parts) // 2
        if parts[:midpoint] == parts[midpoint:]:
            cleaned = " ".join(parts[:midpoint])
    return cleaned.strip(" -")


def _normalize_job_description_text(value: str | None) -> str | None:
    cleaned = _clean_html_text(value or "")
    if not cleaned:
        return None

    match = re.search(r"about the job\b", cleaned, flags=re.IGNORECASE)
    if match:
        cleaned = cleaned[match.end() :].strip(" :-")

    return cleaned or None


def _extract_html_job_cards(html_text: str, *, search_mode: str) -> list[RawJob]:
    jobs: list[RawJob] = []
    for match in PUBLIC_JOB_CARD_RE.finditer(html_text):
        attrs = match.group("attrs")
        body = match.group("body")
        job = _parse_html_job_card(attrs, body, search_mode=search_mode)
        if job is not None:
            jobs.append(job)
    return jobs


def _extract_public_job_cards(html_text: str) -> list[RawJob]:
    return _extract_html_job_cards(html_text, search_mode="public_guest")


def _parse_html_job_card(attrs: str, body: str, *, search_mode: str) -> RawJob | None:
    source_id_match = PUBLIC_JOB_ID_RE.search(attrs)
    href_match = PUBLIC_JOB_LINK_RE.search(body)
    title_match = PUBLIC_JOB_TITLE_RE.search(body)
    company_match = PUBLIC_JOB_COMPANY_RE.search(body)
    location_match = PUBLIC_JOB_LOCATION_RE.search(body)

    href = html.unescape(href_match.group("value")) if href_match else ""
    source_id = source_id_match.group(1) if source_id_match else _extract_job_id_from_url(href)
    title = _normalize_linkedin_title_text(title_match.group("value")) if title_match else ""
    company = _clean_html_text(company_match.group("value")) if company_match else "Unknown"
    location = _clean_html_text(location_match.group("value")) if location_match else ""

    if not source_id or not title or not href:
        return None

    application_url = _canonical_linkedin_job_url(source_id, href)
    return RawJob(
        source="linkedin",
        source_id=source_id,
        company=company,
        title=title,
        location=location or None,
        employment_type=classify_employment_type(title),
        seniority=classify_seniority(title),
        description=None,
        application_url=application_url,
        ats_type="linkedin",
        raw_data={
            "linkedin_href": application_url,
            "detail_url": application_url,
            "manual_apply_url": application_url,
            "search_mode": search_mode,
        },
    )


async def get_linkedin_session_status(
    session_dir: Path = DEFAULT_SESSION_DIR,
    headless: bool = True,
) -> dict:
    """Return the current LinkedIn session status for the saved browser profile."""
    try:
        async with LinkedInSession(session_dir=session_dir, headless=headless) as session:
            authenticated = await session.is_authenticated()
            has_session_data = session.has_saved_session_data()
    except Exception as exc:
        logger.exception("Failed to inspect LinkedIn session")
        return {
            "ok": False,
            "authenticated": False,
            "has_session_data": False,
            "message": f"Failed to inspect LinkedIn session: {exc}",
            "error": str(exc),
            "error_code": "linkedin_session_status_failed",
        }

    message = (
        "LinkedIn session is ready for authenticated searches."
        if authenticated
        else "LinkedIn session is not authenticated. Connect LinkedIn to sign in."
    )
    return {
        "ok": True,
        "authenticated": authenticated,
        "has_session_data": has_session_data,
        "message": message,
        "error": None,
        "error_code": None,
    }


async def connect_linkedin_session(
    session_dir: Path = DEFAULT_SESSION_DIR,
    timeout_ms: int = 300000,
) -> dict:
    """Open a visible browser and wait for the user to finish LinkedIn login."""
    try:
        async with LinkedInSession(session_dir=session_dir, headless=False) as session:
            authenticated = await session.ensure_logged_in(timeout_ms=timeout_ms)
            has_session_data = session.has_saved_session_data()
    except Exception as exc:
        logger.exception("Failed to connect LinkedIn session")
        return {
            "ok": False,
            "authenticated": False,
            "has_session_data": False,
            "message": f"Failed to open LinkedIn login flow: {exc}",
            "error": str(exc),
            "error_code": "linkedin_session_connect_failed",
        }

    if authenticated:
        return {
            "ok": True,
            "authenticated": True,
            "has_session_data": has_session_data,
            "message": "LinkedIn session connected. Future web searches can run headless.",
            "error": None,
            "error_code": None,
        }

    return {
        "ok": False,
        "authenticated": False,
        "has_session_data": has_session_data,
        "message": "LinkedIn login was not completed before the timeout expired.",
        "error": "LinkedIn login timed out or was cancelled.",
        "error_code": "linkedin_auth_required",
    }


async def _cancel_pending_task(task: asyncio.Task) -> None:
    if task.done():
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def resolve_linkedin_apply_target(
    job_url: str,
    session_dir: Path = DEFAULT_SESSION_DIR,
    headless: bool = True,
) -> dict:
    """Resolve a LinkedIn job page's visible Apply button target."""
    try:
        async with LinkedInScraper(session_dir=session_dir, headless=headless) as scraper:
            manual_apply_url = await scraper.resolve_manual_apply_url(job_url)
    except Exception as exc:
        logger.exception("Failed to resolve LinkedIn apply target")
        return {
            "ok": False,
            "url": job_url,
            "source_url": job_url,
            "ats_url": None,
            "error": str(exc),
            "error_code": "linkedin_apply_target_failed",
        }

    return {
        "ok": True,
        "url": manual_apply_url,
        "source_url": job_url,
        "ats_url": manual_apply_url if _is_known_ats_url(manual_apply_url) else None,
        "error": None,
        "error_code": None,
    }


def clear_linkedin_session(session_dir: Path = DEFAULT_SESSION_DIR) -> dict:
    """Delete the saved LinkedIn browser profile so the user can reconnect cleanly."""
    try:
        if session_dir.exists():
            shutil.rmtree(session_dir)
        return {
            "ok": True,
            "authenticated": False,
            "has_session_data": False,
            "message": "LinkedIn session cleared.",
            "error": None,
            "error_code": None,
        }
    except Exception as exc:
        logger.exception("Failed to clear LinkedIn session")
        return {
            "ok": False,
            "authenticated": False,
            "has_session_data": True,
            "message": f"Failed to clear LinkedIn session: {exc}",
            "error": str(exc),
            "error_code": "linkedin_session_clear_failed",
        }
