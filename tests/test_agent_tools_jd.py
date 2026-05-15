"""Phase 15.6: tests for the jd_lookup agent tool.

We use a plain dataclass stand-in for ``JobSnapshot`` so the tool
stays decoupled from the ORM and the test does not need a DB.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.agent.tools.base import ToolError
from src.agent.tools.jd import JdLookupTool


@dataclass
class _StubSnapshot:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = "Software Engineer Intern"
    location: str = "Remote (CA)"
    employment_type: str = "intern"
    seniority: str = "intern"
    description: str = "Long description body...\n" * 50
    application_url: str = "https://example.com/apply/123"
    content_hash: str = "abc123"
    requirements: dict[str, Any] = field(
        default_factory=lambda: {
            "must_have": ["python", "fastapi"],
            "preferred": ["react"],
            "years_experience": 0,
        }
    )
    raw_data: dict[str, Any] = field(default_factory=lambda: {"posted_at": "2026-05-01"})


# ---- Construction ----------------------------------------------------


def test_tool_rejects_none_snapshot() -> None:
    with pytest.raises(ToolError):
        JdLookupTool(None)  # type: ignore[arg-type]


def test_snapshot_id_defaults_to_object_id() -> None:
    snap = _StubSnapshot()
    tool = JdLookupTool(snap)
    assert tool._snapshot_id == str(snap.id)


def test_snapshot_id_can_be_overridden() -> None:
    snap = _StubSnapshot()
    explicit = uuid.uuid4()
    tool = JdLookupTool(snap, snapshot_id=explicit)
    assert tool._snapshot_id == str(explicit)


# ---- Section index ---------------------------------------------------


def test_empty_path_returns_section_index() -> None:
    tool = JdLookupTool(_StubSnapshot())
    result = tool.run({})
    assert result.is_error is False
    payload = json.loads(result.output)
    assert "scalar_paths" in payload
    assert "title" in payload["scalar_paths"]
    assert "requirements" in payload["nested_paths"]
    assert "raw_data" in payload["nested_paths"]


def test_section_index_includes_snapshot_id() -> None:
    snap = _StubSnapshot()
    tool = JdLookupTool(snap)
    payload = json.loads(tool.run({}).output)
    assert payload["snapshot_id"] == str(snap.id)


def test_section_index_omits_empty_fields() -> None:
    snap = _StubSnapshot()
    snap.location = None  # type: ignore[assignment]
    tool = JdLookupTool(snap)
    payload = json.loads(tool.run({}).output)
    assert "location" not in payload["scalar_paths"]
    assert "title" in payload["scalar_paths"]


# ---- Scalar lookups --------------------------------------------------


def test_scalar_lookup_returns_value() -> None:
    tool = JdLookupTool(_StubSnapshot())
    result = tool.run({"path": "title"})
    assert result.output == "Software Engineer Intern"
    assert result.is_error is False


def test_scalar_lookup_truncates_long_value() -> None:
    snap = _StubSnapshot(description="x" * 10000)
    tool = JdLookupTool(snap)
    result = tool.run({"path": "description"})
    assert len(result.output) <= 4000
    assert result.output.endswith("[truncated]")


def test_scalar_lookup_handles_missing_value() -> None:
    snap = _StubSnapshot(application_url=None)  # type: ignore[arg-type]
    tool = JdLookupTool(snap)
    result = tool.run({"path": "application_url"})
    assert result.is_error is False
    assert "not set" in result.output


# ---- Nested lookups --------------------------------------------------


def test_nested_top_path_returns_summary() -> None:
    tool = JdLookupTool(_StubSnapshot())
    payload = json.loads(tool.run({"path": "requirements"}).output)
    assert payload["_count"] == 3
    assert set(payload["keys"]) == {"must_have", "preferred", "years_experience"}


def test_nested_drill_returns_list() -> None:
    tool = JdLookupTool(_StubSnapshot())
    payload = json.loads(tool.run({"path": "requirements.must_have"}).output)
    assert payload["_count"] == 2
    assert "python" in payload["items_preview"]


def test_nested_drill_returns_scalar() -> None:
    tool = JdLookupTool(_StubSnapshot())
    result = tool.run({"path": "requirements.years_experience"})
    assert result.output == "0"


def test_nested_drill_missing_path_lists_keys() -> None:
    tool = JdLookupTool(_StubSnapshot())
    result = tool.run({"path": "requirements.nope"})
    assert result.is_error is False
    assert "not found" in result.output
    assert "must_have" in result.output  # available keys listed


def test_nested_drill_into_dict_in_jsonb() -> None:
    snap = _StubSnapshot()
    snap.requirements["education"] = {"min": "bachelors", "majors": ["cs"]}
    tool = JdLookupTool(snap)
    payload = json.loads(tool.run({"path": "requirements.education"}).output)
    assert payload["_count"] == 2
    assert "min" in payload["keys"]
    deeper = tool.run({"path": "requirements.education.min"})
    assert deeper.output == "bachelors"


def test_nested_drill_with_list_index() -> None:
    snap = _StubSnapshot()
    snap.raw_data["benefits"] = ["health", "401k", "gym"]
    tool = JdLookupTool(snap)
    result = tool.run({"path": "raw_data.benefits.1"})
    assert result.output == "401k"
    out_of_range = tool.run({"path": "raw_data.benefits.99"})
    assert "not found" in out_of_range.output


def test_nested_non_structured_field_is_error() -> None:
    snap = _StubSnapshot()
    snap.requirements = "not a dict"  # type: ignore[assignment]
    tool = JdLookupTool(snap)
    result = tool.run({"path": "requirements"})
    assert result.is_error is True


# ---- Unknown paths ---------------------------------------------------


def test_unknown_top_path_lists_known_paths() -> None:
    tool = JdLookupTool(_StubSnapshot())
    result = tool.run({"path": "salary"})
    assert result.is_error is False
    assert "title" in result.output and "requirements" in result.output


# ---- Read-only contract ----------------------------------------------


def test_tool_does_not_mutate_snapshot() -> None:
    """Reading a section index then drilling into it must not change
    the snapshot's underlying data."""
    snap = _StubSnapshot()
    original = {
        "title": snap.title,
        "must_have": list(snap.requirements["must_have"]),
        "raw_data": dict(snap.raw_data),
    }
    tool = JdLookupTool(snap)
    tool.run({})
    tool.run({"path": "requirements.must_have"})
    tool.run({"path": "raw_data.posted_at"})
    assert snap.title == original["title"]
    assert snap.requirements["must_have"] == original["must_have"]
    assert snap.raw_data == original["raw_data"]
