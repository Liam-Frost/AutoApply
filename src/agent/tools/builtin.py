"""Built-in tools shipped with the harness.

These are intentionally small, side-effect-free, and useful for proving
the loop end-to-end. Heavier business tools (browser, db, generators)
will be added in Phase 9 once the loop is stable.
"""

from __future__ import annotations

from pathlib import Path

from src.agent.tools.base import Tool, ToolError, ToolRegistry, ToolResult
from src.core.config import PROJECT_ROOT

_MAX_READ_BYTES = 200_000


class FileReadTool(Tool):
    """Read a UTF-8 file from inside the project data directory.

    Path is resolved relative to the data dir and rejected if it
    escapes via .. or absolute paths -- the agent must not be able to
    read arbitrary files on disk.
    """

    name = "fs_read"
    description = (
        "Read a UTF-8 text file from the project data directory. "
        "Use a relative path like 'jobs/foo.json'. "
        "Returns at most ~200 KB; truncates with a notice beyond that."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path under the data directory.",
            }
        },
        "required": ["path"],
    }

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir

    def _resolve(self, rel: str) -> Path:
        base = (self._base_dir or PROJECT_ROOT / "data").resolve()
        candidate = (base / rel).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise ToolError(f"Path '{rel}' escapes the data directory.") from exc
        return candidate

    def run(self, args: dict) -> ToolResult:
        rel = args.get("path", "")
        if not isinstance(rel, str) or not rel.strip():
            raise ToolError("'path' must be a non-empty string.")
        target = self._resolve(rel.strip())
        if not target.exists():
            raise ToolError(f"File '{rel}' not found.")
        if not target.is_file():
            raise ToolError(f"Path '{rel}' is not a file.")
        # Stream up to the cap (+ a small look-ahead so we can tell whether
        # the file is larger). Reading byte-by-byte avoids loading the
        # entire file when it exceeds the limit.
        with target.open("rb") as fh:
            raw = fh.read(_MAX_READ_BYTES)
            truncated = bool(fh.read(1))
        if truncated:
            # On truncation we may have sliced through a multi-byte UTF-8
            # codepoint. Walk back at most 3 bytes to land on a valid
            # boundary so decode() doesn't fail on otherwise-readable text.
            for _ in range(3):
                try:
                    text = raw.decode("utf-8")
                    break
                except UnicodeDecodeError:
                    if not raw:
                        text = ""
                        break
                    raw = raw[:-1]
            else:
                text = raw.decode("utf-8", errors="replace")
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ToolError(f"File '{rel}' is not valid UTF-8: {exc}") from exc
        suffix = "\n[truncated]" if truncated else ""
        return ToolResult(
            output=text + suffix,
            data={"path": rel, "bytes": len(raw), "truncated": truncated},
        )


class TextSummarizeTool(Tool):
    """Trivial deterministic summarizer used in eval fixtures.

    Not LLM-based on purpose -- gives the loop a noiseless tool to
    exercise the registry and observation flow in tests.
    """

    name = "text_stats"
    description = (
        "Compute simple statistics about a piece of text "
        "(word count, character count, first 80 chars)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to inspect."},
        },
        "required": ["text"],
    }

    def run(self, args: dict) -> ToolResult:
        text = args.get("text", "")
        if not isinstance(text, str):
            raise ToolError("'text' must be a string.")
        words = len(text.split())
        chars = len(text)
        preview = text.strip().replace("\n", " ")[:80]
        return ToolResult(
            output=f"words={words} chars={chars} preview={preview!r}",
            data={"words": words, "chars": chars, "preview": preview},
        )


class FinishTool(Tool):
    """Sentinel tool the agent calls to terminate the loop with a result.

    The loop intercepts this rather than running it; we still register a
    handler so the schema renders correctly in the prompt.
    """

    name = "finish"
    description = (
        "Stop the loop and return a final answer to the orchestrator. "
        "Call this exactly once when the task is complete."
    )
    parameters = {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "Final answer for the caller.",
            }
        },
        "required": ["answer"],
    }

    def run(self, args: dict) -> ToolResult:
        answer = args.get("answer", "")
        return ToolResult(output=str(answer), data={"answer": str(answer)})


def register_builtin_tools(registry: ToolRegistry) -> None:
    registry.register(FileReadTool())
    registry.register(TextSummarizeTool())
    registry.register(FinishTool())
