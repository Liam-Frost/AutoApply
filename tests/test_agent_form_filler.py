"""Tests for the Phase 9.2 agent form-filler orchestrator.

We exercise the orchestrator without booting Playwright by:

* feeding ``build_snapshot_from_html`` into a snapshot-builder seam
  (monkeypatching :func:`build_snapshot_from_page`), and
* running real ``fill_fields`` against a ``MockPage`` that records
  every action.

The agent is driven by a scripted LLM. Real LLM and real Playwright are
exercised in integration tests / live runs only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.agent.gate.queue import ApprovalGate, ApprovalStatus
from src.agent.tools.browser import build_snapshot_from_html
from src.agent.tools.browser_models import (
    FillProposal,
    PageSnapshot,
    ProposalCollector,
)
from src.agent.trace.store import TraceStore
from src.execution.agent_form_filler import (
    AgentFormFiller,
    AgentFormFillerConfig,
    ProposalReview,
    _click_submit,
    _proposals_to_mappings,
    build_goal,
)

# ---------------------------------------------------------------------------
# Fixture: small static form
# ---------------------------------------------------------------------------

SIMPLE_HTML = """
<html>
  <head><title>Apply</title></head>
  <body>
    <h2>Personal</h2>
    <label for="fn">First Name</label>
    <input id="fn" name="first_name" type="text" required />
    <label for="ln">Last Name</label>
    <input id="ln" name="last_name" type="text" required />
    <input type="email" name="email" placeholder="you@example.com" required />

    <h2>Education</h2>
    <label for="uni">University</label>
    <select id="uni" name="university">
      <option value="">Choose…</option>
      <option value="ubc">University of British Columbia</option>
      <option value="sfu">Simon Fraser University</option>
    </select>

    <h2>Work auth</h2>
    <label for="auth_yes">Yes</label>
    <input id="auth_yes" type="radio" name="work_auth" value="yes" />
    <label for="auth_no">No</label>
    <input id="auth_no" type="radio" name="work_auth" value="no" />
  </body>
</html>
"""


PROFILE = {
    "identity": {
        "full_name": "Liam Liu",
        "email": "frostnova986@gmail.com",
        "phone": "672-968-6198",
    },
    "education": [
        {"institution": "University of British Columbia"},
    ],
}


# ---------------------------------------------------------------------------
# Mock Playwright page
# ---------------------------------------------------------------------------


class MockLocator:
    def __init__(self, page: MockPage, selector: str) -> None:
        self.page = page
        self.selector = selector

    @property
    def first(self) -> MockLocator:
        return self

    async def count(self) -> int:
        return 1

    async def clear(self) -> None:
        self.page.actions.append(("clear", self.selector))

    async def type(self, text: str, delay: int = 0) -> None:
        self.page.actions.append(("type", self.selector, text))

    async def click(self) -> None:
        self.page.actions.append(("click", self.selector))

    async def is_checked(self) -> bool:
        return False

    async def select_option(self, label: str | None = None, **_: Any) -> None:
        self.page.actions.append(("select", self.selector, label))


class MockPage:
    """Records every Playwright-style action without touching a browser.

    Only implements the surface the orchestrator uses; if more is
    needed in a future test we add it explicitly here rather than
    growing it implicitly.
    """

    url = "https://example.com/apply"

    def __init__(self) -> None:
        self.actions: list[tuple[Any, ...]] = []
        self.title_value = "Apply"

    async def title(self) -> str:
        return self.title_value

    async def screenshot(
        self, path: str, full_page: bool = False, **_: Any
    ) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"\x89PNG mock")
        self.actions.append(("screenshot", path))

    def locator(self, selector: str) -> MockLocator:
        return MockLocator(self, selector)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_snapshot(html: str = SIMPLE_HTML) -> PageSnapshot:
    """Build a snapshot and stitch in synthetic selectors so the
    orchestrator's apply step has something to drive."""
    snap = build_snapshot_from_html(html, url="https://example.com/apply")
    selectors = {f.field_id: f"#{f.field_id}_sel" for f in snap.fields}
    return PageSnapshot(
        url=snap.url,
        title=snap.title,
        fields=snap.fields,
        sections=snap.sections,
        truncated=snap.truncated,
        selectors_by_id=selectors,
        radio_names_by_id=snap.radio_names_by_id,
    )


