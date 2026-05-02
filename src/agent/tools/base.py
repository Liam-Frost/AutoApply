"""Tool ABC, registry, and result types.

A Tool is a deterministic capability the agent loop can invoke. Each tool
has a JSON-schema description so the LLM can be told what arguments are
valid, plus a synchronous handler that returns a structured ToolResult.

The registry supports allow-listing: an agent session is given a subset
of tools, never the full set. This is the primary control mechanism --
the loop physically cannot call a tool the orchestrator did not grant.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class ToolError(Exception):
    """Raised when a tool fails. The message is shown to the agent as an
    observation so it can recover; do not put secrets in it."""


@dataclass
class ToolResult:
    """Return value from a tool invocation.

    `output` is what the agent sees as observation text.
    `data` is the structured payload (JSON-serializable) for trace/UI.
    `is_error` flips the observation channel; the loop converts errors
    into observable feedback rather than aborting.
    """

    output: str
    data: dict[str, Any] = field(default_factory=dict)
    is_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"output": self.output, "data": self.data, "is_error": self.is_error}


class Tool(ABC):
    """Subclass to add a new tool. `name`, `description`, and `parameters`
    are class-level metadata used to render the tool to the LLM."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    @abstractmethod
    def run(self, args: dict[str, Any]) -> ToolResult: ...

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            handler=self.run,
        )


@dataclass
class ToolSpec:
    """Lightweight registration record. Use this when wrapping a plain
    callable rather than subclassing Tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], ToolResult]

    def to_schema(self) -> dict[str, Any]:
        """Render to the schema shape consumed by the loop's prompt."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def invoke(self, args: dict[str, Any]) -> ToolResult:
        """Run the handler with arg validation. Catches handler exceptions
        and converts them into error ToolResults so the loop can continue."""
        if not isinstance(args, dict):
            return ToolResult(
                output=(
                    f"Tool '{self.name}' expected an object for args, "
                    f"got {type(args).__name__}."
                ),
                is_error=True,
            )

        missing = _missing_required(self.parameters, args)
        if missing:
            return ToolResult(
                output=f"Tool '{self.name}' missing required args: {sorted(missing)}.",
                is_error=True,
            )

        try:
            result = self.handler(args)
        except ToolError as exc:
            return ToolResult(output=str(exc), is_error=True)
        except Exception as exc:  # noqa: BLE001 -- defensive boundary
            return ToolResult(
                output=f"Tool '{self.name}' raised {type(exc).__name__}: {exc}",
                is_error=True,
            )

        if not isinstance(result, ToolResult):
            return ToolResult(
                output=str(result) if result is not None else "",
                data={"raw": _safe_json(result)},
            )
        return result


class ToolRegistry:
    """Holds available ToolSpecs and produces filtered views."""

    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, tool: Tool | ToolSpec) -> None:
        spec = tool.spec() if isinstance(tool, Tool) else tool
        if not spec.name:
            raise ValueError("Tool name is required.")
        if spec.name in self._specs:
            raise ValueError(f"Tool '{spec.name}' is already registered.")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        if name not in self._specs:
            raise KeyError(f"Tool '{name}' is not registered.")
        return self._specs[name]

    def names(self) -> list[str]:
        return sorted(self._specs)

    def view(self, allowed: list[str] | None = None) -> ToolRegistry:
        """Return a new registry containing only the named tools.

        Used by the agent loop to restrict what a session can call.
        Unknown names raise so misconfiguration fails loudly."""
        if allowed is None:
            return self
        sub = ToolRegistry()
        for name in allowed:
            sub.register(self.get(name))
        return sub

    def render_for_prompt(self) -> str:
        """Serialize tool specs to JSON for the agent prompt."""
        return json.dumps([spec.to_schema() for spec in self._specs.values()], indent=2)

    def __contains__(self, name: str) -> bool:
        return name in self._specs

    def __len__(self) -> int:
        return len(self._specs)


_default_registry: ToolRegistry | None = None


def get_default_registry() -> ToolRegistry:
    """Process-wide registry populated by builtin tools on first access."""
    global _default_registry
    if _default_registry is None:
        from src.agent.tools.builtin import register_builtin_tools

        registry = ToolRegistry()
        register_builtin_tools(registry)
        _default_registry = registry
    return _default_registry


def _missing_required(schema: dict[str, Any], args: dict[str, Any]) -> set[str]:
    required = schema.get("required") or []
    return {key for key in required if key not in args}


def _safe_json(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return repr(value)
