"""Lever ATS application adapter.

Lever application forms typically have:
- Standard fields: name, email, phone, location, LinkedIn, etc.
- File upload for resume (drag-drop or click)
- Custom questions below the standard fields
- Form URL: https://jobs.lever.co/{company}/{id}/apply

Lever uses a single-page form layout.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from src.execution.ats.base import BaseATSAdapter
from src.execution.file_uploader import upload_cover_letter, upload_resume
from src.execution.form_filler import (
    detect_fields,
    fill_fields,
    map_fields_to_profile,
)

logger = logging.getLogger("autoapply.execution.ats.lever")


class LeverAdapter(BaseATSAdapter):
    """Application adapter for Lever ATS forms."""

    ats_name = "lever"

    async def fill_form(
        self,
        page: Page,
        profile_data: dict[str, Any],
        qa_responses: dict[str, str] | None = None,
    ) -> tuple[int, int]:
        """Fill Lever application form fields."""
        # Wait for the application form
        await page.wait_for_selector(
            ".application-form, form.application, #application-form",
            timeout=15000,
        )
        await self.browser.delay()

        # Detect and map fields (scoped to the application form)
        fields = await detect_fields(
            page,
            form_selector=".application-form, form.application, #application-form",
        )
        mappings = map_fields_to_profile(fields, profile_data, qa_responses)

        # Fill them
        filled_mappings = await fill_fields(page, mappings)
        filled = sum(1 for m in filled_mappings if m.filled)
        total = len(filled_mappings)

        logger.info("Lever form: filled %d/%d fields", filled, total)
        return filled, total

    async def upload_files(
        self,
        page: Page,
        resume_path: Path | None = None,
        cover_letter_path: Path | None = None,
    ) -> list[str]:
        """Upload files to Lever form.

        Lever typically uses a drag-drop zone or file input for resume upload.
        """
        uploaded = []

        if resume_path:
            # Lever resume upload: often a file input within a drop zone
            success = await upload_resume(
                page,
                resume_path,
                selector=".resume-upload input[type='file'], input[type='file'][name*='resume']",
            )
            if success:
                uploaded.append(resume_path.name)

        if cover_letter_path:
            success = await upload_cover_letter(
                page,
                cover_letter_path,
            )
            if success:
                uploaded.append(cover_letter_path.name)

        return uploaded

    async def answer_questions(
        self,
        page: Page,
        qa_responses: dict[str, str] | None = None,
    ) -> int:
        """Fill Lever custom questions."""
        if not qa_responses:
            return 0

        # Lever custom questions use specific selectors
        custom_fields = await page.query_selector_all(
            ".custom-question input, .custom-question select, "
            ".custom-question textarea, "
            ".additional-info input, .additional-info select"
        )

        answered = 0
        for field in custom_fields:
            label = ""
            el_id = await field.get_attribute("id") or ""
            if el_id:
                label_el = await page.query_selector(f"label[for='{el_id}']")
                if label_el:
                    label = await label_el.inner_text()

            if not label:
                label = await field.get_attribute("aria-label") or ""

            if label:
                for q, a in qa_responses.items():
                    if q.lower() in label.lower() or label.lower() in q.lower():
                        try:
                            tag = await field.evaluate("el => el.tagName.toLowerCase()")
                            if tag == "select":
                                await field.select_option(label=a)
                            else:
                                await field.fill(a)
                            answered += 1
                        except Exception as e:
                            logger.debug("Custom question fill failed: %s", e)
                        break

        return answered

    async def submit(self, page: Page) -> bool:
        """Submit Lever application form."""
        submit_btn = page.locator(
            "button[type='submit']:has-text('Submit'), "
            "button.postings-btn:has-text('Submit'), "
            "input[type='submit']"
        ).first
        await submit_btn.click()
        logger.info("Lever application submitted")

        # Verify: wait for navigation, check for errors
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        error_visible = await page.locator(
            ".error, .alert-danger, [role='alert']:has-text('error')"
        ).first.is_visible()
        if error_visible:
            logger.warning("Error indicator visible after Lever submit")
            return False
        return True
