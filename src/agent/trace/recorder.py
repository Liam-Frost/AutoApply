"""Run an agent session and persist the resulting trace."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.agent.core.loop import (
    AgentResult,
    AgentSession,
    LLMCallable,
    SessionLimits,
)
from src.agent.tools.base import ToolRegistry
from src.agent.trace.store import TraceRecord, TraceStore, record_from_result


def record_agent_run(
    *,
    goal: str,
    tools: ToolRegistry,
    llm: LLMCallable,
    limits: SessionLimits | None = None,
    metadata: dict[str, Any] | None = None,
    store: TraceStore | None = None,
) -> tuple[AgentResult, TraceRecord]:
    """Run an agent session, persist a trace, and return both."""
    started = datetime.now(UTC)
    session = AgentSession(goal=goal, tools=tools, llm=llm, limits=limits)
    result = session.run()

    record = record_from_result(
        result,
        tools_allowed=tools.names(),
        metadata=metadata,
        started_at=started,
    )
    (store or TraceStore()).save(record)
    return result, record
