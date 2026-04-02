"""Playwright browser management.

Handles browser lifecycle, context/session management, screenshots,
and rate-limiting between actions.
"""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

logger = logging.getLogger("autoapply.execution.browser")

DEFAULT_SCREENSHOT_DIR = Path("data/output/screenshots")


class BrowserManager:
    """Manages Playwright browser lifecycle and page contexts.

    Usage:
        async with BrowserManager() as bm:
            page = await bm.new_page()
            await page.goto("https://example.com")
            await bm.screenshot(page, "example")
    """

    def __init__(
        self,
        headless: bool = True,
        min_delay: float = 3.0,
        max_delay: float = 8.0,
        screenshot_dir: Path = DEFAULT_SCREENSHOT_DIR,
        viewport: dict[str, int] | None = None,
    ):
        self.headless = headless
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.screenshot_dir = screenshot_dir
        self.viewport = viewport or {"width": 1280, "height": 900}

        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def __aenter__(self) -> BrowserManager:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def start(self) -> None:
        """Launch browser and create default context."""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._context = await self._browser.new_context(
            viewport=self.viewport,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            java_script_enabled=True,
        )
        logger.info("Browser started (headless=%s)", self.headless)

    async def close(self) -> None:
        """Shut down browser and playwright."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("Browser closed")

    async def new_page(self) -> Page:
        """Open a new page in the current context."""
        if not self._context:
            raise RuntimeError("Browser not started — call start() or use async with")
        page = await self._context.new_page()
        return page

    async def goto(self, page: Page, url: str, wait_until: str = "domcontentloaded") -> None:
        """Navigate to a URL with rate-limiting delay."""
        await self.delay()
        await page.goto(url, wait_until=wait_until, timeout=30000)
        logger.debug("Navigated to %s", url)

    async def delay(self) -> None:
        """Random delay between actions to mimic human behavior."""
        wait = random.uniform(self.min_delay, self.max_delay)
        await asyncio.sleep(wait)

    async def screenshot(
        self,
        page: Page,
        name: str,
        job_id: str = "",
    ) -> Path:
        """Take a screenshot and save to the screenshot directory.

        Args:
            page: The page to screenshot.
            name: Descriptive name for the screenshot (e.g., "form_filled").
            job_id: Optional job ID prefix for organization.

        Returns:
            Path to the saved screenshot.
        """
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{job_id[:8]}_" if job_id else ""
        path = self.screenshot_dir / f"{prefix}{name}.png"
        await page.screenshot(path=str(path), full_page=True)
        logger.debug("Screenshot saved: %s", path)
        return path

    async def get_page_text(self, page: Page) -> str:
        """Get visible text content of the page."""
        return await page.inner_text("body")
