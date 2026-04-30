"""Ashby ATS application adapter.

Ashby application flows typically use a dedicated `/application` page with:
- Contact fields (name, email, phone, location, LinkedIn, GitHub)
- Resume and optional cover letter uploads
- Inline yes/no and text questions
- A review-stage "Submit Application" button
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from src.execution.ats.base import BaseATSAdapter
from src.execution.file_uploader import upload_cover_letter, upload_resume
from src.execution.form_filler import detect_fields, fill_fields, map_fields_to_profile

logger = logging.getLogger("autoapply.execution.ats.ashby")


class AshbyAdapter(BaseATSAdapter):
    """Application adapter for Ashby-hosted application pages."""

    ats_name = "ashby"

    async def fill_form(
        self,
        page: Page,
        profile_data: dict[str, Any],
        qa_responses: dict[str, str] | None = None,
    ) -> tuple[int, int]:
        await page.wait_for_selector(
            "input[name='_systemfield_name'], input[name='_systemfield_email'], "
            "button:has-text('Submit Application')",
            timeout=15000,
        )
        await self.browser.delay()

        fields = await detect_fields(page)
        mappings = map_fields_to_profile(fields, profile_data, qa_responses)
        filled_mappings = await fill_fields(page, mappings)
        filled = sum(1 for mapping in filled_mappings if mapping.filled)
        total = len(filled_mappings)

        logger.info("Ashby form: filled %d/%d fields", filled, total)
        return filled, total

    async def upload_files(
        self,
        page: Page,
        resume_path: Path | None = None,
        cover_letter_path: Path | None = None,
    ) -> list[str]:
        uploaded: list[str] = []

        if resume_path:
            success = await upload_resume(
                page,
                resume_path,
                selector="input[type='file']#_systemfield_resume, input[type='file'][id*='resume']",
            )
            if success:
                uploaded.append(resume_path.name)

        if cover_letter_path:
            success = await upload_cover_letter(page, cover_letter_path)
            if success:
                uploaded.append(cover_letter_path.name)

        return uploaded

    async def submit(self, page: Page) -> bool:
        submit_btn = page.locator("button:has-text('Submit Application')").first
        await submit_btn.click()
        logger.info("Ashby application submitted")

        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        error_visible = await page.locator(
            ".error, .alert-danger, [role='alert']:has-text('error')"
        ).first.is_visible()
        if error_visible:
            logger.warning("Error indicator visible after Ashby submit")
            return False
        return True
