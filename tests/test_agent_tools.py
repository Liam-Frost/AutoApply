"""Tests for the Phase 8 tool layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.tools import (
    Tool,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    get_default_registry,
)
from src.agent.tools.builtin import (
    FileReadTool,
    FinishTool,
    TextSummarizeTool,
    register_builtin_tools,
)


class _Echo(Tool):
    name = "echo"
    description = "Echo back the message."
    parameters = {
        "type": "object",
        "properties": {"msg": {"type": "string"}},
        "required": ["msg"],
    }

    def run(self, args):
        return ToolResult(output=args["msg"], data={"msg": args["msg"]})


class TestToolSpec:
    def test_invoke_validates_required_args(self):
        spec = _Echo().spec()
        result = spec.invoke({})
        assert result.is_error
        assert "missing required args" in result.output

    def test_invoke_rejects_non_dict_args(self):
        spec = _Echo().spec()
        result = spec.invoke("not a dict")  # type: ignore[arg-type]
        assert result.is_error
        assert "expected an object" in result.output

    def test_invoke_converts_handler_exception_to_error_result(self):
        def boom(_args):
            raise RuntimeError("kaboom")

        spec = ToolSpec(name="boom", description="", parameters={}, handler=boom)
        result = spec.invoke({})
        assert result.is_error
        assert "RuntimeError" in result.output
        assert "kaboom" in result.output

    def test_invoke_translates_tool_error_message_only(self):
        def fail(_args):
            raise ToolError("nope")

        spec = ToolSpec(name="fail", description="", parameters={}, handler=fail)
        result = spec.invoke({})
        assert result.is_error
        assert result.output == "nope"

    def test_invoke_wraps_non_toolresult_returns(self):
        def plain(_args):
            return {"x": 1}

        spec = ToolSpec(name="plain", description="", parameters={}, handler=plain)
        result = spec.invoke({})
        assert not result.is_error
        assert result.data == {"raw": {"x": 1}}


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        reg.register(_Echo())
        assert "echo" in reg
        assert reg.get("echo").name == "echo"

    def test_double_register_raises(self):
        reg = ToolRegistry()
        reg.register(_Echo())
        with pytest.raises(ValueError):
            reg.register(_Echo())

    def test_view_filters_to_allowed(self):
        reg = ToolRegistry()
        reg.register(_Echo())
        reg.register(FinishTool())
        sub = reg.view(["finish"])
        assert sub.names() == ["finish"]
        assert "echo" not in sub

    def test_view_unknown_name_raises(self):
        reg = ToolRegistry()
        reg.register(_Echo())
        with pytest.raises(KeyError):
            reg.view(["nope"])

    def test_render_for_prompt_is_json(self):
        import json

        reg = ToolRegistry()
        reg.register(_Echo())
        rendered = json.loads(reg.render_for_prompt())
        assert rendered[0]["name"] == "echo"
        assert rendered[0]["parameters"]["required"] == ["msg"]


class TestFileReadTool:
    def test_reads_relative_path(self, tmp_path: Path):
        (tmp_path / "hello.txt").write_text("hi", encoding="utf-8")
        tool = FileReadTool(base_dir=tmp_path)
        result = tool.spec().invoke({"path": "hello.txt"})
        assert not result.is_error
        assert result.output == "hi"
        assert result.data["bytes"] == 2

    def test_rejects_traversal(self, tmp_path: Path):
        tool = FileReadTool(base_dir=tmp_path)
        result = tool.spec().invoke({"path": "../etc/passwd"})
        assert result.is_error
        assert "escapes" in result.output

    def test_rejects_missing(self, tmp_path: Path):
        tool = FileReadTool(base_dir=tmp_path)
        result = tool.spec().invoke({"path": "ghost.txt"})
        assert result.is_error
        assert "not found" in result.output

    def test_truncates_large_files(self, tmp_path: Path):
        big = tmp_path / "big.txt"
        big.write_bytes(b"a" * 250_000)
        tool = FileReadTool(base_dir=tmp_path)
        result = tool.spec().invoke({"path": "big.txt"})
        assert not result.is_error
        assert result.data["truncated"] is True
        assert result.output.endswith("[truncated]")

    def test_truncation_handles_utf8_boundary(self, tmp_path: Path):
        # Place a 3-byte UTF-8 character (中, 0xE4 0xB8 0xAD) so it straddles
        # the truncation point. Without boundary handling, decode() fails.
        from src.agent.tools.builtin import _MAX_READ_BYTES

        path = tmp_path / "chinese.txt"
        # Pad so that the multi-byte char crosses the byte cap.
        prefix = b"a" * (_MAX_READ_BYTES - 1)
        body = prefix + "中".encode() + b"a" * 100
        path.write_bytes(body)

        tool = FileReadTool(base_dir=tmp_path)
        result = tool.spec().invoke({"path": "chinese.txt"})
        assert not result.is_error
        assert result.data["truncated"] is True
        # The straddling character is dropped, but earlier ASCII content
        # decodes cleanly and the cap is honored.
        assert result.output.startswith("a")


class TestTextStatsTool:
    def test_basic_stats(self):
        result = TextSummarizeTool().spec().invoke({"text": "hello world"})
        assert not result.is_error
        assert result.data == {
            "words": 2,
            "chars": 11,
            "preview": "hello world",
        }


class TestDefaultRegistry:
    def test_builtin_tools_registered(self):
        reg = ToolRegistry()
        register_builtin_tools(reg)
        assert set(reg.names()) == {"fs_read", "text_stats", "finish"}

    def test_default_registry_is_cached(self):
        reg1 = get_default_registry()
        reg2 = get_default_registry()
        assert reg1 is reg2
