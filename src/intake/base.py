"""Base scraper interface.

Every ATS scraper inherits from BaseScraper and implements `fetch_jobs`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

from src.intake.schema import RawJob

logger = logging.getLogger("autoapply.intake")

DEFAULT_TIMEOUT = 30
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AutoApply/0.1; job-research-bot)",
    "Accept": "application/json",
}


class ScraperError(Exception):
    """Raised when a scraper cannot fetch or parse jobs."""


class BaseScraper(ABC):
    """Abstract base for all ATS scrapers."""

    source_name: str = "unknown"

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self._client = httpx.Client(
            timeout=timeout,
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BaseScraper:
        return self

    def __exit__(self, *_) -> None:
        self.close()

    @abstractmethod
    def fetch_jobs(self, company_slug: str) -> list[RawJob]:
        """Fetch all open jobs for a given company slug.

        Args:
            company_slug: The company's identifier on this ATS (e.g. "stripe").

        Returns:
            List of normalized RawJob objects.
        """

    def _get(self, url: str, **kwargs) -> httpx.Response:
        """Perform a GET request with basic error handling."""
        try:
            resp = self._client.get(url, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            raise ScraperError(f"HTTP {e.response.status_code} from {url}") from e
        except httpx.RequestError as e:
            raise ScraperError(f"Request failed for {url}: {e}") from e
