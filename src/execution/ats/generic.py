"""Generic application adapter for unknown company/ATS forms.

This adapter is intentionally conservative: it tries to reach an application
surface, fills high-confidence fields, uploads available files, advances simple
multi-step forms, and pauses for review unless explicit auto-submit is enabled.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from src.core.state_machine import ApplicationState, AppStatus
from src.execution.ats.base import ApplicationResult, BaseATSAdapter
from src.execution.file_uploader import upload_cover_letter, upload_resume
from src.execution.form_filler import (
    detect_fields,
    fill_fields,
    map_fields_to_profile,
)
from src.generation.qa_responder import answer_questions

logger = logging.getLogger("autoapply.execution.ats.generic")

APPLY_ENTRY_SELECTORS = [
    "main a:has-text('Apply')",
    "main button:has-text('Apply')",
    "a:has-text('Apply Now')",
    "button:has-text('Apply Now')",
    "a:has-text('Start Application')",
    "button:has-text('Start Application')",
    "a:has-text('Apply for this job')",
    "button:has-text('Apply for this job')",
]

NEXT_STEP_SELECTORS = [
    "button:has-text('Next')",
    "button:has-text('Continue')",
    "button:has-text('Save and continue')",
    "button:has-text('Proceed')",
    "input[type='button'][value*='Next']",
    "input[type='button'][value*='Continue']",
]

HIGH_RISK_LABEL_TERMS = (
    "captcha",
    "recaptcha",
    "password",
    "gender",
    "race",
    "ethnicity",
    "veteran",
    "disability",
    "voluntary self-identification",
    "equal employment opportunity",
)

THIRD_PARTY_APPLY_TERMS = ("linkedin", "indeed", "google", "facebook")


class GenericAdapter(BaseATSAdapter):
    """Best-effort adapter for external application forms without a dedicated ATS adapter."""

    ats_name = "company_site"
    max_steps = 4

    async def apply(
        self,
        page: Page,
        application_url: str,
        state: ApplicationState,
        profile_data: dict[str, Any],
        resume_path: Path | None = None,
        cover_letter_path: Path | None = None,
        qa_responses: dict[str, str] | None = None,
        auto_submit: bool = False,
        job_context: Any | None = None,
    ) -> ApplicationResult:
        result = ApplicationResult(job_id=state.job_id)

        try:
            await self.browser.goto(page, application_url)
            page = await self._open_application_surface(page)
            state.transition(AppStatus.FORM_OPENED)
            result.screenshots.append(
                await self.browser.screenshot(page, "form_opened", state.job_id)
            )

            uploaded_files: list[str] = []
            fields_filled = 0
            fields_total = 0
            qa_answered = 0

            for _ in range(self.max_steps):
                filled, total, answered = await self._fill_current_page(
                    page,
                    profile_data,
                    qa_responses,
                    job_context,
                )
                fields_filled += filled
                fields_total += total
                qa_answered += answered

                for filename in await self.upload_files(page, resume_path, cover_letter_path):
                    if filename not in uploaded_files:
                        uploaded_files.append(filename)

                if not await self._click_next_step(page):
                    break

            state.transition(AppStatus.FIELDS_MAPPED, fields_filled=fields_filled)
            result.fields_filled = fields_filled
            result.fields_total = fields_total
            result.screenshots.append(
                await self.browser.screenshot(page, "fields_mapped", state.job_id)
            )

            state.transition(AppStatus.FILES_UPLOADED, files=uploaded_files)
            result.files_uploaded = uploaded_files
            result.screenshots.append(
                await self.browser.screenshot(page, "files_uploaded", state.job_id)
            )

            state.transition(AppStatus.QUESTIONS_ANSWERED, qa_count=qa_answered)
            result.qa_answered = qa_answered

            if auto_submit and await self._can_submit_safely(page):
                submit_ok = await self.submit(page)
                if submit_ok:
                    state.transition(AppStatus.SUBMITTED)
                    result.status = AppStatus.SUBMITTED
                else:
                    state.transition(AppStatus.REVIEW_REQUIRED)
                    result.status = AppStatus.REVIEW_REQUIRED
            else:
                state.transition(AppStatus.REVIEW_REQUIRED)
                result.status = AppStatus.REVIEW_REQUIRED
                result.screenshots.append(
                    await self.browser.screenshot(page, "review_required", state.job_id)
                )

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            state.fail(error_msg)
            result.status = AppStatus.FAILED
            result.error = error_msg
            logger.error("[%s] Generic application failed: %s", state.job_id[:8], error_msg)
            with suppress(Exception):
                result.screenshots.append(
                    await self.browser.screenshot(page, "error", state.job_id)
                )

        return result

    async def fill_form(
        self,
        page: Page,
        profile_data: dict[str, Any],
        qa_responses: dict[str, str] | None = None,
    ) -> tuple[int, int]:
        filled, total, _ = await self._fill_current_page(page, profile_data, qa_responses, None)
        return filled, total

    async def upload_files(
        self,
        page: Page,
        resume_path: Path | None = None,
        cover_letter_path: Path | None = None,
    ) -> list[str]:
        uploaded: list[str] = []
        if resume_path and await upload_resume(page, resume_path):
            uploaded.append(resume_path.name)
        if cover_letter_path and await upload_cover_letter(page, cover_letter_path):
            uploaded.append(cover_letter_path.name)
        return uploaded

    async def submit(self, page: Page) -> bool:
        submit_btn = await self._first_visible_locator(
            page,
            [
                "button[type='submit']:has-text('Submit')",
                "button:has-text('Submit Application')",
                "button:has-text('Send Application')",
                "input[type='submit']",
            ],
        )
        if submit_btn is None:
            return False

        await submit_btn.click()
        with suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=10000)

        return not await self._has_error_indicator(page)

    async def _open_application_surface(self, page: Page) -> Page:
        if await self._has_application_controls(page):
            return page

        entry = await self._first_visible_locator(page, APPLY_ENTRY_SELECTORS)
        if entry is None:
            return page

        text = await self._locator_text(entry)
        if any(term in text.lower() for term in THIRD_PARTY_APPLY_TERMS):
            return page

        existing_pages = set(page.context.pages)
        popup_task = asyncio.create_task(page.wait_for_event("popup", timeout=5000))
        new_page_task = asyncio.create_task(
            page.context.wait_for_event(
                "page",
                predicate=lambda candidate: candidate not in existing_pages,
                timeout=5000,
            )
        )

        try:
            await entry.click()
            with suppress(Exception):
                await page.wait_for_load_state("networkidle", timeout=8000)

            for task in (popup_task, new_page_task):
                if not task.done():
                    continue
                with suppress(Exception):
                    opened_page = task.result()
                    await opened_page.wait_for_load_state("domcontentloaded", timeout=8000)
                    return opened_page
        finally:
            await self._cancel_task(popup_task)
            await self._cancel_task(new_page_task)

        return page

    async def _fill_current_page(
        self,
        page: Page,
        profile_data: dict[str, Any],
        qa_responses: dict[str, str] | None,
        job_context: Any | None,
    ) -> tuple[int, int, int]:
        fields = [
            field
            for field in await detect_fields(page)
            if field.field_type != "file" and not self._is_high_risk_label(field.label)
        ]
        dynamic_qa = self._build_dynamic_qa_responses(fields, profile_data, job_context)
        combined_qa = {**(qa_responses or {}), **dynamic_qa}

        mappings = map_fields_to_profile(fields, profile_data, combined_qa or None)
        filled_mappings = await fill_fields(page, mappings)
        filled = sum(1 for mapping in filled_mappings if mapping.filled)
        answered = sum(
            1
            for mapping in filled_mappings
            if mapping.filled and mapping.form_field.label in dynamic_qa
        )
        return filled, len(filled_mappings), answered

    def _build_dynamic_qa_responses(
        self,
        fields,
        profile_data: dict[str, Any],
        job_context: Any | None,
    ) -> dict[str, str]:
        if job_context is None:
            return {}

        labels = [field.label for field in fields if field.label]
        if not labels:
            return {}

        qa_entries = [
            entry
            for entry in profile_data.get("qa_bank", [])
            if isinstance(entry, dict) and entry.get("question_pattern")
        ]
        responses = answer_questions(
            questions=labels,
            job=job_context,
            profile_data=profile_data,
            qa_entries=qa_entries,
            use_llm=False,
        )
        return {
            response.question: response.answer
            for response in responses
            if response.answer and not response.needs_review
        }

    async def _click_next_step(self, page: Page) -> bool:
        next_btn = await self._first_visible_locator(page, NEXT_STEP_SELECTORS)
        if next_btn is None:
            return False

        text = await self._locator_text(next_btn)
        if any(blocked in text.lower() for blocked in ("submit", "apply")):
            return False

        await next_btn.click()
        with suppress(Exception):
            await page.wait_for_load_state("networkidle", timeout=8000)
        await self.browser.delay()
        return True

    async def _can_submit_safely(self, page: Page) -> bool:
        return await self._visible_required_empty_count(page) == 0

    async def _has_application_controls(self, page: Page) -> bool:
        return await page.evaluate(
            """() => Array.from(document.querySelectorAll(
                "input:not([type='hidden']):not([type='submit']):not([type='button']), " +
                "textarea, select"
            )).some((el) => {
                const style = window.getComputedStyle(el);
                return style && style.visibility !== 'hidden' && style.display !== 'none';
            })"""
        )

    async def _visible_required_empty_count(self, page: Page) -> int:
        return await page.evaluate(
            """() => Array.from(document.querySelectorAll("input, textarea, select"))
                .filter((el) => el.required || el.getAttribute('aria-required') === 'true')
                .filter((el) => {
                    const style = window.getComputedStyle(el);
                    return style && style.visibility !== 'hidden' && style.display !== 'none';
                })
                .filter((el) => {
                    if (el.type === 'checkbox' || el.type === 'radio') {
                        return !el.checked;
                    }
                    return !String(el.value || '').trim();
                }).length"""
        )

    async def _has_error_indicator(self, page: Page) -> bool:
        return await page.locator(
            ".error, .alert-danger, [role='alert']:has-text('error'), "
            ":text('required field')"
        ).first.is_visible()

    async def _first_visible_locator(self, page: Page, selectors: list[str]):
        for selector in selectors:
            locator = page.locator(selector)
            count = min(await locator.count(), 10)
            for index in range(count):
                candidate = locator.nth(index)
                try:
                    if await candidate.is_visible() and await candidate.is_enabled():
                        return candidate
                except Exception:
                    continue
        return None

    async def _locator_text(self, locator) -> str:
        with suppress(Exception):
            return (await locator.inner_text(timeout=1000)).strip()
        with suppress(Exception):
            return (await locator.get_attribute("value") or "").strip()
        return ""

    def _is_high_risk_label(self, label: str) -> bool:
        lower = (label or "").lower()
        return any(term in lower for term in HIGH_RISK_LABEL_TERMS)

    async def _cancel_task(self, task: asyncio.Task) -> None:
        if task.done():
            with suppress(Exception, asyncio.CancelledError):
                task.result()
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
