"""Tool layer: uniform interface for capabilities the agent can call."""

from src.agent.tools.base import (
    Tool,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    get_default_registry,
)
from src.agent.tools.browser_models import (
    FieldDescriptor,
    FillProposal,
    PageSnapshot,
    ProposalCollector,
)

__all__ = [
    "FieldDescriptor",
    "FillProposal",
    "PageSnapshot",
    "ProposalCollector",
    "Tool",
    "ToolError",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
    "get_default_registry",
]
