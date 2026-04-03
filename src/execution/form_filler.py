"""Form field detection and filling.

Identifies form fields on ATS application pages, maps them to applicant
data, and fills them in. Handles common field types: text, select, radio,
checkbox, textarea.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page

logger = logging.getLogger("autoapply.execution.form_filler")


@dataclass
class FormField:
    """A detected form field with its label and type."""

    selector: str
    label: str = ""
    field_type: str = "text"  # text, select, radio, checkbox, textarea, file
    required: bool = False
    options: list[str] = field(default_factory=list)  # For select/radio
    value: str = ""  # Current or intended value


@dataclass
class FieldMapping:
    """Maps a form field to an applicant data key."""

    form_field: FormField
    data_key: str  # Key in the applicant data dict
    value: str = ""
    filled: bool = False
    error: str = ""


async def detect_fields(page: Page, form_selector: str | None = None) -> list[FormField]:
    """Detect all fillable form fields on the current page.

    Scans for input, select, and textarea elements, extracting labels
    and field metadata.

    Args:
        page: The page to scan.
        form_selector: Optional CSS selector to scope detection to a specific
            form container. If None, scans the entire page.
    """
    fields = []
    container = page
    if form_selector:
        form_el = await page.query_selector(form_selector)
        if form_el:
            container = form_el

    # Text inputs and textareas
    inputs = await container.query_selector_all(
        "input[type='text'], input[type='email'], input[type='tel'], "
        "input[type='url'], input[type='number'], input:not([type]), textarea"
    )
    for el in inputs:
        label = await _get_field_label(page, el)
        field_type = await el.get_attribute("type") or "text"
        tag = await el.evaluate("el => el.tagName.toLowerCase()")
        if tag == "textarea":
            field_type = "textarea"
        required = await el.get_attribute("required") is not None
        selector = await _build_selector(el)

        fields.append(FormField(
            selector=selector,
            label=label,
            field_type=field_type,
            required=required,
        ))

    # Checkboxes
    checkboxes = await container.query_selector_all("input[type='checkbox']")
    for el in checkboxes:
        label = await _get_field_label(page, el)
        selector = await _build_selector(el)
        fields.append(FormField(
            selector=selector,
            label=label,
            field_type="checkbox",
        ))

    # Radio buttons (grouped by name)
    radios = await container.query_selector_all("input[type='radio']")
    seen_radio_names: set[str] = set()
    for el in radios:
        name = await el.get_attribute("name") or ""
        if name in seen_radio_names:
            continue
        seen_radio_names.add(name)
        label = await _get_field_label(page, el)
        # Collect option labels for the radio group
        group_els = await container.query_selector_all(f"input[type='radio'][name='{_css_escape(name)}']") if name else [el]
        options = []
        for radio_el in group_els:
            opt_label = await _get_field_label(page, radio_el)
            val = await radio_el.get_attribute("value") or ""
            options.append(opt_label or val)
        selector = await _build_selector(el)
        fields.append(FormField(
            selector=selector,
            label=label,
            field_type="radio",
            options=options,
        ))

    # Select dropdowns
    selects = await container.query_selector_all("select")
    for el in selects:
        label = await _get_field_label(page, el)
        selector = await _build_selector(el)
        options = await el.evaluate(
            "el => Array.from(el.options).map(o => o.text.trim())"
        )
        fields.append(FormField(
            selector=selector,
            label=label,
            field_type="select",
            options=options,
        ))

    # File inputs
    file_inputs = await container.query_selector_all("input[type='file']")
    for el in file_inputs:
        label = await _get_field_label(page, el)
        selector = await _build_selector(el)
        fields.append(FormField(
            selector=selector,
            label=label,
            field_type="file",
        ))

    logger.info("Detected %d form fields", len(fields))
    return fields


async def fill_fields(
    page: Page,
    mappings: list[FieldMapping],
    delay_ms: int = 50,
) -> list[FieldMapping]:
    """Fill form fields based on mappings.

    Args:
        page: The page containing the form.
        mappings: List of field-to-value mappings.
        delay_ms: Typing delay per character (milliseconds) for human simulation.

    Returns:
        Updated mappings with filled status and any errors.
    """
    for mapping in mappings:
        if not mapping.value:
            continue

        try:
            field = mapping.form_field
            el = page.locator(field.selector)

            if field.field_type in ("text", "email", "tel", "url", "number"):
                await el.clear()
                await el.type(mapping.value, delay=delay_ms)
                mapping.filled = True

            elif field.field_type == "textarea":
                await el.clear()
                await el.type(mapping.value, delay=delay_ms)
                mapping.filled = True

            elif field.field_type == "select":
                await el.select_option(label=mapping.value)
                mapping.filled = True

            elif field.field_type == "checkbox":
                is_checked = await el.is_checked()
                should_check = mapping.value.lower() in ("true", "yes", "1")
                if is_checked != should_check:
                    await el.click()
                mapping.filled = True

            elif field.field_type == "radio":
                await el.click()
                mapping.filled = True

            else:
                mapping.error = f"Unsupported field type: {field.field_type}"

            logger.debug("Filled '%s' = '%s'", field.label, mapping.value[:50])

        except Exception as e:
            mapping.error = str(e)
            logger.warning("Failed to fill '%s': %s", mapping.form_field.label, e)

    filled_count = sum(1 for m in mappings if m.filled)
    logger.info("Filled %d/%d fields", filled_count, len(mappings))
    return mappings


def map_fields_to_profile(
    fields: list[FormField],
    profile_data: dict[str, Any],
    qa_responses: dict[str, str] | None = None,
) -> list[FieldMapping]:
    """Auto-map detected form fields to applicant profile data.

    Uses label matching to determine which profile field maps to each form field.
    """
    identity = profile_data.get("identity", {})
    education = profile_data.get("education", [])
    first_edu = education[0] if education else {}

    # Label → value mapping rules (case-insensitive label substring match)
    label_rules: list[tuple[list[str], str]] = [
        (["first name", "given name"], identity.get("full_name", "").split()[0] if identity.get("full_name") else ""),
        (["last name", "family name", "surname"], " ".join(identity.get("full_name", "").split()[1:]) if identity.get("full_name") else ""),
        (["full name", "your name"], identity.get("full_name", "")),
        (["email"], identity.get("email", "")),
        (["phone", "mobile", "telephone"], identity.get("phone", "")),
        (["linkedin"], identity.get("linkedin_url", "")),
        (["github"], identity.get("github_url", "")),
        (["portfolio", "website", "personal site"], identity.get("portfolio_url", "")),
        (["location", "city", "address"], identity.get("location", "")),
        (["university", "school", "institution"], first_edu.get("institution", "")),
        (["degree"], first_edu.get("degree", "")),
        (["major", "field of study", "discipline"], first_edu.get("field", "")),
        (["gpa", "grade"], first_edu.get("gpa", "")),
    ]

    mappings = []
    for form_field in fields:
        if form_field.field_type == "file":
            continue  # File uploads handled separately

        label_lower = form_field.label.lower()
        matched_value = ""

        # Try label rules
        for keywords, value in label_rules:
            if any(kw in label_lower for kw in keywords):
                matched_value = value
                break

        # Try QA responses
        if not matched_value and qa_responses:
            for q_pattern, answer in qa_responses.items():
                if q_pattern.lower() in label_lower or label_lower in q_pattern.lower():
                    matched_value = answer
                    break

        data_key = _infer_data_key(label_lower)
        mappings.append(FieldMapping(
            form_field=form_field,
            data_key=data_key,
            value=matched_value,
        ))

    mapped_count = sum(1 for m in mappings if m.value)
    logger.info("Mapped %d/%d fields to profile data", mapped_count, len(mappings))
    return mappings


async def _get_field_label(page: Page, element) -> str:
    """Extract the label text for a form element."""
    # Try aria-label
    aria = await element.get_attribute("aria-label")
    if aria:
        return aria.strip()

    # Try associated <label> via id
    el_id = await element.get_attribute("id")
    if el_id:
        label_el = await page.query_selector(f"label[for='{_css_escape(el_id)}']")
        if label_el:
            text = await label_el.inner_text()
            if text.strip():
                return text.strip()

    # Try placeholder
    placeholder = await element.get_attribute("placeholder")
    if placeholder:
        return placeholder.strip()

    # Try name attribute
    name = await element.get_attribute("name")
    if name:
        return name.replace("_", " ").replace("-", " ").strip()

    return ""


def _css_escape(value: str) -> str:
    """Escape a string for safe use in CSS attribute selectors."""
    return value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')


async def _build_selector(element) -> str:
    """Build a unique CSS selector for an element.

    Constructs a fully qualified path from the element up through
    its ancestors to ensure global uniqueness.
    """
    # Prefer id (globally unique)
    el_id = await element.get_attribute("id")
    if el_id:
        return f"#{_css_escape(el_id)}"

    # Prefer name + tag (usually unique within a form)
    name = await element.get_attribute("name")
    tag = await element.evaluate("el => el.tagName.toLowerCase()")
    if name:
        return f"{tag}[name='{_css_escape(name)}']"

    # Fallback: build a fully qualified selector path from root
    selector = await element.evaluate("""el => {
        const parts = [];
        let current = el;
        while (current && current.tagName) {
            const tag = current.tagName.toLowerCase();
            if (current.id) {
                parts.unshift('#' + CSS.escape(current.id));
                break;
            }
            const parent = current.parentElement;
            if (!parent) {
                parts.unshift(tag);
                break;
            }
            const siblings = Array.from(parent.children).filter(c => c.tagName === current.tagName);
            if (siblings.length === 1) {
                parts.unshift(tag);
            } else {
                const idx = siblings.indexOf(current) + 1;
                parts.unshift(`${tag}:nth-of-type(${idx})`);
            }
            current = parent;
        }
        return parts.join(' > ');
    }""")
    return selector


def _infer_data_key(label: str) -> str:
    """Infer a canonical data key from a form label."""
    label = label.lower().strip()
    key_map = {
        "first name": "first_name",
        "last name": "last_name",
        "full name": "full_name",
        "email": "email",
        "phone": "phone",
        "linkedin": "linkedin_url",
        "github": "github_url",
        "location": "location",
        "university": "institution",
        "school": "institution",
        "degree": "degree",
        "gpa": "gpa",
        "major": "field",
    }
    for pattern, key in key_map.items():
        if pattern in label:
            return key
    return label.replace(" ", "_")
