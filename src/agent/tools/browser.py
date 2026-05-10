"""Browser inspection / proposal tools for the form-filler agent.

The agent gets four tools, all read-only or proposal-only. None of them
touch the live ``Page``:

    browser_inspect_page  - dump the bound snapshot's fields
    browser_find_field    - fuzzy search for fields by label/placeholder
    browser_propose_fill  - record a (field_id, value, confidence) plan
    browser_screenshot    - return the path to a screenshot taken upstream

The orchestrator pre-builds a :class:`PageSnapshot`, ties it together
with a :class:`ProposalCollector`, then calls :func:`build_browser_tools`
to get a :class:`ToolRegistry` it can hand to the agent loop. Once the
loop finishes, the orchestrator reads ``collector.latest()`` and replays
the proposals against the real ``Page`` -- after the HITL gate clears
them.

This indirection is the only reason the agent can be confined: there is
no Playwright handle anywhere in this module, so even a misbehaving
agent cannot click, navigate, or scrape PII it was not given.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from src.agent.tools.base import Tool, ToolError, ToolRegistry, ToolResult
from src.agent.tools.browser_models import (
    FieldDescriptor,
    FillProposal,
    PageSnapshot,
    ProposalCollector,
    _SnapshotBudget,
    freeze_field_descriptor,
)
from src.agent.tools.builtin import FinishTool

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


class BrowserInspectPageTool(Tool):
    """Return the snapshot's fields as compact JSON.

    The agent uses this once at the start of a session to learn what is
    on the page. We render JSON rather than a free-form summary so the
    agent can reason structurally; the trade-off is that we must keep
    the schema small enough to fit a typical model context.
    """

    name = "browser_inspect_page"
    description = (
        "Return a structured listing of the form fields on the current page. "
        "Each field has a `field_id` (use this when proposing a fill), "
        "label, type, options (for select/radio), and whether it is required. "
        "Pass an optional `section` filter to narrow the listing."
    )
    parameters = {
        "type": "object",
        "properties": {
            "section": {
                "type": "string",
                "description": "Only return fields whose section heading matches this substring.",
            },
            "limit": {
                "type": "integer",
                "description": "Cap on number of fields returned. Default: all.",
            },
        },
    }

    def __init__(self, snapshot: PageSnapshot) -> None:
        self._snapshot = snapshot

    def run(self, args: dict[str, Any]) -> ToolResult:
        section = args.get("section")
        limit = args.get("limit")
        if section is not None and not isinstance(section, str):
            raise ToolError("'section' must be a string when provided.")
        if limit is not None and not isinstance(limit, int):
            raise ToolError("'limit' must be an integer when provided.")

        fields: Iterable[FieldDescriptor] = self._snapshot.fields
        if section:
            needle = section.lower()
            fields = [f for f in fields if needle in (f.section or "").lower()]
        if isinstance(limit, int) and limit >= 0:
            fields = list(fields)[:limit]
        else:
            fields = list(fields)

        payload = {
            "url": self._snapshot.url,
            "title": self._snapshot.title,
            "truncated": self._snapshot.truncated,
            "field_count": len(fields),
            "fields": [f.to_dict() for f in fields],
        }
        return ToolResult(
            output=json.dumps(payload, ensure_ascii=False),
            data=payload,
        )


class BrowserFindFieldTool(Tool):
    """Fuzzy lookup over labels/placeholders/sections.

    Helpful when the agent already knows what it wants ('email
    address') but the snapshot is too large to scan visually. The
    scorer is intentionally simple -- substring + token overlap -- so
    the result is deterministic and reproducible across runs.
    """

    name = "browser_find_field"
    description = (
        "Search the page for fields whose label, placeholder, or section "
        "matches the given query. Returns up to `top_k` ranked matches "
        "with scores; use the `field_id` from the best match when filling."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Free-text query, e.g. 'first name', 'email', 'university'.",
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of matches to return. Default 5.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, snapshot: PageSnapshot) -> None:
        self._snapshot = snapshot

    def run(self, args: dict[str, Any]) -> ToolResult:
        query = args.get("query", "")
        if not isinstance(query, str) or not query.strip():
            raise ToolError("'query' must be a non-empty string.")
        top_k = args.get("top_k", 5)
        if not isinstance(top_k, int) or top_k <= 0:
            raise ToolError("'top_k' must be a positive integer.")

        scored = [
            (_score_field(query, f), f) for f in self._snapshot.fields
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        picked = [(s, f) for s, f in scored if s > 0][:top_k]

        matches = [
            {"score": round(score, 3), "field": f.to_dict()}
            for score, f in picked
        ]
        payload = {"query": query, "matches": matches}
        if not matches:
            return ToolResult(
                output=f"No fields matched query {query!r}.",
                data=payload,
            )
        return ToolResult(
            output=json.dumps(payload, ensure_ascii=False),
            data=payload,
        )


class BrowserProposeFillTool(Tool):
    """Record a fill proposal. **Does not touch the page.**

    The orchestrator collects all proposals and applies them after the
    agent finishes -- subject to the HITL gate. This is the choke point
    that keeps the agent from running away with the form.
    """

    name = "browser_propose_fill"
    description = (
        "Propose a value to fill into a form field. This DOES NOT actually "
        "fill the field; it records the proposal for the orchestrator. "
        "Provide `field_id` (from inspect or find_field), the `value` to "
        "fill, a `confidence` score in [0,1], and a short `reasoning`. "
        "Repeat with the same field_id to revise an earlier proposal."
    )
    parameters = {
        "type": "object",
        "properties": {
            "field_id": {"type": "string"},
            "value": {"type": "string"},
            "confidence": {
                "type": "number",
                "description": "Self-reported confidence in [0, 1].",
            },
            "reasoning": {
                "type": "string",
                "description": "One short sentence on why this value fits.",
            },
        },
        "required": ["field_id", "value", "confidence"],
    }

    # Hard cap so a runaway agent can't OOM the host by submitting tens of
    # thousands of proposals.
    MAX_PROPOSALS = 256

    def __init__(
        self,
        snapshot: PageSnapshot,
        collector: ProposalCollector,
    ) -> None:
        self._snapshot = snapshot
        self._collector = collector

    def run(self, args: dict[str, Any]) -> ToolResult:
        field_id = args.get("field_id")
        value = args.get("value")
        confidence = args.get("confidence")
        reasoning = args.get("reasoning", "")

        if not isinstance(field_id, str) or not field_id.strip():
            raise ToolError("'field_id' must be a non-empty string.")
        if not isinstance(value, str):
            raise ToolError("'value' must be a string.")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ToolError("'confidence' must be a number.")
        confidence = float(confidence)
        if not (0.0 <= confidence <= 1.0):
            raise ToolError("'confidence' must be in [0, 1].")
        if reasoning is not None and not isinstance(reasoning, str):
            raise ToolError("'reasoning' must be a string when provided.")

        descriptor = self._snapshot.field_by_id(field_id)
        if descriptor is None:
            return ToolResult(
                output=(
                    f"Unknown field_id {field_id!r}. "
                    "Call browser_inspect_page or browser_find_field first."
                ),
                is_error=True,
            )

        if (
            len(self._collector.history()) >= self.MAX_PROPOSALS
            and not self._collector.has_field(field_id)
        ):
            return ToolResult(
                output=(
                    f"Refusing proposal: already at the cap of "
                    f"{self.MAX_PROPOSALS} proposals."
                ),
                is_error=True,
            )

        # Validate against the field type so obviously wrong proposals
        # surface as observation feedback, not silent bad fills.
        validation_error = _validate_proposal(descriptor, value)
        if validation_error:
            return ToolResult(
                output=f"Proposal rejected: {validation_error}",
                is_error=True,
            )

        proposal = FillProposal(
            field_id=field_id,
            value=value,
            confidence=confidence,
            reasoning=str(reasoning or ""),
        )
        self._collector.add(proposal)

        return ToolResult(
            output=(
                f"Recorded proposal for field {field_id!r} "
                f"(label={descriptor.label!r}, confidence={confidence:.2f})."
            ),
            data={
                "proposal": proposal.to_dict(),
                "field_label": descriptor.label,
                "total_proposals": len(self._collector.latest()),
            },
        )


class BrowserScreenshotTool(Tool):
    """Return the path of a screenshot the orchestrator already captured.

    The agent does not actually drive the camera; if no screenshot was
    pre-staged this returns an error rather than tripping a real
    Playwright call. This keeps the tool sync and side-effect-free.
    """

    name = "browser_screenshot"
    description = (
        "Return the path to a screenshot of the current page. "
        "The screenshot is captured by the orchestrator before the "
        "agent starts; this tool just reports where it lives."
    )
    parameters = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, screenshot_path: str | None) -> None:
        self._path = screenshot_path

    def run(self, _args: dict[str, Any]) -> ToolResult:
        if not self._path:
            return ToolResult(
                output="No screenshot is available for this session.",
                is_error=True,
            )
        return ToolResult(
            output=f"Screenshot path: {self._path}",
            data={"path": self._path},
        )


# ---------------------------------------------------------------------------
# Registry builder
# ---------------------------------------------------------------------------


@dataclass
class BrowserToolBundle:
    """Convenience container returned by :func:`build_browser_tools`."""

    registry: ToolRegistry
    snapshot: PageSnapshot
    collector: ProposalCollector


def build_browser_tools(
    snapshot: PageSnapshot,
    *,
    collector: ProposalCollector | None = None,
    screenshot_path: str | None = None,
    include_finish: bool = True,
) -> BrowserToolBundle:
    """Construct a registry containing the browser toolset bound to one snapshot.

    The orchestrator passes the registry's allowed view to the agent
    loop; tying construction to a single snapshot keeps the agent's
    field references unambiguous.
    """
    registry = ToolRegistry()
    registry.register(BrowserInspectPageTool(snapshot))
    registry.register(BrowserFindFieldTool(snapshot))
    coll = collector or ProposalCollector()
    registry.register(BrowserProposeFillTool(snapshot, coll))
    registry.register(BrowserScreenshotTool(screenshot_path))
    if include_finish:
        registry.register(FinishTool())
    return BrowserToolBundle(registry=registry, snapshot=snapshot, collector=coll)


# ---------------------------------------------------------------------------
# Snapshot construction helpers
# ---------------------------------------------------------------------------


def build_snapshot_from_html(
    html: str,
    *,
    url: str = "",
    title: str = "",
    max_fields: int = 0,
) -> PageSnapshot:
    """Build a :class:`PageSnapshot` from a static HTML string.

    Used by tests, eval fixtures, and any code path where we already
    have the form's HTML in hand. For a live Playwright session use
    :func:`build_snapshot_from_page` instead.

    The parser is intentionally stdlib-only (matches ``intake/html_utils``).
    It is *not* a general HTML5 parser -- it handles the field shapes
    we need (input/select/textarea, label[for], section headings) and
    nothing else.
    """
    budget = _SnapshotBudget(max_fields=max_fields or 60)
    parser = _FormFieldParser(budget=budget)
    parser.feed(html or "")
    parser.close()

    if not title:
        title = parser.title or ""

    return PageSnapshot(
        url=url,
        title=title,
        fields=tuple(parser.fields),
        sections=tuple(parser.section_history),
        truncated=budget.truncated,
        # HTML snapshots have no Playwright selectors yet; the orchestrator
        # is responsible for swapping in real selectors before any fill.
        selectors_by_id={},
        radio_names_by_id=dict(parser.radio_names_by_id),
    )


async def build_snapshot_from_page(
    page: Any,
    *,
    form_selector: str | None = None,
    max_fields: int = 0,
) -> PageSnapshot:
    """Build a :class:`PageSnapshot` from a live Playwright Page.

    Delegates the DOM walk to the existing deterministic detector in
    :mod:`src.execution.form_filler`; this function only transforms its
    output into the agent-facing snapshot shape (opaque ids, truncated
    labels, sections grouped by nearest heading).
    """
    # Local import to avoid pulling Playwright into pure-Python tests.
    from src.execution.form_filler import detect_fields  # noqa: PLC0415

    raw = await detect_fields(page, form_selector=form_selector)
    url = getattr(page, "url", "") or ""
    title = ""
    try:
        title = await page.title()
    except Exception:  # noqa: BLE001 -- title is best-effort
        title = ""

    budget = _SnapshotBudget(max_fields=max_fields or 60)
    fields: list[FieldDescriptor] = []
    selectors_by_id: dict[str, str] = {}
    for raw_field in raw:
        if not budget.take():
            break
        field_id = f"f{budget.used}"
        fields.append(
            freeze_field_descriptor(
                field_id=field_id,
                label=raw_field.label or "",
                field_type=raw_field.field_type or "text",
                required=raw_field.required,
                options=raw_field.options or (),
            )
        )
        selectors_by_id[field_id] = raw_field.selector

    return PageSnapshot(
        url=url,
        title=title or "",
        fields=tuple(fields),
        truncated=budget.truncated,
        selectors_by_id=selectors_by_id,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _score_field(query: str, field: FieldDescriptor) -> float:
    """Tiny ranking function: substring + token overlap.

    Stable and explainable -- the eval suite will pin scores so we
    notice if changes here regress field-matching quality.
    """
    haystack = " ".join(
        [field.label or "", field.placeholder or "", field.section or ""]
    ).lower()
    needle = (query or "").lower().strip()
    if not needle:
        return 0.0

    score = 0.0
    if needle in haystack:
        score += 1.0

    q_tokens = _tokenize(query)
    f_tokens = _tokenize(haystack)
    if q_tokens and f_tokens:
        overlap = len(q_tokens & f_tokens)
        score += overlap / len(q_tokens)

    # Tie-break: prefer required fields, but only among fields that
    # already match. A pure 'required' bonus would surface unrelated
    # fields when the query doesn't match anything on the page.
    if score > 0 and field.required:
        score += 0.05
    return score


_NUMERIC_RE = re.compile(r"^-?\d+(\.\d+)?$")


def _validate_proposal(field: FieldDescriptor, value: str) -> str | None:
    """Check a proposed value against the field's declared type.

    Returns a human-readable error string when the proposal is bad, or
    ``None`` when it is acceptable. We err on the permissive side:
    LLMs often produce values that need light coercion (e.g. 'true'
    vs 'Yes') and we want the orchestrator's filler to handle that.
    """
    if field.field_type == "select" and field.options:
        # Allow exact match, or fuzzy/partial match against option labels.
        if value not in field.options and not any(
            value.lower() == opt.lower() or value.lower() in opt.lower()
            for opt in field.options
            if not opt.startswith("…")
        ):
            preview = list(field.options)[:5]
            ellipsis = "..." if len(field.options) > 5 else ""
            return (
                f"value {value!r} is not one of the field's options "
                f"({preview}{ellipsis})"
            )
    if field.field_type == "radio" and field.options:
        if value not in field.options and not any(
            value.lower() == opt.lower() for opt in field.options
        ):
            return (
                f"value {value!r} is not a radio option ({list(field.options)})"
            )
    if field.field_type == "number" and value and not _NUMERIC_RE.match(value):
        return f"value {value!r} is not numeric"
    if field.field_type == "checkbox" and value.lower() not in {
        "true",
        "false",
        "yes",
        "no",
        "1",
        "0",
        "",
    }:
        return f"checkbox value {value!r} must be true/false/yes/no/1/0"
    if field.field_type == "file":
        return "file fields are handled by the file uploader, not propose_fill"
    return None


# Heading tags we treat as potential section markers.
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "fieldset", "legend"}
# Field tags we descend into.
_INPUT_TAGS = {"input", "select", "textarea"}


@dataclass
class _PartialField:
    """Mutable scratch object while parsing an open input/select/textarea."""

    tag: str
    attrs: dict[str, str]
    text_buf: list[str]
    options: list[str]


class _FormFieldParser(HTMLParser):
    """Stdlib HTML parser that extracts form fields with section context.

    Not a general HTML5 parser. It assumes the fixture HTML is
    well-formed enough for a sequential walk -- which is what real ATS
    pages we care about provide once Playwright has rendered them.
    """

    def __init__(self, budget: _SnapshotBudget) -> None:
        super().__init__(convert_charrefs=True)
        self._budget = budget
        self.fields: list[FieldDescriptor] = []
        self.title: str = ""
        self.section_history: list[str] = []
        self._section_stack: list[str] = []
        self._labels_by_for: dict[str, str] = {}
        self._title_buf: list[str] | None = None
        self._heading_buf: list[str] | None = None
        self._heading_tag: str | None = None
        self._label_for: str | None = None
        self._label_buf: list[str] = []
        self._open_field: _PartialField | None = None
        self._open_option: dict[str, Any] | None = None
        self._next_id = 1
        # Maps field_id -> radio group name (so the orchestrator can find
        # all radios in a group when filling).
        self.radio_names_by_id: dict[str, str] = {}
        # Internal: maps radio group name -> field_id of the canonical field
        # we kept for that group, so subsequent radios merge their options in.
        self._radio_group_to_id: dict[str, str] = {}

    # ----- low level callbacks -----

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}

        if tag == "title":
            self._title_buf = []
            return

        if tag in _HEADING_TAGS:
            self._heading_tag = tag
            self._heading_buf = []
            return

        if tag == "label":
            self._label_for = a.get("for") or None
            self._label_buf = []
            return

        if tag in _INPUT_TAGS:
            self._open_field = _PartialField(
                tag=tag, attrs=a, text_buf=[], options=[]
            )
            if tag == "input" and a.get("type") not in {
                "button",
                "submit",
                "reset",
                "image",
                "hidden",
            }:
                # input is void in HTML5; commit on the start tag.
                self._commit_open_field()
            elif tag == "input":
                # Suppressed input types.
                self._open_field = None
            return

        if tag == "option" and self._open_field and self._open_field.tag == "select":
            self._open_option = {"value": a.get("value", ""), "text_buf": []}
            return

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title_buf is not None:
            self.title = "".join(self._title_buf).strip()
            self._title_buf = None
            return

        if tag in _HEADING_TAGS and self._heading_tag == tag:
            heading = "".join(self._heading_buf or []).strip()
            if heading:
                self.section_history.append(heading)
                self._section_stack = [heading]
            self._heading_buf = None
            self._heading_tag = None
            return

        if tag == "label":
            text = "".join(self._label_buf).strip()
            if self._label_for and text:
                self._labels_by_for[self._label_for] = text
            self._label_for = None
            self._label_buf = []
            return

        if tag == "option" and self._open_option is not None:
            text = "".join(self._open_option["text_buf"]).strip()
            label = text or self._open_option["value"]
            if label and self._open_field is not None:
                self._open_field.options.append(label)
            self._open_option = None
            return

        if tag in _INPUT_TAGS and self._open_field and self._open_field.tag == tag:
            self._commit_open_field()
            return

    def handle_data(self, data: str) -> None:
        if self._title_buf is not None:
            self._title_buf.append(data)
        if self._heading_buf is not None:
            self._heading_buf.append(data)
        if self._label_for is not None:
            self._label_buf.append(data)
        if self._open_option is not None:
            self._open_option["text_buf"].append(data)
        elif self._open_field is not None and self._open_field.tag == "textarea":
            self._open_field.text_buf.append(data)

    # ----- field commit -----

    def _commit_open_field(self) -> None:
        if not self._open_field:
            return
        a = self._open_field.attrs
        tag = self._open_field.tag
        ftype = a.get("type", "").lower() or ("textarea" if tag == "textarea" else "text")
        if tag == "select":
            ftype = "select"
        if tag == "textarea":
            ftype = "textarea"

        if ftype in {"button", "submit", "reset", "image", "hidden"}:
            self._open_field = None
            return

        # Radio buttons collapse into one logical field per group; we keep
        # the first occurrence and append later option labels into it.
        if ftype == "radio":
            name = a.get("name", "")
            existing_id = self._radio_group_to_id.get(name)
            if existing_id is not None:
                opt_label = self._labels_by_for.get(a.get("id", "")) or a.get("value", "")
                if opt_label:
                    self._merge_radio_option(existing_id, opt_label)
                self._open_field = None
                return

        if not self._budget.take():
            self._open_field = None
            return

        label = self._derive_label(a)
        placeholder = a.get("placeholder", "")
        required = "required" in a
        section = self._section_stack[-1] if self._section_stack else ""
        options = list(self._open_field.options)
        if ftype == "radio":
            seed = self._labels_by_for.get(a.get("id", "")) or a.get("value", "")
            if seed:
                options.append(seed)

        field_id = f"f{self._next_id}"
        self._next_id += 1
        descriptor = freeze_field_descriptor(
            field_id=field_id,
            label=label,
            field_type=ftype,
            required=required,
            placeholder=placeholder,
            options=options,
            section=section,
        )
        self.fields.append(descriptor)
        if ftype == "radio":
            radio_name = a.get("name", "")
            self.radio_names_by_id[field_id] = radio_name
            self._radio_group_to_id[radio_name] = field_id
        self._open_field = None

    def _merge_radio_option(self, field_id: str, option: str) -> None:
        idx = next(
            (i for i, f in enumerate(self.fields) if f.field_id == field_id), -1
        )
        if idx < 0:
            return
        existing = self.fields[idx]
        merged = list(existing.options) + [option]
        self.fields[idx] = freeze_field_descriptor(
            field_id=existing.field_id,
            label=existing.label,
            field_type=existing.field_type,
            required=existing.required,
            placeholder=existing.placeholder,
            options=merged,
            section=existing.section,
        )

    def _derive_label(self, attrs: dict[str, str]) -> str:
        # 1. aria-label wins, mirrors the deterministic detector.
        aria = attrs.get("aria-label")
        if aria and aria.strip():
            return aria.strip()
        # 2. label[for=id]
        el_id = attrs.get("id")
        if el_id and el_id in self._labels_by_for:
            return self._labels_by_for[el_id]
        # 3. placeholder
        placeholder = attrs.get("placeholder")
        if placeholder and placeholder.strip():
            return placeholder.strip()
        # 4. name attribute (last resort)
        name = attrs.get("name")
        if name:
            return name.replace("_", " ").replace("-", " ").strip()
        return ""
