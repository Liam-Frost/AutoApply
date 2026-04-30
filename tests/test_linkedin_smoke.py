"""Opt-in live smoke tests for real LinkedIn search behavior."""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("AUTOAPPLY_LIVE_LINKEDIN_SMOKE") != "1",
    reason="set AUTOAPPLY_LIVE_LINKEDIN_SMOKE=1 to run live LinkedIn smoke tests",
)


@pytest.mark.asyncio
async def test_live_linkedin_search_smoke():
    from src.intake.search import search_linkedin

    jobs = await search_linkedin(
        keywords=os.getenv("AUTOAPPLY_LIVE_LINKEDIN_KEYWORD", "software engineer"),
        location=os.getenv("AUTOAPPLY_LIVE_LINKEDIN_LOCATION", "United States"),
        time_filter=os.getenv("AUTOAPPLY_LIVE_LINKEDIN_TIME_FILTER", "week"),
        max_pages=1,
        enrich_details=False,
        headless=True,
        allow_public_fallback=True,
    )

    assert jobs, "Expected at least one live LinkedIn result"
    first_job = jobs[0]
    assert first_job.source == "linkedin"
    assert first_job.source_id
    assert first_job.title
    assert first_job.application_url
