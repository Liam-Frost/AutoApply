"""Base ATS application adapter.

Defines the interface that all ATS-specific adapters must implement.
Each adapter encapsulates the form-filling workflow for a specific ATS.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.async_api import Page

from src.core.state_machine import ApplicationState, AppStatus
from src.execution.browser import BrowserManager

logger = logging.getLogger("autoapply.execution.ats.base")


@dataclass
class ApplicationResult:
    """Result of an application attempt."""

    job_id: str
    status: AppStatus = AppStatus.DISCOVERED
    screenshots: list[Path] = field(default_factory=list)
    fields_filled: int = 0
    fields_total: int = 0
    files_uploaded: list[str] = field(default_factory=list)
    qa_answered: int = 0
    error: str = ""


class BaseATSAdapter(ABC):
    """Abstract base for ATS-specific application adapters.

    Each adapter implements the form-filling workflow for one ATS:
    open form → fill fields → upload files → answer questions → stop before submit.
    """

    ats_name: str = "unknown"

    def __init__(self, browser: BrowserManager):
        self.browser = browser

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
    ) -> ApplicationResult:
        """Execute the full application workflow.

        Default implementation follows the state machine:
        FORM_OPENED → FIELDS_MAPPED → FILES_UPLOADED → QUESTIONS_ANSWERED
        → REVIEW_REQUIRED (or SUBMITTED if auto_submit=True)

        Override individual steps in subclasses for ATS-specific behavior.
        """
        result = ApplicationResult(job_id=state.job_id)

        try:
            # Step 1: Open the application form
            await self.browser.goto(page, application_url)
            state.transition(AppStatus.FORM_OPENED)
            result.screenshots.append(
                await self.browser.screenshot(page, "form_opened", state.job_id)
            )

            # Step 2: Fill form fields
            fields_filled, fields_total = await self.fill_form(page, profile_data, qa_responses)
            state.transition(AppStatus.FIELDS_MAPPED, fields_filled=fields_filled)
            result.fields_filled = fields_filled
            result.fields_total = fields_total
            result.screenshots.append(
                await self.browser.screenshot(page, "fields_mapped", state.job_id)
            )

            # Step 3: Upload files
            uploaded = await self.upload_files(page, resume_path, cover_letter_path)
            if resume_path and not any(
                "resume" in f.lower() or resume_path.name in f for f in uploaded
            ):
                logger.warning("[%s] Resume upload may have failed", state.job_id[:8])
            state.transition(AppStatus.FILES_UPLOADED, files=uploaded)
            result.files_uploaded = uploaded
            result.screenshots.append(
                await self.browser.screenshot(page, "files_uploaded", state.job_id)
            )

            # Step 4: Answer questions (if any remain)
            qa_count = await self.answer_questions(page, qa_responses)
            state.transition(AppStatus.QUESTIONS_ANSWERED, qa_count=qa_count)
            result.qa_answered = qa_count

            # Step 5: Review or submit
            if auto_submit:
                submit_ok = await self.submit(page)
                if submit_ok:
                    state.transition(AppStatus.SUBMITTED)
                    result.status = AppStatus.SUBMITTED
                else:
                    state.transition(AppStatus.REVIEW_REQUIRED)
                    result.status = AppStatus.REVIEW_REQUIRED
                    logger.warning(
                        "[%s] Submit may have failed — flagged for review", state.job_id[:8]
                    )
            else:
                state.transition(AppStatus.REVIEW_REQUIRED)
                result.status = AppStatus.REVIEW_REQUIRED
                result.screenshots.append(
                    await self.browser.screenshot(page, "review_required", state.job_id)
                )
                logger.info("[%s] Paused for review — not auto-submitting", state.job_id[:8])

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            state.fail(error_msg)
            result.status = AppStatus.FAILED
            result.error = error_msg
            logger.error("[%s] Application failed: %s", state.job_id[:8], error_msg)
            try:
                result.screenshots.append(
                    await self.browser.screenshot(page, "error", state.job_id)
                )
            except Exception:
                pass

        return result

    @abstractmethod
    async def fill_form(
        self,
        page: Page,
        profile_data: dict[str, Any],
        qa_responses: dict[str, str] | None = None,
    ) -> tuple[int, int]:
        """Fill the application form fields.

        Returns:
            (fields_filled, fields_total)
        """

    @abstractmethod
    async def upload_files(
        self,
        page: Page,
        resume_path: Path | None = None,
        cover_letter_path: Path | None = None,
    ) -> list[str]:
        """Upload resume and cover letter.

        Returns:
            List of uploaded file descriptions (e.g., ["resume.pdf"]).
        """

    async def answer_questions(
        self,
        page: Page,
        qa_responses: dict[str, str] | None = None,
    ) -> int:
        """Fill any remaining quick questions on the form.

        Default: no-op. Override in subclasses with ATS-specific logic.
        Returns number of questions answered.
        """
        return 0

    async def submit(self, page: Page) -> bool:
        """Click the submit button and verify submission.

        Returns True if submission appears successful, False otherwise.
        Override per ATS for specific confirmation checks.
        """
        submit_btn = page.locator(
            "button[type='submit'], input[type='submit'], "
            "button:has-text('Submit'), button:has-text('Apply')"
        ).first
        await submit_btn.click()
        logger.info("Submit button clicked")

        # Basic verification: wait for navigation or confirmation element
        try:
            await page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass  # Some forms don't trigger navigation

        # Check for common error indicators
        error_visible = await page.locator(
            ".error, .alert-danger, [role='alert']:has-text('error')"
        ).first.is_visible()
        if error_visible:
            logger.warning("Error indicator visible after submit")
            return False

        return True
