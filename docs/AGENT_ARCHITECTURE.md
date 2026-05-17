# Agent Architecture

This document describes AutoApply's bounded agent harness. It is the
source of truth for how LLM-driven loops are confined, audited, and
connected to human review.

## Why we have this

Job applications involve varied forms, job descriptions, templates,
and edge-case judgments. Deterministic code handles the stable parts;
agents are used only where bounded judgment helps: form-fill proposals,
cover-letter drafting, template-adapter suggestions, and borderline fit
review.

The harness is **not** an autonomous agent. It is a confined ReAct
loop with strict guard rails:

* The agent only sees the tools we register, never the open
  internet, the database, or the live `Page`.
* All side-effecting actions are performed by an orchestrator after the
  agent returns a structured proposal. Submission requires explicit
  approval through the review/gate flow.
* Every step is recorded into a JSON trace.

## Three-layer architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  Orchestrator (e.g. AgentFormFiller)                             │
│    • holds the live Playwright Page, profile data, gate          │
│    • builds a PageSnapshot, screenshots, instantiates tools      │
│    • runs the agent loop and reads back proposals                │
│    • applies fills via deterministic fill_fields()               │
│    • parks gate requests for HITL review and submit              │
└──────────────────┬───────────────────────────────────────────────┘
                   │  hands a ToolRegistry view + an LLM callable
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Agent loop (src/agent/core/loop.py)                             │
│    • bounded ReAct: max_steps, step_timeout, allow_tool_errors   │
│    • parses {thought, action: {name, args}} JSON each turn       │
│    • can ONLY call tools the orchestrator allow-listed           │
│    • emits AgentSteps with token + cost telemetry                │
└──────────────────┬───────────────────────────────────────────────┘
                   │  invokes ToolSpec.handler(args)
                   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Tools (src/agent/tools/*)                                       │
│    • each tool is a sync, side-effect-free function with a       │
│      JSON-schema parameter spec                                  │
│    • for the form-filler: browser_inspect_page,                  │
│      browser_find_field, browser_propose_fill,                   │
│      browser_screenshot, profile_lookup, finish                  │
│    • there is no Playwright handle anywhere in this layer        │
└──────────────────────────────────────────────────────────────────┘
```

The arrows go strictly downward. Tools do not call orchestrator
methods. The agent loop does not call Playwright. This is what makes
the confinement story believable.

## What runs in agent mode vs deterministic mode

Agents are narrow helpers, not the pipeline owner. Intake, job-index
state, task scheduling, document rendering, application state changes,
and submit clicks remain deterministic/orchestrator-owned.

```
intake → matching → generation → execution
          │           │             │
          │           │             ├── form_filler.py / agent_form_filler.py
          │           │             └── submit gate → approved submit
          │           ├── AgentCoverLetter for bounded drafting
          │           └── template adapter assistant for reusable manifests
          └── EdgeCaseAgent for borderline fit explanations
```

Selection is per call site. Each orchestrator decides whether to invoke
an agent, validates the response, and falls back to deterministic logic
when the agent errors, returns malformed output, or exceeds its scope.

## The HITL contract

Operational task flows use Postgres-backed review/gate state so workers
do not park while waiting for a person. The legacy file-backed gate
helpers remain for standalone/local harness compatibility, but product
flows should go through Postgres-backed routes.

Core gate kinds:

| Kind | When parked |
|---|---|
| `form_fill_review` | Agent form-fill proposal needs operator review. |
| `submit_form` | Submit action requires explicit approval. |
| `review_queue` entry | Plan-run prepared an application for approve/submit/discard. |
| `materials.*` gate | Persistent grounding mutation needs approval. |

`form_fill_review` is a soft gate: the orchestrator returns the
review request id without applying anything; the caller polls the
gate, and once approved calls `apply_after_review(...)`.

Submit gates are hard gates: submit actions must observe an approved
state before the click/task is allowed to continue. There is no hidden
"force submit" path for agents.

Default thresholds (configurable via `AgentFormFillerConfig`):

* `min_confidence = 0.7` -- below this a form-fill proposal triggers review
* `always_review = True` -- successful form-fill proposals still go through review unless a caller explicitly narrows this policy
* `submit_gate_ttl_seconds = 600`

## How profile data reaches the agent

`profile_lookup` is the only way. It exposes a dotted-path API
(`identity.email`, `education[0].institution`, etc.) and:

* Each call shows up as an observable AgentStep so reviewers can
  audit what data the agent fetched.
* Top-level sections can be denylisted (constructor argument).
* Container values come back as a `_count + preview` envelope so
  the agent learns the shape without us pasting the whole tree.

We deliberately do NOT paste the profile into the agent's prompt.
That would burn tokens every turn and make every future profile
field leak by default.

## Telemetry

Each `AgentStep` records `prompt_tokens`, `output_tokens`, and
`cost_usd`. CLI providers (claude-cli, codex-cli) don't surface real
counts so values are estimated via a chars/4 heuristic with
configurable rates:

```
AUTOAPPLY_AGENT_COST_PROMPT_PER_1K  default $0.003 / 1k tokens
AUTOAPPLY_AGENT_COST_OUTPUT_PER_1K  default $0.015 / 1k tokens
```

Treat the numbers as accurate to ~30%. They exist to spot order-of-
magnitude regressions, not to reconcile invoices.

Phase 11.1 adds `AgentStep.llm_attempts` -- a list of
`{provider, ok, kind, error, latency_ms}` records describing which
provider answered each turn. `src.utils.llm.generate_text` writes the
list into a `ContextVar` (`last_attempt_chain`) on every call; `_step`
in the agent loop snapshots it before constructing the AgentStep, also
pulling `LLMError.attempts` off the raised exception when the call
failed. The field is empty for tests that inject a stub LLM callable
bypassing `generate_text`.

Surfaces:

* `autoapply eval --suite <name>`: per-case + suite totals
* Web trace viewer: per-step + per-trace pills
* Persisted trace JSON: `total_prompt_tokens`, `total_output_tokens`,
  `total_cost_usd`, plus `steps[].llm_attempts` (Phase 11.1+)

## Eval

`autoapply eval --suite form_filler` runs five fixture forms with
scripted LLM transcripts (so CI is deterministic and free) and
checks that the agent proposes the expected values. Pass-rate
baseline lives at `tests/agent_evals/baselines/form_filler.json`;
PRs are gated on `--min-pass-rate 0.85`.

To add a fixture: drop a JSON file under
`tests/agent_evals/fixtures/form_filler/` with `html`, `profile`,
`llm_responses`, and `expectations`. Use the
`field_mapping_match` and `no_proposal_for_label` scorers documented
in `src/agent/eval/scorers.py`.

## Agent + Task Queue Boundary

Phase 14 adds a task queue so plan runs and material generation do
not live inside a long web request or one monolithic CLI command. The
queue is outside the agent harness:

```
Scheduler / Web / CLI
        |
        v
Postgres task record + Redis queue token
        |
        v
Worker claims one task
        |
        v
Bounded agent run, if that task needs judgment
        |
        v
Worker updates task state + trace + audit
```

The split is intentional. Workers own scheduling, claim/ack/nack,
timeouts, retries, heartbeats, and concurrency. Agents own only the
bounded decision inside one task. An agent result is structured as one
of: `success`, `failed_retryable`, `failed_terminal`, `needs_human`, or
`needs_followup_task`.

Agents do not write directly to Redis and do not mutate global task
state. If an agent needs follow-up work, it calls an allow-listed tool
that asks the task service to create a child task. If it needs human
input, the worker parks the task in `waiting_human` and links it to the
existing HITL gate/review item rather than retrying.

## What is not in scope

* Multi-step / multi-page agents (we run one snapshot per page).
* Provider-native tool use protocol (we still use a ReAct JSON
  protocol so both `claude` and `codex` CLIs work, and so the new
  Phase 10 REST adapters get the same loop for free).
* Unreviewed autonomous submission.
* Agents owning task queue state, database writes, Redis keys, or global
  scheduling.
* Hosted multi-tenant identity and policy enforcement; that is Phase 18
  product hardening rather than an agent-harness responsibility.

See `docs/PROJECT_MANAGEMENT.md` for the current roadmap and
verification baseline. See `docs/PHASE_HISTORY.md` for shipped phase
history.

## Reading the code

| File                                              | Role |
|---------------------------------------------------|------|
| `src/agent/tools/base.py`                         | Tool / ToolSpec / ToolRegistry primitives |
| `src/agent/tools/builtin.py`                      | `fs_read`, `text_stats`, `finish` |
| `src/agent/tools/browser.py`                      | Form-filler browser tools (read-only + propose) |
| `src/agent/tools/browser_models.py`               | `PageSnapshot`, `FieldDescriptor`, `FillProposal`, `ProposalCollector` |
| `src/agent/tools/profile.py`                      | `profile_lookup` |
| `src/agent/core/loop.py`                          | Bounded ReAct loop, telemetry plumbing |
| `src/agent/core/cost.py`                          | Token / cost estimation |
| `src/agent/gate/queue.py`                         | Legacy local approval queue helpers |
| `src/agent/trace/store.py`                        | JSON-on-disk trace store |
| `src/agent/eval/runner.py`                        | Fixture-driven eval harness |
| `src/agent/eval/scorers.py`                       | Built-in scorers (incl. `field_mapping_match`) |
| `src/execution/agent_form_filler.py`              | Phase 9 orchestrator |
| `src/execution/form_filler.py`                    | Deterministic Playwright filler (still default) |
| `src/web/routes/agent.py`                         | `/api/agent/...` viewer + gate routes |
| `src/tasks/tasks.py`                              | Celery task wrappers around bounded work |
| `src/application/review.py`                       | Review queue state machine and use cases |
