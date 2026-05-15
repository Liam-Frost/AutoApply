"""Phase 15.7: tests for AgentCoverLetter + fact-drift post-guard."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.generation.agent_cover_letter import (
    AgentCoverLetter,
    AgentCoverLetterError,
    _parse_agent_output,
)
from src.generation.fact_drift import check_fact_drift

# ---- Fact-drift post-guard ------------------------------------------


def test_no_drift_when_text_grounded() -> None:
    report = check_fact_drift(
        "Built a service serving 10k requests per second.",
        evidence_texts=["Built a service serving 10k requests per second."],
    )
    assert report.has_blocking_drift is False
    assert report.number_drift == []


def test_number_drift_is_blocking() -> None:
    report = check_fact_drift(
        "Reduced latency by 99%.",
        evidence_texts=["Reduced latency in our cache."],
    )
    assert report.has_blocking_drift is True
    assert "99%" in report.number_drift


def test_numeric_unit_normalization() -> None:
    """'10k' in the generated text matches '10000' in the evidence."""
    report = check_fact_drift(
        "Serving 10k requests per second.",
        evidence_texts=["Serving 10000 requests per second."],
    )
    assert report.has_blocking_drift is False


def test_currency_and_decimal_match() -> None:
    report = check_fact_drift(
        "Drove $1.5M in revenue impact.",
        evidence_texts=["Drove $1.5M in revenue impact this year."],
    )
    assert report.has_blocking_drift is False


def test_drift_can_use_jd_or_profile() -> None:
    """A number cited from the JD or the profile is not drift even if
    absent from evidence bullets."""
    report = check_fact_drift(
        "Joining a team of 200 engineers.",
        evidence_texts=["Strong communicator on cross-team projects."],
        jd_snapshot_text="We have 200 engineers across three offices.",
    )
    assert report.has_blocking_drift is False


def test_entity_drift_is_warning_not_blocking() -> None:
    report = check_fact_drift(
        "Worked at GhostCorp on a critical platform.",
        evidence_texts=["Worked at Initech on a critical platform."],
    )
    assert report.has_blocking_drift is False  # entity drift is non-blocking
    assert any("GhostCorp" in cand for cand in report.entity_drift)


def test_sentence_initial_capitals_are_not_entity_drift() -> None:
    report = check_fact_drift(
        "The role excites me. Therefore I am applying.",
        evidence_texts=["I am applying to roles I find exciting."],
    )
    assert report.entity_drift == []


def test_length_warning_when_paragraph_far_exceeds_evidence() -> None:
    long_para = "Padded fluff " * 80
    report = check_fact_drift(
        long_para,
        evidence_texts=["Short bullet."],
    )
    # No numbers / entities here, so blocking should be False, but the
    # length warning should fire.
    assert report.length_warnings


# ---- Agent output parsing -------------------------------------------


def test_parse_agent_output_accepts_bare_json() -> None:
    payload = json.dumps(
        {
            "paragraphs": [
                {"type": "opening", "text": "Hello", "source_ids": ["e1"]},
                {"type": "closing", "text": "Bye", "source_ids": []},
            ]
        }
    )
    doc = _parse_agent_output(payload)
    assert doc is not None
    assert len(doc.paragraphs) == 2
    assert doc.paragraphs[0].type == "opening"


def test_parse_agent_output_strips_fenced_code() -> None:
    payload = (
        "Sure, here you go:\n"
        + "```json\n"
        + '{"paragraphs": [{"type": "opening", "text": "Hi", "source_ids": []}]}\n'
        + "```"
    )
    doc = _parse_agent_output(payload)
    assert doc is not None
    assert doc.paragraphs[0].text == "Hi"


def test_parse_agent_output_returns_none_on_bad_json() -> None:
    assert _parse_agent_output("not json") is None
    assert _parse_agent_output("") is None
    assert _parse_agent_output("[]") is None  # must be object


def test_parse_agent_output_returns_none_on_empty_paragraphs() -> None:
    assert _parse_agent_output('{"paragraphs": []}') is None


# ---- AgentCoverLetter dispatch --------------------------------------


@dataclass
class _SnapshotStub:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = "Backend Intern"
    description: str = "Build APIs."
    location: str = "Remote"
    employment_type: str = "intern"
    requirements: dict[str, Any] = field(
        default_factory=lambda: {"must_have": ["python", "fastapi"]}
    )
    raw_data: dict[str, Any] = field(
        default_factory=lambda: {"company": "Initech"}
    )


_PROFILE: dict[str, Any] = {
    "identity": {"full_name": "Alice Smith", "email": "a@x.com"},
    "work_experiences": [
        {
            "company": "Initech",
            "title": "Software Engineer Intern",
            "location": "Remote",
            "bullets": [
                {"text": "Reduced API latency by 40% using Redis caching."},
                {"text": "Wrote integration tests covering 90% of the auth flow."},
            ],
        }
    ],
}


def test_constructor_requires_snapshot() -> None:
    with pytest.raises(AgentCoverLetterError):
        AgentCoverLetter(job_snapshot=None, profile_data=_PROFILE)


def test_use_agent_false_returns_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    orchestrator = AgentCoverLetter(
        job_snapshot=_SnapshotStub(),
        profile_data=_PROFILE,
        llm_fn=lambda prompt, system: '{"paragraphs": [{"type": "opening", "text": "x"}]}',
    )
    result = orchestrator.run(
        evidence_bullets=["Reduced API latency by 40%."],
        use_agent=False,
    )
    assert result.decision == "deterministic_only"
    assert result.document is not None


def test_no_llm_fn_routes_to_deterministic() -> None:
    orchestrator = AgentCoverLetter(
        job_snapshot=_SnapshotStub(),
        profile_data=_PROFILE,
        llm_fn=None,
    )
    result = orchestrator.run(evidence_bullets=["Reduced API latency by 40%."])
    assert result.decision == "deterministic_only"


def test_agent_ok_when_output_is_grounded(monkeypatch: pytest.MonkeyPatch) -> None:
    grounded_output = json.dumps(
        {
            "paragraphs": [
                {
                    "type": "opening",
                    "text": "I am excited to apply for the Backend Intern role.",
                    "source_ids": ["e1"],
                },
                {
                    "type": "experience_evidence",
                    "text": "I reduced API latency by 40% using Redis caching at Initech.",
                    "source_ids": ["e1"],
                },
            ]
        }
    )
    orchestrator = AgentCoverLetter(
        job_snapshot=_SnapshotStub(),
        profile_data=_PROFILE,
        llm_fn=lambda prompt, system: grounded_output,
    )
    result = orchestrator.run(
        evidence_bullets=["Reduced API latency by 40% using Redis caching."]
    )
    assert result.decision == "agent_ok"
    assert result.fact_drift is not None
    assert result.fact_drift.has_blocking_drift is False


def test_agent_number_drift_triggers_fallback() -> None:
    drift_output = json.dumps(
        {
            "paragraphs": [
                {
                    "type": "experience_evidence",
                    "text": "I reduced latency by 99% which is fabricated.",
                    "source_ids": ["e1"],
                }
            ]
        }
    )
    orchestrator = AgentCoverLetter(
        job_snapshot=_SnapshotStub(),
        profile_data=_PROFILE,
        llm_fn=lambda prompt, system: drift_output,
    )
    result = orchestrator.run(evidence_bullets=["Reduced API latency by 40%."])
    assert result.decision == "agent_drift_fallback"
    assert result.fact_drift is not None
    assert "99%" in result.fact_drift.number_drift


def test_agent_raising_triggers_fallback() -> None:
    def _boom(prompt: str, system: str = "") -> str:
        raise RuntimeError("LLM exploded")

    orchestrator = AgentCoverLetter(
        job_snapshot=_SnapshotStub(),
        profile_data=_PROFILE,
        llm_fn=_boom,
    )
    result = orchestrator.run(evidence_bullets=["Some evidence."])
    assert result.decision == "agent_error_fallback"
    assert result.agent_error is not None and "LLM exploded" in result.agent_error
    assert result.document is not None  # deterministic doc was built


def test_agent_returning_none_triggers_fallback() -> None:
    orchestrator = AgentCoverLetter(
        job_snapshot=_SnapshotStub(),
        profile_data=_PROFILE,
        llm_fn=lambda prompt, system: None,
    )
    result = orchestrator.run(evidence_bullets=["Some evidence."])
    assert result.decision == "agent_error_fallback"
    assert "None" in (result.agent_error or "")


def test_agent_malformed_output_triggers_fallback() -> None:
    orchestrator = AgentCoverLetter(
        job_snapshot=_SnapshotStub(),
        profile_data=_PROFILE,
        llm_fn=lambda prompt, system: "this is not json",
    )
    result = orchestrator.run(evidence_bullets=["Some evidence."])
    assert result.decision == "agent_error_fallback"


def test_evidence_auto_selected_when_not_provided() -> None:
    """The orchestrator should fall back to the profile's work-
    experience bullets when no evidence is passed."""
    output = json.dumps(
        {"paragraphs": [{"type": "opening", "text": "hello", "source_ids": []}]}
    )
    orchestrator = AgentCoverLetter(
        job_snapshot=_SnapshotStub(),
        profile_data=_PROFILE,
        llm_fn=lambda prompt, system: output,
    )
    result = orchestrator.run()
    assert result.used_evidence  # not empty
