"""Rate limiter for browser automation actions.

Controls the pace of automated interactions to avoid detection and
respect target site rate limits. Supports per-action delays, error
cooldowns, and hourly application caps.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field

logger = logging.getLogger("autoapply.utils.rate_limiter")


@dataclass
class RateLimiterConfig:
    """Rate limiter configuration."""

    min_delay: float = 3.0  # seconds between browser actions
    max_delay: float = 8.0
    cooldown_on_error: float = 60.0  # seconds to wait after an error
    max_applications_per_hour: int = 15


class RateLimiter:
    """Controls pacing for browser automation actions.

    Usage::

        limiter = RateLimiter(config)
        await limiter.wait()          # delay before next action
        await limiter.error_cooldown() # longer pause after failure
        if not limiter.can_apply():    # check hourly cap
            ...
    """

    def __init__(self, config: RateLimiterConfig | None = None):
        self.config = config or RateLimiterConfig()
        self._application_timestamps: list[float] = []
        self._last_action_time: float = 0.0

    async def wait(self) -> float:
        """Wait a random delay between actions.

        Returns the actual delay in seconds.
        """
        delay = random.uniform(self.config.min_delay, self.config.max_delay)

        # Ensure minimum gap since last action
        elapsed = time.monotonic() - self._last_action_time
        if elapsed < delay:
            actual_delay = delay - elapsed
            await asyncio.sleep(actual_delay)
        else:
            actual_delay = 0.0

        self._last_action_time = time.monotonic()
        return actual_delay

    async def error_cooldown(self) -> None:
        """Wait after an error before retrying."""
        logger.info(
            "Error cooldown: waiting %.0fs", self.config.cooldown_on_error
        )
        await asyncio.sleep(self.config.cooldown_on_error)
        self._last_action_time = time.monotonic()

    def can_apply(self) -> bool:
        """Check if we're within the hourly application cap."""
        now = time.monotonic()
        cutoff = now - 3600  # 1 hour window
        # Prune old timestamps
        self._application_timestamps = [
            ts for ts in self._application_timestamps if ts > cutoff
        ]
        return len(self._application_timestamps) < self.config.max_applications_per_hour

    def record_application(self) -> None:
        """Record that an application was submitted."""
        self._application_timestamps.append(time.monotonic())

    @property
    def applications_this_hour(self) -> int:
        """Number of applications submitted in the last hour."""
        now = time.monotonic()
        cutoff = now - 3600
        self._application_timestamps = [
            ts for ts in self._application_timestamps if ts > cutoff
        ]
        return len(self._application_timestamps)

    @property
    def remaining_this_hour(self) -> int:
        """How many more applications we can submit this hour."""
        return max(0, self.config.max_applications_per_hour - self.applications_this_hour)
