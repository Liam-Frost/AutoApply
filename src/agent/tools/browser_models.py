"""Data types shared between the browser tools and the orchestrator.

The agent never touches Playwright directly. Instead the orchestrator
extracts a ``PageSnapshot`` -- an immutable, JSON-serializable view of
the form -- and binds tools to that snapshot. The agent reads from the
snapshot and writes to a ``ProposalCollector``; the orchestrator later
replays the proposals against the real ``Page``.

This split is deliberate:

* Sync tools fit the Phase 8 ``Tool.run`` signature without an event loop.
* The agent cannot accidentally click submit, navigate, or scrape PII --
  there is no Playwright handle in the tool's reach.
* Snapshots are trivial to fixture for tests/evals (just build one in
  Python, no headless browser required).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Keep the prompt cost bounded. ATS pages can list 100+ fields between
# header/footer/nav inputs; the orchestrator should narrow before we
# even get here, but we still cap defensively.
MAX_SNAPSHOT_FIELDS = 60

# Maximum chars we ship to the agent for any single label/option string.
# Truncation here is preferable to letting one weird field blow the
# context budget for the whole page.
MAX_LABEL_CHARS = 240
MAX_OPTION_CHARS = 80
MAX_OPTIONS_PER_FIELD = 25


@dataclass(frozen=True)
class FieldDescriptor:
    """One form field as the agent sees it.

    ``field_id`` is an opaque handle assigned by the snapshot builder.
    The agent passes it back when proposing a fill; the orchestrator
    resolves it to a real Playwright selector. Keeping selectors out of
    the agent's view means a hallucinated id fails loudly instead of
    targeting an arbitrary element on the page.
    """

    field_id: str
    label: str
    # text | email | tel | url | number | textarea | select | radio | checkbox | file
    field_type: str
    required: bool = False
    placeholder: str = ""
    options: tuple[str, ...] = ()
    section: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["options"] = list(self.options)
        return d


@dataclass(frozen=True)
class PageSnapshot:
    """Immutable view of a form page passed to the agent.

    ``url`` and ``title`` give the agent context. ``fields`` is the
    ordered list. ``truncated`` is set if we dropped fields to fit the
    budget; the orchestrator treats this as a signal to either page the
    form or fall back to deterministic mode.

    ``selectors_by_id`` carries the orchestrator-side mapping back to
    real Playwright selectors. It is intentionally NOT serialised into
    the agent-facing JSON (see :meth:`to_dict`) so the agent cannot see
    raw selectors even if it gets a debug-level dump.
    """

    url: str
    title: str
    fields: tuple[FieldDescriptor, ...]
    sections: tuple[str, ...] = ()
    truncated: bool = False
    selectors_by_id: dict[str, str] = field(default_factory=dict)
    radio_names_by_id: dict[str, str] = field(default_factory=dict)

    def field_by_id(self, field_id: str) -> FieldDescriptor | None:
        for fd in self.fields:
            if fd.field_id == field_id:
                return fd
        return None

    def to_dict(self) -> dict[str, Any]:
        """Render the snapshot for the agent prompt.

        Excludes ``selectors_by_id`` deliberately -- the agent works
        through opaque field_ids only.
        """
        return {
            "url": self.url,
            "title": self.title,
            "truncated": self.truncated,
            "sections": list(self.sections),
            "fields": [f.to_dict() for f in self.fields],
        }


@dataclass
class FillProposal:
    """One ``(field_id, value)`` suggestion from the agent.

    ``confidence`` is a float in [0, 1] the agent self-reports. The
    orchestrator combines it with a configured threshold to decide
    whether the proposal needs human review before being applied. We
    keep the agent's free-text reason because it shows up in trace
    review when something looks wrong later.
    """

    field_id: str
    value: str
    confidence: float
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProposalCollector:
    """Accumulates fill proposals across one agent session.

    Repeating the same ``field_id`` overwrites the previous proposal --
    the agent is allowed to revise as it learns more. We keep the full
    history for the trace so reviewers can see what was tried.
    """

    def __init__(self) -> None:
        self._latest: dict[str, FillProposal] = {}
        self._history: list[FillProposal] = []

    def add(self, proposal: FillProposal) -> None:
        self._latest[proposal.field_id] = proposal
        self._history.append(proposal)

    def latest(self) -> list[FillProposal]:
        """Final answer: one proposal per field, last write wins."""
        return list(self._latest.values())

    def history(self) -> list[FillProposal]:
        return list(self._history)

    def has_field(self, field_id: str) -> bool:
        return field_id in self._latest

    def reset(self) -> None:
        self._latest.clear()
        self._history.clear()


def truncate_label(text: str, limit: int = MAX_LABEL_CHARS) -> str:
    """Trim a label to the budget; preserves the head + a marker."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def truncate_options(
    options: list[str] | tuple[str, ...],
    *,
    item_limit: int = MAX_OPTION_CHARS,
    count_limit: int = MAX_OPTIONS_PER_FIELD,
) -> tuple[str, ...]:
    """Truncate a select/radio option list to bounded size."""
    out: list[str] = []
    for opt in list(options)[:count_limit]:
        out.append(truncate_label(str(opt), limit=item_limit))
    if len(options) > count_limit:
        out.append(f"…(+{len(options) - count_limit} more)")
    return tuple(out)


@dataclass
class _SnapshotBudget:
    """Internal helper: tracks remaining field budget while building a snapshot."""

    max_fields: int = MAX_SNAPSHOT_FIELDS
    used: int = 0
    truncated: bool = False

    def take(self) -> bool:
        if self.used >= self.max_fields:
            self.truncated = True
            return False
        self.used += 1
        return True


def freeze_field_descriptor(
    *,
    field_id: str,
    label: str,
    field_type: str,
    required: bool = False,
    placeholder: str = "",
    options: list[str] | tuple[str, ...] = (),
    section: str = "",
) -> FieldDescriptor:
    """Construct a ``FieldDescriptor`` while applying truncation rules.

    Centralising truncation here (rather than expecting every caller to
    do it) keeps the snapshot guarantees in one place: nothing reaches
    the agent without going through here.
    """
    return FieldDescriptor(
        field_id=str(field_id),
        label=truncate_label(label),
        field_type=str(field_type or "text"),
        required=bool(required),
        placeholder=truncate_label(placeholder),
        options=truncate_options(options) if options else (),
        section=truncate_label(section, limit=80),
    )


__all__ = [
    "FieldDescriptor",
    "FillProposal",
    "MAX_LABEL_CHARS",
    "MAX_OPTIONS_PER_FIELD",
    "MAX_OPTION_CHARS",
    "MAX_SNAPSHOT_FIELDS",
    "PageSnapshot",
    "ProposalCollector",
    "_SnapshotBudget",
    "freeze_field_descriptor",
    "truncate_label",
    "truncate_options",
]
