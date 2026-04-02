"""Greenhouse ATS application adapter.

Greenhouse application forms typically have:
- Direct field inputs (name, email, phone, location, LinkedIn, etc.)
- File upload for resume (required) and cover letter (optional)
- Custom questions at the bottom
- A single-page form with "Submit Application" button

Form URL pattern: https://boards.greenhouse.io/{company}/jobs/{id}#app
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

logger = logging.getLogger("autoapply.execution.ats.greenhouse")


class GreenhouseAdapter(BaseATSAdapter):
    """Application adapter for Greenhouse ATS forms."""

    ats_name = "greenhouse"

    async def fill_form(
        self,
        page: Page,
        profile_data: dict[str, Any],
        qa_responses: dict[str, str] | None = None,
    ) -> tuple[int, int]:
        """Fill Greenhouse application form fields."""
        # Wait for the form to load
        await page.wait_for_selector(
            "#application_form, form[action*='applications'], #application",
            timeout=15000,
        )
        await self.browser.delay()

        # Detect and map fields
        fields = await detect_fields(page)
        mappings = map_fields_to_profile(fields, profile_data, qa_responses)

        # Fill them
        filled_mappings = await fill_fields(page, mappings)
        filled = sum(1 for m in filled_mappings if m.filled)
        total = len(filled_mappings)

        logger.info("Greenhouse form: filled %d/%d fields", filled, total)
        return filled, total

    async def upload_files(
        self,
        page: Page,
        resume_path: Path | None = None,
        cover_letter_path: Path | None = None,
    ) -> list[str]:
        """Upload files to Greenhouse form.

        Greenhouse typically has:
        - #resume_file_input or input[name*='resume']
        - #cover_letter_file_input or input[name*='cover']
        """
        uploaded = []

        if resume_path:
            success = await upload_resume(
                page, resume_path,
                selector="input[type='file'][id*='resume'], input[type='file'][name*='resume']",
            )
            if success:
                uploaded.append(resume_path.name)

        if cover_letter_path:
            success = await upload_cover_letter(
                page, cover_letter_path,
                selector="input[type='file'][id*='cover'], input[type='file'][name*='cover']",
            )
            if success:
                uploaded.append(cover_letter_path.name)

        return uploaded

    async def answer_questions(
        self,
        page: Page,
        qa_responses: dict[str, str] | None = None,
    ) -> int:
        """Fill custom questions on Greenhouse forms.

        Greenhouse custom questions appear as additional fields below the
        standard form fields. They've already been detected and filled
        by fill_form if qa_responses was provided, so this handles any
        remaining questions.
        """
        if not qa_responses:
            return 0

        # Look for unfilled custom question fields
        custom_fields = await page.query_selector_all(
            ".custom-question input, .custom-question select, "
            ".custom-question textarea, "
            "[data-field-type='custom'] input, [data-field-type='custom'] select"
        )

        answered = 0
        for field in custom_fields:
            label = await field.get_attribute("aria-label") or ""
            if not label:
                el_id = await field.get_attribute("id") or ""
                if el_id:
                    label_el = await page.query_selector(f"label[for='{el_id}']")
                    if label_el:
                        label = await label_el.inner_text()

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

    async def submit(self, page: Page) -> None:
        """Submit Greenhouse application form."""
        submit_btn = page.locator(
            "#submit_app, button[type='submit']:has-text('Submit'), "
            "input[type='submit'][value*='Submit']"
        ).first
        await submit_btn.click()
        logger.info("Greenhouse application submitted")