def scripted_llm(responses: list[str]):
    """Build an LLMCallable that pops one response per call."""
    queue = list(responses)

    def _llm(_p: str, _s: str, _t: int) -> str:
        if not queue:
            raise RuntimeError("scripted LLM exhausted")
        return queue.pop(0)

    return _llm


def respond(thought: str, action: str, **args: Any) -> str:
    return json.dumps(
        {"thought": thought, "action": {"name": action, "args": args}}
    )


# ---------------------------------------------------------------------------
# build_goal / _review
# ---------------------------------------------------------------------------


class TestGoalBuilder:
    def test_includes_summary_and_extra(self) -> None:
        text = build_goal(
            profile_summary="identity, education",
            extra_context="Apply for SWE intern",
        )
        assert "identity" in text
        assert "Apply for SWE intern" in text
        assert "browser_propose_fill" in text

    def test_minimal_form(self) -> None:
        text = build_goal()
        assert "browser_inspect_page" in text


class TestReview:
    def test_low_confidence_triggers_review(self) -> None:
        config = AgentFormFillerConfig(min_confidence=0.7, always_review=False)
        filler = AgentFormFiller(
            config=config, gate=ApprovalGate(), trace_store=TraceStore()
        )
        review = filler._review(
            [
                FillProposal("f1", "a", confidence=0.9),
                FillProposal("f2", "b", confidence=0.5),
            ]
        )
        assert review.needs_human_review is True
        assert [p.field_id for p in review.low_confidence] == ["f2"]

    def test_always_review_dominates(self) -> None:
        config = AgentFormFillerConfig(min_confidence=0.0, always_review=True)
        filler = AgentFormFiller(config=config)
        review = filler._review([FillProposal("f1", "a", confidence=1.0)])
        assert review.needs_human_review is True

    def test_no_proposals_needs_review(self) -> None:
        config = AgentFormFillerConfig(always_review=False)
        filler = AgentFormFiller(config=config)
        review = filler._review([])
        assert review.needs_human_review is True


# ---------------------------------------------------------------------------
# _proposals_to_mappings
# ---------------------------------------------------------------------------


class TestProposalsToMappings:
    def test_skips_proposals_without_selector(self) -> None:
        snap = build_snapshot_from_html(SIMPLE_HTML)
        # Default builder has no selectors_by_id from HTML -- proposals
        # should be silently dropped.
        mappings = _proposals_to_mappings(
            snap,
            [FillProposal(snap.fields[0].field_id, "Liam", confidence=0.9)],
        )
        assert mappings == []

    def test_text_field_uses_stored_selector(self) -> None:
        snap = make_snapshot()
        first = snap.fields[0]
        mappings = _proposals_to_mappings(
            snap, [FillProposal(first.field_id, "Liam", confidence=0.9)]
        )
        assert len(mappings) == 1
        assert mappings[0].form_field.selector == f"#{first.field_id}_sel"
        assert mappings[0].value == "Liam"

    def test_radio_field_gets_specific_radio_selector(self) -> None:
        snap = make_snapshot()
        radio = next(f for f in snap.fields if f.field_type == "radio")
        mappings = _proposals_to_mappings(
            snap, [FillProposal(radio.field_id, "yes", confidence=0.9)]
        )
        assert len(mappings) == 1
        sel = mappings[0].form_field.selector
        assert "name='work_auth'" in sel
        assert "value='yes'" in sel

    def test_file_field_skipped(self) -> None:
        snap = build_snapshot_from_html(
            "<input type='file' aria-label='Resume' />"
        )
        snap = PageSnapshot(
            url=snap.url,
            title=snap.title,
            fields=snap.fields,
            sections=snap.sections,
            truncated=snap.truncated,
            selectors_by_id={f.field_id: "#x" for f in snap.fields},
        )
        mappings = _proposals_to_mappings(
            snap,
            [FillProposal(snap.fields[0].field_id, "/r.pdf", confidence=1.0)],
        )
        assert mappings == []


