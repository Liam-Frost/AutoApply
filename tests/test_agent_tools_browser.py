"""Tests for the Phase 9.1 browser tool layer.

These cover three layers:

* The data types and budget logic in ``browser_models``.
* The four agent-facing tools in ``browser`` (inspect, find, propose, screenshot).
* The stdlib HTML snapshot builder, which the eval suite relies on.

The tests intentionally avoid Playwright -- the orchestrator integration
is exercised in 9.2's tests.
"""

from __future__ import annotations

import json

import pytest

from src.agent.tools.browser import (
    BrowserFindFieldTool,
    BrowserInspectPageTool,
    BrowserProposeFillTool,
    BrowserScreenshotTool,
    build_browser_tools,
    build_snapshot_from_html,
)
from src.agent.tools.browser_models import (
    MAX_OPTIONS_PER_FIELD,
    MAX_SNAPSHOT_FIELDS,
    FieldDescriptor,
    FillProposal,
    PageSnapshot,
    ProposalCollector,
    freeze_field_descriptor,
    truncate_label,
    truncate_options,
)

SAMPLE_HTML = """
<html>
  <head><title>Apply for SWE Intern</title></head>
  <body>
    <h2>Personal Information</h2>
    <label for="fn">First Name</label>
    <input id="fn" name="first_name" type="text" required />
    <label for="ln">Last Name</label>
    <input id="ln" name="last_name" type="text" required />
    <input type="email" name="email" placeholder="you@example.com" required />
    <input type="tel" aria-label="Mobile phone" />

    <h2>Education</h2>
    <label for="uni">University</label>
    <select id="uni" name="university">
      <option value="">Choose…</option>
      <option value="ubc">University of British Columbia</option>
      <option value="sfu">Simon Fraser University</option>
      <option value="other">Other</option>
    </select>
    <label for="gpa">GPA</label>
    <input id="gpa" name="gpa" type="number" />

    <h2>Eligibility</h2>
    <label for="auth_yes">Yes</label>
    <input id="auth_yes" type="radio" name="work_auth" value="yes" />
    <label for="auth_no">No</label>
    <input id="auth_no" type="radio" name="work_auth" value="no" />

    <input type="checkbox" name="agree_tos" aria-label="Agree to terms" />

    <textarea name="cover_letter" placeholder="Tell us why"></textarea>
    <input type="file" aria-label="Resume" />

    <input type="submit" value="Apply" />
  </body>
</html>
"""


@pytest.fixture
def snapshot() -> PageSnapshot:
    return build_snapshot_from_html(
        SAMPLE_HTML, url="https://example.com/apply"
    )


# ---------------------------------------------------------------------------
# browser_models
# ---------------------------------------------------------------------------


class TestModels:
    def test_field_descriptor_to_dict(self) -> None:
        f = freeze_field_descriptor(
            field_id="f1",
            label="Email",
            field_type="email",
            required=True,
            options=("a", "b"),
        )
        d = f.to_dict()
        assert d == {
            "field_id": "f1",
            "label": "Email",
            "field_type": "email",
            "required": True,
            "placeholder": "",
            "options": ["a", "b"],
            "section": "",
        }

    def test_truncate_label_long_input(self) -> None:
        text = "x" * 1000
        out = truncate_label(text, limit=20)
        assert len(out) == 20
        assert out.endswith("…")

    def test_truncate_options_caps_count_and_marks_overflow(self) -> None:
        opts = [f"opt-{i}" for i in range(MAX_OPTIONS_PER_FIELD + 5)]
        out = truncate_options(opts)
        assert len(out) == MAX_OPTIONS_PER_FIELD + 1
        assert out[-1].startswith("…(+5 more)")

    def test_proposal_collector_overwrite(self) -> None:
        coll = ProposalCollector()
        coll.add(FillProposal(field_id="f1", value="A", confidence=0.5))
        coll.add(FillProposal(field_id="f1", value="B", confidence=0.9))
        latest = coll.latest()
        assert len(latest) == 1
        assert latest[0].value == "B"
        assert len(coll.history()) == 2

    def test_page_snapshot_to_dict_excludes_selectors(self) -> None:
        snap = PageSnapshot(
            url="u",
            title="t",
            fields=(),
            selectors_by_id={"f1": "#x"},
        )
        d = snap.to_dict()
        assert "selectors_by_id" not in d
        assert d["url"] == "u"


# ---------------------------------------------------------------------------
# Snapshot builder (HTML)
# ---------------------------------------------------------------------------


