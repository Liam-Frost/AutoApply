"""Tests for ProfileLookupTool (Phase 9.2)."""

from __future__ import annotations

import json

from src.agent.tools.profile import ProfileLookupTool

PROFILE = {
    "identity": {
        "full_name": "Liam Liu",
        "email": "frostnova986@gmail.com",
        "phone": "672-968-6198",
        "location": "Vancouver, BC",
    },
    "education": [
        {
            "institution": "University of British Columbia",
            "degree": "Bachelor of Applied Science",
            "field": "Computer Engineering",
            "gpa": "3.95",
        },
        {
            "institution": "China University of Political Science and Law",
            "degree": "Bachelor of Science",
            "field": "Psychology",
        },
    ],
    "work_experiences": [
        {"company": "EA Academy Canada", "title": "Academic Tutor"},
    ],
}


class TestScalarLookup:
    def test_returns_string_value(self) -> None:
        tool = ProfileLookupTool(PROFILE)
        result = tool.spec().invoke({"path": "identity.email"})
        assert not result.is_error
        assert result.output == "frostnova986@gmail.com"
        assert result.data["value"] == "frostnova986@gmail.com"

    def test_indexed_list_path(self) -> None:
        tool = ProfileLookupTool(PROFILE)
        result = tool.spec().invoke({"path": "education[0].institution"})
        assert not result.is_error
        assert result.output == "University of British Columbia"

    def test_nested_index_then_key(self) -> None:
        tool = ProfileLookupTool(PROFILE)
        result = tool.spec().invoke({"path": "education[1].field"})
        assert result.output == "Psychology"


class TestContainerLookup:
    def test_list_returns_count_and_preview(self) -> None:
        tool = ProfileLookupTool(PROFILE)
        result = tool.spec().invoke({"path": "education"})
        assert not result.is_error
        payload = json.loads(result.output)
        assert payload["_count"] == 2
        # Preview elements are dicts -- coercion preserves structure.
        assert payload["preview"][0]["institution"] == "University of British Columbia"

    def test_dict_returns_keys(self) -> None:
        tool = ProfileLookupTool(PROFILE)
        result = tool.spec().invoke({"path": "identity"})
        assert not result.is_error
        payload = json.loads(result.output)
        assert "_keys" in payload
        assert set(payload["_keys"]) == set(PROFILE["identity"].keys())


class TestErrorPaths:
    def test_missing_key_is_recoverable_error(self) -> None:
        tool = ProfileLookupTool(PROFILE)
        result = tool.spec().invoke({"path": "identity.middle_name"})
        assert result.is_error
        assert "not found" in result.output

    def test_index_out_of_range(self) -> None:
        tool = ProfileLookupTool(PROFILE)
        result = tool.spec().invoke({"path": "education[5].institution"})
        assert result.is_error
        assert "index error" in result.output

    def test_non_integer_index_rejected(self) -> None:
        tool = ProfileLookupTool(PROFILE)
        result = tool.spec().invoke({"path": "education[abc].institution"})
        assert result.is_error
        assert "Invalid path" in result.output

    def test_empty_path_rejected(self) -> None:
        tool = ProfileLookupTool(PROFILE)
        result = tool.spec().invoke({"path": ""})
        assert result.is_error

    def test_path_must_start_with_key(self) -> None:
        tool = ProfileLookupTool(PROFILE)
        result = tool.spec().invoke({"path": "[0].x"})
        assert result.is_error

    def test_unterminated_bracket(self) -> None:
        tool = ProfileLookupTool(PROFILE)
        result = tool.spec().invoke({"path": "education[0"})
        assert result.is_error
        assert "unterminated" in result.output


class TestDenylist:
    def test_denied_section_blocked(self) -> None:
        tool = ProfileLookupTool(PROFILE, denylist={"identity"})
        result = tool.spec().invoke({"path": "identity.email"})
        assert result.is_error
        assert "blocked" in result.output

    def test_other_sections_still_readable(self) -> None:
        tool = ProfileLookupTool(PROFILE, denylist={"identity"})
        result = tool.spec().invoke({"path": "education[0].institution"})
        assert not result.is_error


class TestTruncation:
    def test_long_string_truncated(self) -> None:
        big = "x" * 10_000
        tool = ProfileLookupTool({"notes": big})
        result = tool.spec().invoke({"path": "notes"})
        assert not result.is_error
        assert result.output.endswith("[truncated]")
        assert len(result.output) <= 4_000

    def test_data_preserves_full_value(self) -> None:
        # Truncation only affects the agent observation; structured data
        # stays intact for trace consumers.
        big = "x" * 10_000
        tool = ProfileLookupTool({"notes": big})
        result = tool.spec().invoke({"path": "notes"})
        assert result.data["value"] == big