# ---------------------------------------------------------------------------
# Orchestrator end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_snapshot_builder(monkeypatch: pytest.MonkeyPatch) -> PageSnapshot:
    """Replace build_snapshot_from_page with a fixed-fixture version."""
    snap = make_snapshot()

    async def fake_builder(_page: Any, **_: Any) -> PageSnapshot:
        return snap

    monkeypatch.setattr(
        "src.execution.agent_form_filler.build_snapshot_from_page",
        fake_builder,
    )
    return snap


@pytest.fixture
def gate(tmp_path: Path) -> ApprovalGate:
    return ApprovalGate(base_dir=tmp_path / "gate")


@pytest.fixture
def trace_store(tmp_path: Path) -> TraceStore:
    return TraceStore(base_dir=tmp_path / "traces")


@pytest.fixture
def screenshot_dir(tmp_path: Path) -> Path:
    return tmp_path / "screenshots"


class TestOrchestratorRun:
    @pytest.mark.asyncio
    async def test_high_confidence_path_applies_fills(
        self,
        patched_snapshot_builder: PageSnapshot,
        gate: ApprovalGate,
        trace_store: TraceStore,
        screenshot_dir: Path,
    ) -> None:
        snap = patched_snapshot_builder
        first = next(f for f in snap.fields if f.label == "First Name")
        last = next(f for f in snap.fields if f.label == "Last Name")
        email = next(f for f in snap.fields if "@example.com" in f.label)
        responses = [
            respond("inspect", "browser_inspect_page"),
            respond("fill first", "browser_propose_fill",
                    field_id=first.field_id, value="Liam", confidence=0.95),
            respond("fill last", "browser_propose_fill",
                    field_id=last.field_id, value="Liu", confidence=0.95),
            respond("fill email", "browser_propose_fill",
                    field_id=email.field_id, value="frostnova986@gmail.com",
                    confidence=0.95),
            respond("done", "finish", answer="3 fields"),
        ]
        config = AgentFormFillerConfig(
            min_confidence=0.7,
            always_review=False,
            screenshot_dir=screenshot_dir,
        )
        filler = AgentFormFiller(
            config=config,
            gate=gate,
            trace_store=trace_store,
            llm=scripted_llm(responses),
        )
        page = MockPage()
        result = await filler.run(page=page, profile_data=PROFILE, job_id="abcd1234")

        assert result.error is None
        assert result.used_fallback is False
        assert result.review_request_id is None
        assert result.review.needs_human_review is False
        assert result.filled_count == 3
        # Three text-type actions ('clear' + 'type') should be in the page log.
        type_actions = [a for a in page.actions if a[0] == "type"]
        values = [a[2] for a in type_actions]
        assert "Liam" in values
        assert "Liu" in values
        assert "frostnova986@gmail.com" in values
        # Trace was recorded.
        assert result.trace_id

    @pytest.mark.asyncio
    async def test_low_confidence_parks_review_gate(
        self,
        patched_snapshot_builder: PageSnapshot,
        gate: ApprovalGate,
        trace_store: TraceStore,
        screenshot_dir: Path,
    ) -> None:
        snap = patched_snapshot_builder
        first = next(f for f in snap.fields if f.label == "First Name")
        responses = [
            respond("inspect", "browser_inspect_page"),
            respond("uncertain fill", "browser_propose_fill",
                    field_id=first.field_id, value="Liam", confidence=0.4),
            respond("done", "finish", answer="1 uncertain"),
        ]
        config = AgentFormFillerConfig(
            min_confidence=0.7,
            always_review=False,
            screenshot_dir=screenshot_dir,
        )
        filler = AgentFormFiller(
            config=config,
            gate=gate,
            trace_store=trace_store,
            llm=scripted_llm(responses),
        )
        page = MockPage()
        result = await filler.run(page=page, profile_data=PROFILE)

        assert result.review_request_id is not None
        assert result.review.needs_human_review
        # No fills applied yet (review is still pending).
        assert result.fill_mappings == []
        # No 'type' actions on the page.
        assert not any(a[0] == "type" for a in page.actions)
        # The gate now has a pending request the user can review.
        request = gate.get(result.review_request_id)
        assert request.status == ApprovalStatus.PENDING
        assert "low_confidence_field_ids" in request.payload

    @pytest.mark.asyncio
    async def test_apply_after_review_fills_when_user_approves(
        self,
        patched_snapshot_builder: PageSnapshot,
        gate: ApprovalGate,
        trace_store: TraceStore,
        screenshot_dir: Path,
    ) -> None:
        snap = patched_snapshot_builder
        first = next(f for f in snap.fields if f.label == "First Name")
        responses = [
            respond("inspect", "browser_inspect_page"),
            respond("uncertain", "browser_propose_fill",
                    field_id=first.field_id, value="Liam", confidence=0.4),
            respond("done", "finish", answer="ok"),
        ]
        filler = AgentFormFiller(
            config=AgentFormFillerConfig(
                min_confidence=0.7,
                always_review=False,
                screenshot_dir=screenshot_dir,
            ),
            gate=gate,
            trace_store=trace_store,
            llm=scripted_llm(responses),
        )
        page = MockPage()
        run_result = await filler.run(page=page, profile_data=PROFILE)
        assert run_result.review_request_id

        # Simulate the human approving the review.
        gate.approve(run_result.review_request_id, decided_by="test")

        # Caller (web layer) now applies the proposals.
        applied = await filler.apply_after_review(
            page=page, snapshot=snap, proposals=run_result.review.proposals
        )
        assert any(m.filled for m in applied)
        # Now the page recorded a type action.
        assert any(a[0] == "type" and a[2] == "Liam" for a in page.actions)

    @pytest.mark.asyncio
    async def test_falls_back_when_agent_produces_no_proposals(
        self,
        patched_snapshot_builder: PageSnapshot,
        monkeypatch: pytest.MonkeyPatch,
        gate: ApprovalGate,
        trace_store: TraceStore,
        screenshot_dir: Path,
    ) -> None:
        # Agent immediately finishes without proposing anything.
        responses = [respond("nope", "finish", answer="empty")]

        # Stub detect_fields/fill_fields used by the fallback so we don't
        # need a real Playwright session.
        async def stub_detect(_page: Any, **_: Any) -> list:
            from src.execution.form_filler import FormField

            return [
                FormField(selector="#fn_sel", label="First Name", field_type="text"),
            ]

        async def stub_fill(_page: Any, mappings, **_: Any):
            for m in mappings:
                if m.value:
                    m.filled = True
            return mappings

        monkeypatch.setattr(
            "src.execution.agent_form_filler.detect_fields", stub_detect
        )
        monkeypatch.setattr(
            "src.execution.agent_form_filler.fill_fields", stub_fill
        )

        config = AgentFormFillerConfig(
            min_confidence=0.7,
            always_review=False,
            screenshot_dir=screenshot_dir,
        )
        filler = AgentFormFiller(
            config=config,
            gate=gate,
            trace_store=trace_store,
            llm=scripted_llm(responses),
        )
        result = await filler.run(page=MockPage(), profile_data=PROFILE)
        assert result.used_fallback is True
        # First-name fill came through the deterministic mapper.
        assert any(m.filled for m in result.fill_mappings)

    @pytest.mark.asyncio
    async def test_screenshot_failure_does_not_abort_run(
        self,
        patched_snapshot_builder: PageSnapshot,
        monkeypatch: pytest.MonkeyPatch,
        gate: ApprovalGate,
        trace_store: TraceStore,
        screenshot_dir: Path,
    ) -> None:
        responses = [respond("done", "finish", answer="ok")]

        page = MockPage()

        async def boom(*_: Any, **__: Any) -> None:
            raise RuntimeError("disk full")

        monkeypatch.setattr(page, "screenshot", boom)

        config = AgentFormFillerConfig(
            screenshot_dir=screenshot_dir,
        )
        filler = AgentFormFiller(
            config=config,
            gate=gate,
            trace_store=trace_store,
            llm=scripted_llm(responses),
            # Disable fallback so we observe the agent path's screenshot
            # robustness directly.
        )
        # Disabling fallback via config:
        filler.config.fallback_to_rules = False
        result = await filler.run(page=page, profile_data=PROFILE)
        # The run still produced a snapshot + (empty) review, even though
        # the screenshot blew up.
        assert result.snapshot is not None
        assert result.screenshot_path is None