class TestSnapshotBuilder:
    def test_extracts_inputs_and_select(self, snapshot: PageSnapshot) -> None:
        labels = [f.label for f in snapshot.fields]
        assert "First Name" in labels
        assert "Last Name" in labels
        assert "you@example.com" in labels  # placeholder fallback
        assert "Mobile phone" in labels  # aria-label
        assert "University" in labels
        assert "GPA" in labels
        # Submit/hidden are skipped.
        assert all(f.field_type != "submit" for f in snapshot.fields)

    def test_pulls_options_from_select(self, snapshot: PageSnapshot) -> None:
        uni = next(f for f in snapshot.fields if f.label == "University")
        assert uni.field_type == "select"
        assert "University of British Columbia" in uni.options
        assert "Simon Fraser University" in uni.options

    def test_radio_group_collapses_to_one_field_with_options(
        self, snapshot: PageSnapshot
    ) -> None:
        radios = [f for f in snapshot.fields if f.field_type == "radio"]
        assert len(radios) == 1
        assert {opt.lower() for opt in radios[0].options} >= {"yes", "no"}
        assert snapshot.radio_names_by_id[radios[0].field_id] == "work_auth"

    def test_section_attached_to_fields(self, snapshot: PageSnapshot) -> None:
        first_name = next(f for f in snapshot.fields if f.label == "First Name")
        uni = next(f for f in snapshot.fields if f.label == "University")
        assert first_name.section == "Personal Information"
        assert uni.section == "Education"

    def test_required_flag_picked_up(self, snapshot: PageSnapshot) -> None:
        first_name = next(f for f in snapshot.fields if f.label == "First Name")
        assert first_name.required is True
        gpa = next(f for f in snapshot.fields if f.label == "GPA")
        assert gpa.required is False

    def test_textarea_and_file_detected(self, snapshot: PageSnapshot) -> None:
        types = {f.field_type for f in snapshot.fields}
        assert "textarea" in types
        assert "file" in types

    def test_truncated_when_over_budget(self) -> None:
        many = "<form>" + "".join(
            f"<label for='x{i}'>F{i}</label><input id='x{i}' name='n{i}' type='text'/>"
            for i in range(MAX_SNAPSHOT_FIELDS + 3)
        ) + "</form>"
        snap = build_snapshot_from_html(many)
        assert snap.truncated is True
        assert len(snap.fields) == MAX_SNAPSHOT_FIELDS

    def test_title_extracted(self, snapshot: PageSnapshot) -> None:
        assert "Apply for SWE Intern" in snapshot.title


# ---------------------------------------------------------------------------
# browser_inspect_page
# ---------------------------------------------------------------------------


class TestInspectTool:
    def test_returns_compact_json_with_all_fields(
        self, snapshot: PageSnapshot
    ) -> None:
        tool = BrowserInspectPageTool(snapshot)
        result = tool.spec().invoke({})
        assert not result.is_error
        payload = json.loads(result.output)
        assert payload["url"] == snapshot.url
        assert payload["field_count"] == len(snapshot.fields)
        assert payload["fields"][0]["field_id"]

    def test_filters_by_section(self, snapshot: PageSnapshot) -> None:
        tool = BrowserInspectPageTool(snapshot)
        result = tool.spec().invoke({"section": "Education"})
        payload = result.data
        assert payload["field_count"] >= 2
        for f in payload["fields"]:
            assert "education" in f["section"].lower()

    def test_limit_caps_returned_fields(self, snapshot: PageSnapshot) -> None:
        tool = BrowserInspectPageTool(snapshot)
        result = tool.spec().invoke({"limit": 2})
        assert result.data["field_count"] == 2

    def test_rejects_non_string_section(self, snapshot: PageSnapshot) -> None:
        tool = BrowserInspectPageTool(snapshot)
        result = tool.spec().invoke({"section": 123})
        assert result.is_error
        assert "must be a string" in result.output


# ---------------------------------------------------------------------------
# browser_find_field
# ---------------------------------------------------------------------------


class TestFindFieldTool:
    def test_top_match_wins_for_obvious_query(
        self, snapshot: PageSnapshot
    ) -> None:
        tool = BrowserFindFieldTool(snapshot)
        result = tool.spec().invoke({"query": "first name"})
        assert not result.is_error
        matches = result.data["matches"]
        assert matches
        assert matches[0]["field"]["label"] == "First Name"

    def test_returns_empty_when_no_match(self, snapshot: PageSnapshot) -> None:
        tool = BrowserFindFieldTool(snapshot)
        result = tool.spec().invoke({"query": "zzz_no_such_field"})
        assert "No fields matched" in result.output
        assert result.data["matches"] == []

    def test_top_k_caps_results(self, snapshot: PageSnapshot) -> None:
        tool = BrowserFindFieldTool(snapshot)
        result = tool.spec().invoke({"query": "name", "top_k": 1})
        assert len(result.data["matches"]) == 1

    def test_required_field_breaks_ties(self) -> None:
        a = freeze_field_descriptor(
            field_id="f1",
            label="Email",
            field_type="email",
            required=False,
        )
        b = freeze_field_descriptor(
            field_id="f2",
            label="Email",
            field_type="email",
            required=True,
        )
        snap = PageSnapshot(url="", title="", fields=(a, b))
        tool = BrowserFindFieldTool(snap)
        result = tool.spec().invoke({"query": "email"})
        # Required field ranked higher.
        assert result.data["matches"][0]["field"]["field_id"] == "f2"

    def test_rejects_blank_query(self, snapshot: PageSnapshot) -> None:
        tool = BrowserFindFieldTool(snapshot)
        result = tool.spec().invoke({"query": "   "})
        assert result.is_error

    def test_rejects_zero_top_k(self, snapshot: PageSnapshot) -> None:
        tool = BrowserFindFieldTool(snapshot)
        result = tool.spec().invoke({"query": "email", "top_k": 0})
        assert result.is_error


