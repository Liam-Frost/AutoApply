"""AutoApply agent harness.

Phase 8 introduces a controlled-autonomy layer on top of the existing
deterministic pipeline. The harness has five pieces:

    tools/   -- uniform Tool interface + registry (8.1)
    core/    -- bounded agent loop driving an LLM with limited tools (8.2)
    trace/   -- step-level recording and replay storage (8.3)
    eval/    -- fixture-driven regression harness (8.4)
    gate/    -- human-in-the-loop approval queue for irreversible actions (8.5)

Agents are *summoned* by the orchestrator for narrow tasks. They never
take irreversible actions directly -- those flow through the gate.
"""