# ---------------------------------------------------------------------------
# Submit gate
# ---------------------------------------------------------------------------


class TestSubmitGate:
    @pytest.mark.asyncio
    async def test_submit_blocked_without_approval(
        self,
        gate: ApprovalGate,
    ) -> None:
        snap = make_snapshot()
        review = ProposalReview(
            proposals=[FillProposal("f1", "x", confidence=0.9)],
            threshold=0.7,
        )
        filler = AgentFormFiller(gate=gate)
        request = filler.request_submit_approval(
            snapshot=snap, review=review, job_id="j1"
        )
        assert request.kind == "submit_form"
        assert request.status == ApprovalStatus.PENDING

        with pytest.raises(PermissionError):
            await filler.submit(page=MockPage(), request_id=request.id)

    @pytest.mark.asyncio
    async def test_submit_succeeds_after_approval(
        self,
        gate: ApprovalGate,
    ) -> None:
        snap = make_snapshot()
        review = ProposalReview(threshold=0.7)
        filler = AgentFormFiller(gate=gate)
        request = filler.request_submit_approval(
            snapshot=snap, review=review, job_id="j1"
        )
        gate.approve(request.id, decided_by="user")

        page = MockPage()
        ok = await filler.submit(page=page, request_id=request.id)
        assert ok is True
        # Some submit-button click was issued.
        assert any(a[0] == "click" for a in page.actions)

    @pytest.mark.asyncio
    async def test_submit_rejects_after_rejection(
        self,
        gate: ApprovalGate,
    ) -> None:
        snap = make_snapshot()
        filler = AgentFormFiller(gate=gate)
        request = filler.request_submit_approval(
            snapshot=snap, review=ProposalReview(threshold=0.7), job_id="j"
        )
        gate.reject(request.id, decided_by="user", reason="not now")
        with pytest.raises(PermissionError):
            await filler.submit(page=MockPage(), request_id=request.id)


