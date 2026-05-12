# Agent Architecture

This document describes the agent harness introduced in Phase 8 and
extended for the form-filler in Phase 9. It is the source of truth
for how AutoApply confines an LLM-driven loop, and *should* answer
the question "could the agent click submit on my behalf?" before you
even open the code.

## Why we have this

Form pages are infinitely varied. The deterministic `form_filler.py`
covers the 80% case (label-keyword matching), but every new vendor
or custom question breaks it slightly differently. We want a layer
that can read a page, decide what to fill, and ask for help when
unsure -- without ever actually submitting on our behalf.

The harness is **not** an autonomous agent. It is a confined ReAct
loop with strict guard rails:

* The agent only sees the tools we register, never the open
  internet, the database, or the live `Page`.
* All side-effecting actions (filling, clicking, submitting, file
  writes outside the data dir) are performed by the orchestrator
  *after* the agent finishes -- and submission requires the human
  to approve the action through the gate.
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

Phase 9 only converts one node -- form filling -- to agent mode. The
rest of the pipeline (intake, matching, generation, document
rendering, submit clicks) is unchanged.

```
intake → matching → generation → execution
                                  │
                                  ├── form_filler.py        (deterministic, default)
                                  └── agent_form_filler.py  (Phase 9 agent)
                                  
                                  Both feed → submit gate → click submit
```

Selection is currently per-call. The orchestrator entry point lives
in `src/execution/agent_form_filler.py`; the deterministic path
remains in `src/execution/form_filler.py`. Either one can fall back
to the other (the agent orchestrator drops to rules when the agent
crashes or produces no proposals).

## The HITL contract

Two gate kinds exist. Both are file-backed under
`data/agent_gate/<id>.json` and surfaced in the web GUI viewer:

| Kind                | When parked                                         |
|---------------------|-----------------------------------------------------|
| `form_fill_review`  | Any agent proposal scored below `min_confidence`.   |
| `submit_form`       | Always before any submit click.                     |

`form_fill_review` is a soft gate: the orchestrator returns the
review request id without applying anything; the caller polls the
gate, and once approved calls `apply_after_review(...)`.

`submit_form` is a hard gate: `AgentFormFiller.submit()` raises
`PermissionError` unless the request status is `APPROVED`. There is
no override, no "force" flag.

Default thresholds (configurable via `AgentFormFillerConfig`):

* `min_confidence = 0.7` -- below this any proposal triggers review
* `always_review = True`  -- any successful run still goes through
  review (this can be disabled per-vendor once the eval suite shows
  stable behaviour)
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

Surfaces:

* `autoapply eval --suite <name>`: per-case + suite totals
* Web trace viewer: per-step + per-trace pills
* Persisted trace JSON: `total_prompt_tokens`, `total_output_tokens`,
  `total_cost_usd`

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

## What is *not* in scope (yet)

* Multi-step / multi-page agents (we run one snapshot per page).
* Provider-native tool use protocol (we still use a ReAct JSON
  protocol so both `claude` and `codex` CLIs work, and so the new
  Phase 10 REST adapters get the same loop for free).
* Cover-letter generation as an agent -- **Phase 14** (the original
  Phase 10 plan slid down two slots once Phase 10 became the LLM
  provider abstraction and Phase 11-13 inserted reliability /
  caching / scheduler foundations).
* Matching / filter agent + explainability -- **Phase 15**.
* Daily nightly run loop + review queue (the original
  "multi-agent orchestrator" idea, descoped to a batch + queue
  pattern) -- **Phase 16**.

See `docs/PROJECT_MANAGEMENT.md` for the full Phase 11-16 roadmap,
including the two new cross-cutting infrastructure phases
(caching and scheduled tasks) that unblock the agent work.

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
| `src/agent/gate/queue.py`                         | File-backed approval queue |
| `src/agent/trace/store.py`                        | JSON-on-disk trace store |
| `src/agent/eval/runner.py`                        | Fixture-driven eval harness |
| `src/agent/eval/scorers.py`                       | Built-in scorers (incl. `field_mapping_match`) |
| `src/execution/agent_form_filler.py`              | Phase 9 orchestrator |
| `src/execution/form_filler.py`                    | Deterministic Playwright filler (still default) |
| `src/web/routes/agent.py`                         | `/api/agent/...` viewer + gate routes |