# ---------------------------------------------------------------------------
# browser_propose_fill
# ---------------------------------------------------------------------------


class TestProposeFillTool:
    def test_records_proposal_into_collector(
        self, snapshot: PageSnapshot
    ) -> None:
        coll = ProposalCollector()
        tool = BrowserProposeFillTool(snapshot, coll)
        first_name = next(f for f in snapshot.fields if f.label == "First Name")
        result = tool.spec().invoke(
            {
                "field_id": first_name.field_id,
                "value": "Liam",
                "confidence": 0.92,
                "reasoning": "matches profile.identity.first_name",
            }
        )
        assert not result.is_error
        latest = coll.latest()
        assert len(latest) == 1
        assert latest[0].value == "Liam"
        assert latest[0].confidence == pytest.approx(0.92)

    def test_unknown_field_id_is_recoverable_error(
        self, snapshot: PageSnapshot
    ) -> None:
        coll = ProposalCollector()
        tool = BrowserProposeFillTool(snapshot, coll)
        result = tool.spec().invoke(
            {"field_id": "fXXX", "value": "x", "confidence": 0.5}
        )
        assert result.is_error
        assert "Unknown field_id" in result.output
        assert coll.latest() == []

    def test_confidence_out_of_range_raises(
        self, snapshot: PageSnapshot
    ) -> None:
        coll = ProposalCollector()
        tool = BrowserProposeFillTool(snapshot, coll)
        first_name = next(f for f in snapshot.fields if f.label == "First Name")
        result = tool.spec().invoke(
            {"field_id": first_name.field_id, "value": "x", "confidence": 1.5}
        )
        assert result.is_error
        assert "in [0, 1]" in result.output

    def test_validates_select_value_against_options(
        self, snapshot: PageSnapshot
    ) -> None:
        coll = ProposalCollector()
        tool = BrowserProposeFillTool(snapshot, coll)
        uni = next(f for f in snapshot.fields if f.label == "University")
        bad = tool.spec().invoke(
            {"field_id": uni.field_id, "value": "Hogwarts", "confidence": 0.9}
        )
        assert bad.is_error
        assert "not one of the field's options" in bad.output

        good = tool.spec().invoke(
            {
                "field_id": uni.field_id,
                "value": "University of British Columbia",
                "confidence": 0.9,
            }
        )
        assert not good.is_error

    def test_validates_number_field(self, snapshot: PageSnapshot) -> None:
        coll = ProposalCollector()
        tool = BrowserProposeFillTool(snapshot, coll)
        gpa = next(f for f in snapshot.fields if f.label == "GPA")
        bad = tool.spec().invoke(
            {"field_id": gpa.field_id, "value": "A+", "confidence": 0.7}
        )
        assert bad.is_error
        good = tool.spec().invoke(
            {"field_id": gpa.field_id, "value": "3.95", "confidence": 0.7}
        )
        assert not good.is_error

    def test_file_field_rejected(self, snapshot: PageSnapshot) -> None:
        coll = ProposalCollector()
        tool = BrowserProposeFillTool(snapshot, coll)
        f = next(f for f in snapshot.fields if f.field_type == "file")
        result = tool.spec().invoke(
            {"field_id": f.field_id, "value": "/tmp/r.pdf", "confidence": 0.9}
        )
        assert result.is_error
        assert "file uploader" in result.output

    def test_revision_is_allowed_and_history_kept(
        self, snapshot: PageSnapshot
    ) -> None:
        coll = ProposalCollector()
        tool = BrowserProposeFillTool(snapshot, coll)
        first_name = next(f for f in snapshot.fields if f.label == "First Name")
        for value in ["Liam", "Liam-Frost"]:
            tool.spec().invoke(
                {
                    "field_id": first_name.field_id,
                    "value": value,
                    "confidence": 0.8,
                }
            )
        latest = coll.latest()
        assert len(latest) == 1
        assert latest[0].value == "Liam-Frost"
        assert len(coll.history()) == 2

    def test_proposal_cap_enforced(self, snapshot: PageSnapshot) -> None:
        coll = ProposalCollector()
        # Pre-fill the collector to the cap on history.
        first_name = next(f for f in snapshot.fields if f.label == "First Name")
        for _ in range(BrowserProposeFillTool.MAX_PROPOSALS):
            coll.add(
                FillProposal(field_id=first_name.field_id, value="x", confidence=0.5)
            )
        tool = BrowserProposeFillTool(snapshot, coll)
        # Adding a *new* field id is rejected.
        another = next(f for f in snapshot.fields if f.label != "First Name")
        result = tool.spec().invoke(
            {"field_id": another.field_id, "value": "x", "confidence": 0.5}
        )
        assert result.is_error
        assert "cap of" in result.output


