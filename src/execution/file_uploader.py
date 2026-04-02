"""File upload handler for ATS application forms.

Handles resume and cover letter file uploads via Playwright's
file chooser API. Supports common file input patterns across ATS.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from playwright.async_api import Page

logger = logging.getLogger("autoapply.execution.file_uploader")


async def upload_resume(
    page: Page,
    file_path: Path,
    selector: str | None = None,
) -> bool:
    """Upload a resume file to the application form.

    Args:
        page: The page with the upload form.
        file_path: Path to the resume file (.pdf or .docx).
        selector: CSS selector for the file input. If None, auto-detects.

    Returns:
        True if upload succeeded, False otherwise.
    """
    return await _upload_file(page, file_path, selector, file_type="resume")


async def upload_cover_letter(
    page: Page,
    file_path: Path,
    selector: str | None = None,
) -> bool:
    """Upload a cover letter file to the application form."""
    return await _upload_file(page, file_path, selector, file_type="cover_letter")


async def _upload_file(
    page: Page,
    file_path: Path,
    selector: str | None,
    file_type: str,
) -> bool:
    """Upload a file to a file input element.

    Tries multiple strategies:
    1. Direct set_input_files on the given selector
    2. Auto-detect file inputs by label
    3. Click-to-open file chooser pattern
    """
    if not file_path.exists():
        logger.error("File not found: %s", file_path)
        return False

    file_str = str(file_path.resolve())

    # Strategy 1: Use provided selector
    if selector:
        try:
            await page.set_input_files(selector, file_str)
            logger.info("Uploaded %s via selector: %s", file_type, selector)
            return True
        except Exception as e:
            logger.debug("Selector upload failed: %s", e)

    # Strategy 2: Auto-detect file inputs
    file_inputs = await page.query_selector_all("input[type='file']")
    if not file_inputs:
        logger.warning("No file input elements found on page")
        return False

    # Try to match by label
    target = await _find_file_input_by_label(page, file_inputs, file_type)
    if target is None and file_inputs:
        # Fall back to first (for resume) or second (for cover letter) input
        if file_type == "resume":
            target = file_inputs[0]
        elif len(file_inputs) > 1:
            target = file_inputs[1]
        else:
            target = file_inputs[0]

    if target:
        try:
            await target.set_input_files(file_str)
            logger.info("Uploaded %s via auto-detected input", file_type)
            return True
        except Exception as e:
            logger.warning("Auto-detected upload failed: %s", e)

    # Strategy 3: File chooser pattern (click button, handle dialog)
    upload_buttons = await page.query_selector_all(
        "button:has-text('Upload'), button:has-text('Attach'), "
        "[role='button']:has-text('Upload'), [role='button']:has-text('Attach')"
    )
    for btn in upload_buttons:
        try:
            async with page.expect_file_chooser(timeout=5000) as fc_info:
                await btn.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(file_str)
            logger.info("Uploaded %s via file chooser button", file_type)
            return True
        except Exception:
            continue

    logger.warning("All upload strategies failed for %s", file_type)
    return False


async def _find_file_input_by_label(
    page: Page,
    inputs: list,
    file_type: str,
) -> Any | None:
    """Try to match a file input to the intended file type by its label."""
    resume_keywords = ["resume", "cv", "curriculum"]
    cover_keywords = ["cover", "letter", "motivation"]

    keywords = resume_keywords if file_type == "resume" else cover_keywords

    for el in inputs:
        # Check aria-label
        aria = await el.get_attribute("aria-label") or ""
        # Check associated label
        el_id = await el.get_attribute("id")
        label_text = ""
        if el_id:
            label_el = await page.query_selector(f"label[for='{el_id}']")
            if label_el:
                label_text = await label_el.inner_text()

        # Check accept attribute
        accept = await el.get_attribute("accept") or ""

        combined = f"{aria} {label_text} {accept}".lower()
        if any(kw in combined for kw in keywords):
            return el

    return None