class TestClickSubmit:
    @pytest.mark.asyncio
    async def test_uses_explicit_selector_first(self) -> None:
        page = MockPage()
        await _click_submit(page, "button#go")
        assert page.actions[0] == ("click", "button#go")

    @pytest.mark.asyncio
    async def test_falls_through_default_candidates(self) -> None:
        page = MockPage()
        ok = await _click_submit(page, None)
        assert ok is True
        # First default candidate is button[type='submit'].
        assert page.actions[0][1] == "button[type='submit']"


# ---------------------------------------------------------------------------
# Wiring sanity
# ---------------------------------------------------------------------------


class TestWiring:
    def test_collector_is_optional_in_build_browser_tools(self) -> None:
        # Smoke check: bundle constructed in orchestrator path uses an
        # owned ProposalCollector unless one is provided.
        snap = make_snapshot()
        coll = ProposalCollector()
        from src.agent.tools.browser import build_browser_tools

        bundle = build_browser_tools(snap, collector=coll)
        assert bundle.collector is coll

    @pytest.mark.asyncio
    async def test_run_is_async(self) -> None:
        # Defensive contract test the orchestrator module already
        # asserts at import time. Repeated here for paper-trail.
        import inspect

        assert inspect.iscoroutinefunction(AgentFormFiller.run)