# ---------------------------------------------------------------------------
# browser_screenshot
# ---------------------------------------------------------------------------


class TestScreenshotTool:
    def test_reports_path_when_available(self) -> None:
        tool = BrowserScreenshotTool("data/output/screenshots/apply.png")
        result = tool.spec().invoke({})
        assert not result.is_error
        assert "apply.png" in result.output

    def test_errors_when_no_screenshot_staged(self) -> None:
        tool = BrowserScreenshotTool(None)
        result = tool.spec().invoke({})
        assert result.is_error
        assert "No screenshot" in result.output


# ---------------------------------------------------------------------------
# Registry assembly
# ---------------------------------------------------------------------------


class TestBundle:
    def test_build_browser_tools_registers_expected_set(
        self, snapshot: PageSnapshot
    ) -> None:
        bundle = build_browser_tools(snapshot)
        assert set(bundle.registry.names()) == {
            "browser_inspect_page",
            "browser_find_field",
            "browser_propose_fill",
            "browser_screenshot",
            "finish",
        }
        assert isinstance(bundle.collector, ProposalCollector)

    def test_bundle_collector_is_shared_with_propose_tool(
        self, snapshot: PageSnapshot
    ) -> None:
        bundle = build_browser_tools(snapshot)
        first_name = next(f for f in snapshot.fields if f.label == "First Name")
        bundle.registry.get("browser_propose_fill").invoke(
            {
                "field_id": first_name.field_id,
                "value": "Liam",
                "confidence": 0.9,
            }
        )
        # The collector handed back from build_browser_tools sees the proposal.
        assert bundle.collector.latest()[0].value == "Liam"

    def test_omit_finish_is_supported_for_eval_use(
        self, snapshot: PageSnapshot
    ) -> None:
        bundle = build_browser_tools(snapshot, include_finish=False)
        assert "finish" not in bundle.registry.names()


# ---------------------------------------------------------------------------
# Smoke: full ReAct loop with a scripted LLM driving the tools.
# ---------------------------------------------------------------------------


class TestEndToEndWithScriptedAgent:
    def test_agent_can_inspect_then_propose_then_finish(
        self, snapshot: PageSnapshot
    ) -> None:
        from src.agent.core.loop import AgentSession, SessionLimits

        bundle = build_browser_tools(snapshot)
        first_name = next(f for f in snapshot.fields if f.label == "First Name")

        responses = [
            json.dumps(
                {
                    "thought": "see what's on the page",
                    "action": {"name": "browser_inspect_page", "args": {}},
                }
            ),
            json.dumps(
                {
                    "thought": "fill first name",
                    "action": {
                        "name": "browser_propose_fill",
                        "args": {
                            "field_id": first_name.field_id,
                            "value": "Liam",
                            "confidence": 0.95,
                            "reasoning": "matches profile",
                        },
                    },
                }
            ),
            json.dumps(
                {
                    "thought": "done",
                    "action": {"name": "finish", "args": {"answer": "1 field"}},
                }
            ),
        ]

        def scripted(_p: str, _s: str, _t: int) -> str:
            return responses.pop(0)

        session = AgentSession(
            goal="Fill first name only.",
            tools=bundle.registry,
            llm=scripted,
            limits=SessionLimits(max_steps=5),
        )
        result = session.run()
        assert result.finished
        assert result.answer == "1 field"
        assert bundle.collector.latest()[0].value == "Liam"


# ---------------------------------------------------------------------------
# Sanity: importing tools registry exposes new types
# ---------------------------------------------------------------------------


def test_public_imports() -> None:
    from src.agent.tools import (
        FieldDescriptor as ImportedFD,
    )
    from src.agent.tools import (
        FillProposal as ImportedFP,
    )
    from src.agent.tools import (
        PageSnapshot as ImportedPS,
    )
    from src.agent.tools import (
        ProposalCollector as ImportedPC,
    )

    assert ImportedFD is FieldDescriptor
    assert ImportedFP is FillProposal
    assert ImportedPS is PageSnapshot
    assert ImportedPC is ProposalCollector
