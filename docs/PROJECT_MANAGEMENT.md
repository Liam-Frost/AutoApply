# AutoApply — Project Management

## Overview

This document tracks development progress, decisions, and context for the AutoApply project. It is designed to be self-contained so that any AI assistant or developer can pick up where the previous session left off.

## Architecture Summary

AutoApply is a 7-layer modular job application automation system:

| Layer | Module | Purpose |
|-------|--------|---------|
| 1 | `src/intake/` | Scrape & standardize job postings from ATS (Greenhouse, Lever) and LinkedIn |
| 2 | `src/matching/` | Rule-based + semantic + risk filtering to score jobs |
| 3 | `src/memory/` | Structured applicant profile, bullet pool, story bank, QA bank |
| 4 | `src/generation/` | Resume/Cover Letter IR, evidence retrieval, fitting, validation, QA answering |
| 5 | `src/execution/` | Playwright browser automation, form filling, ATS adapters |
| 6 | `src/documents/` | DOCX/PDF creation, template packages, page counts, file versioning |
| 7 | `src/tracker/` | Application tracking, analytics, reporting |

| 8 | `src/application/` | Shared use-case layer consumed by CLI and Web |
| 9 | `src/web/` + `frontend/` | FastAPI JSON API + Vue SPA: dashboard, job search, Materials, tracking, profile, settings |

Orchestration lives in `src/core/` (agent, state machine, config).
Shared utilities in `src/utils/` (LLM CLI wrapper, rate limiter, logger).

## Tech Stack

- **Language**: Python 3.12+
- **Frontend**: Vue 3 + Vue Router + Vite
- **Web backend**: FastAPI JSON API
- **Package manager**: uv
- **Frontend package manager**: npm
- **Database**: PostgreSQL 16+ with pgvector
- **Browser automation**: Playwright
- **LLM**: Claude Code CLI (`claude -p`) + Codex CLI — invoked via subprocess, no API SDK
- **Document processing**: python-docx, docx2pdf / LibreOffice CLI
- **DB migrations**: Alembic + SQLAlchemy
- **Target platforms**: Greenhouse + Lever + Ashby for direct apply, LinkedIn for job discovery / ATS redirect extraction
- **Agent interface**: CLI with `--json` support for core commands

## Development Workflow

### Branching

- `master` — stable, merged after each completed Phase
- `dev` — active development, pushed after each sub-phase with code review

### Commit & Review Cadence

1. Write code for a sub-phase (e.g., Phase 1.1, 1.2, 1.3)
2. Run a Codex CLI or Claude Code CLI review for the current sub-phase
3. Address review findings
4. Commit with descriptive message → push to `dev`
5. After full Phase completion: final code review → merge `dev` into `master` → update docs

CLI role: agent-facing automation surface.
GUI role: human-facing operator console.

### Key Files

| File | Purpose |
|------|---------|
| `docs/plan_en.md` | Full implementation plan (English) |
| `docs/plan_zh.md` | Full implementation plan (Chinese) |
| `docs/PROJECT_MANAGEMENT.md` | This file — progress tracking & context |
| `docs/CHANGELOG.md` | Per-phase changelog |
| `docs/DECISIONS.md` | Architecture & design decisions log |
| `config/settings.yaml` | Runtime configuration |
| `config/.env.example` | Environment variable template |
| `data/templates/` | DOCX-first template packages for resume and cover letter generation |

## Phase Plan

### Phase 1: Infrastructure + Applicant Memory (Weeks 1-2)

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 1.1 | Project init: uv, PostgreSQL+pgvector, Alembic, config loader, LLM CLI wrapper, logging | **Complete** |
| 1.2 | Applicant Memory: profile YAML schema, resume importer, bullet pool, story bank, QA bank | **Complete** |
| 1.3 | Document Processing: Word template engine, block-based resume assembly, PDF conversion, file versioning | **Complete** |

**Verification**: Load profile YAML → ingest to DB → generate one tailored Word resume + PDF — **PASSED**
**Code Review**: Codex review run, 6 issues found and fixed (2 P1, 4 P2). See CHANGELOG.

### Phase 2: Job Intake + Smart Filtering (Weeks 3-4)

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 2.1 | Job schema, Greenhouse scraper, Lever scraper, JD parsing, filters, search CLI | **Complete** |
| 2.2 | Hard rule filters, semantic matching, composite scorer, low-quality job filtering | **Complete** |

**Verification**: Scrape Greenhouse jobs → score & rank → output top-N list
**Code Review**: 8 P1 and 7 P2 issues found and fixed. See CHANGELOG.

### Phase 3: Resume/CL Tailoring + QA (Weeks 5-6)

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 3.1 | JD keyword extraction, bullet selection, lexical rewrite, fact-drift check | **Complete** |
| 3.2 | Cover letter generation (structure-constrained), company research | **Complete** |
| 3.3 | Quick question answering (classify → match → generate → review flag) | **Complete** |

**Verification**: Given JD → auto-select bullets → generate resume + CL + answer questions
**Code Review**: Codex review — 1 P1 (auth template removed), 1 P2 (experience calc fixed). See CHANGELOG.

### Phase 4: Browser Automation + Form Filling (Weeks 7-8)

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 4.1 | Application state machine + Playwright browser manager | **Complete** |
| 4.2 | Form field detection, mapping, filling + file upload | **Complete** |
| 4.3 | ATS adapters (Greenhouse, Lever) with scoped detection | **Complete** |
| 4.4 | Rate limiter with concurrency safety | **Complete** |

**Verification**: Greenhouse job → auto-fill form → upload files → screenshot (no submit)
**Code Review**: Codex review — 3 P1, 7 P2, 2 P3 found and fixed. See CHANGELOG.

### Phase 5: CLI + Tracking + Full Pipeline (Weeks 9-10)

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 5.1 | CLI framework (Click command group) + `autoapply init` wizard | **Complete** |
| 5.2 | Application tracking: CRUD, state sync, outcome updates | **Complete** |
| 5.3 | Analytics + apply/status CLI commands | **Complete** |

**Verification**: `autoapply init` -> `autoapply search` -> `autoapply apply` -> `autoapply status`
**Code Review**: Codex review -- 3 P1, 6 P2, 2 P3 found and fixed. See CHANGELOG.

### Phase 6: LinkedIn Integration (Weeks 11-12)

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 6.1 | LinkedIn authenticated session manager (Playwright, cookie persistence, login detection) | **Complete** |
| 6.2 | LinkedIn job search scraper (search URL builder, pagination, result extraction) | **Complete** |
| 6.3 | Job detail extraction + ATS redirect detection (LinkedIn -> Greenhouse/Lever URL mapping) | **Complete** |
| 6.4 | Integration with existing pipeline (CLI `autoapply search --source linkedin`, filters, storage) | **Complete** |
| 6.5 | Tests + code review | **Complete** |

**Verification**: `autoapply search --source linkedin --keyword "software engineer intern"` -> extract jobs -> detect ATS links -> feed into existing apply pipeline

### Phase 7: Web GUI (Weeks 13-15)

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 7.1 | Separate Vue frontend workspace + Vite build + FastAPI SPA shell | **Complete** |
| 7.2 | Minimal dashboard, jobs, applications, profile, and settings pages | **Complete** |
| 7.3 | JSON API routes for search, tracking, profile, and settings | **Complete** |
| 7.4 | Remove legacy Jinja2/HTMX layer and simplify repository structure | **Complete** |
| 7.5 | Tests + Codex review | **Complete** |

**Verification**: `autoapply web` -> browser opens dashboard -> search jobs -> trigger apply -> view status

### Phase 8: Materials Workspace + Template Packages + Hardening

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 8.1 | Dedicated `/materials` Vue workspace for job/JD, applicant, template, format, preview, and downloads | **Complete** |
| 8.2 | DOCX-first template packages with manifests, style locks, upload, validation, and deterministic rendering | **Complete** |
| 8.3 | Resume/Cover Letter IR, evidence retrieval, template fitting, artifact validation, page counting, version persistence | **Complete** |
| 8.4 | API hardening: template ID validation, artifact path restrictions, upload limits, profile ID validation | **Complete** |
| 8.5 | LinkedIn/cache/parser hardening from Claude Code review | **Complete** |

**Verification**: `/jobs` -> `Generate Apply Materials` -> `/materials?jobId=...` -> generate DOCX/PDF -> preview/download. Full test baseline: 340 passed, 1 skipped.

### Phase 9: UI Overhaul (Tailwind + shadcn-vue)

Front-end-only refresh of the Vue SPA. No backend changes.

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| A | Generate the AutoApply design system spec via the `ui-ux-pro-max` agent | **Complete** |
| B-1..B-3 | Install Tailwind v3 + `tailwindcss-animate`, ship HSL design tokens (light + dark), add shadcn-style base components (`Button`, `Input`, `Card`, `Badge`, `Dialog`, `Skeleton`, `EmptyState`, `Label`) | **Complete** |
| C-1..C-3 | Rebase `styles.css` onto HSL tokens; tighten core controls (button / input / chip / banner / page header) and layout (workspace 1400px, denser tables, hoverable rows) | **Complete** |
| C-4..C-9 | Rebuild every view shell with shadcn `Card` + Lucide icons (Dashboard, Applications, Settings, Materials, Profile, Jobs); empty states use the shared `EmptyState`, primary actions use shadcn `Button`, numeric columns use `tabular-nums` | **Complete** |
| D-1 | Migrate every `.banner is-*` div to shadcn `Alert` (destructive / success / warning / default) with Lucide icons | **Complete** |
| D-2..D-3 | Migrate JobsView "Apply Materials" modal and MaterialsView Template Library modal to reka-ui `Dialog` (portal, overlay, scroll-lock, focus-trap, built-in close) | **Complete** |
| D-4 | Rebuild `AppSelect.vue` on top of reka-ui `Select` (portal, scroll buttons, animated open/close); preserve the `{ value, label }` API including empty-string sentinels | **Complete** |
| D-5 | Rebuild `TagInput.vue` with shadcn-style chip pills + flush inline `Input`; preserve keyboard / paste / commit-on-blur behavior | **Complete** |
| D-6 | Replace `AppIcon.vue` and `DockIcon.vue` (hand-rolled SVG dictionaries) with direct lucide-vue-next components everywhere; delete both files; toggle the Tailwind `.dark` class on `<html>` | **Complete** |
| D-7..D-8 | Migrate ProfileView / JobsView / PaginationBar accordion + pagination icon-buttons to shadcn `Button`; add `aria-expanded` to every accordion-head / editor-item-head | **Complete** |
| D-9 | Prune dead CSS for the migrated banner / modal patterns (CSS bundle 53 kB → 52 kB) | **Complete** |
| D-10 | Documentation sync (CHANGELOG / PROJECT_MANAGEMENT / DECISIONS) | **Complete** |

**Verification**: `npm run build` succeeds at every sub-phase; `codex review` reports no actionable regressions; manual smoke covers Dashboard / Jobs / Applications / Materials / Profile / Settings in both light and dark themes.

### Agent Phase 8: Agent Harness Foundations

Foundational layer for running confined LLM-driven loops inside AutoApply. Independent of the UI Overhaul Phase 9 above (different concern, separate numbering).

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 8.1 | Tool abstraction layer (Tool ABC, ToolRegistry allow-lists, builtin `fs_read` / `text_stats` / `finish`) | **Complete** |
| 8.2 | Bounded ReAct agent loop with manual JSON protocol (works on `claude` and `codex` CLIs) | **Complete** |
| 8.3 | JSON-on-disk trace store + FastAPI viewer at `/api/agent/viewer` | **Complete** |
| 8.4 | Fixture-driven eval harness; `autoapply eval` CLI with suites, scorers, `--min-pass-rate` | **Complete** |
| 8.5 | HITL approval gate (file-backed queue, viewer UI, `propose` / `approve` / `reject`) | **Complete** |

**Verification**: `autoapply eval --suite agent_smoke` -> all cases pass.

### Agent Phase 9: Form-Filler Agent

First business node converted to agent mode. The deterministic `form_filler.py` is still the default; the agent path is opt-in via `AgentFormFiller` / `run_agent_form_fill(...)`.

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 9.1 | Browser tool layer: `browser_inspect_page`, `browser_find_field`, `browser_propose_fill`, `browser_screenshot`. Sync, side-effect-free; agent never holds a Playwright handle. Stdlib HTML snapshot builder + async builder for live pages. | **Complete** |
| 9.2 | `AgentFormFiller` orchestrator: snapshot → agent loop → proposal review → HITL gate → deterministic fill. `submit()` raises `PermissionError` unless gate approves. `profile_lookup` tool replaces prompt-pasted PII. Falls back to rules on agent failure. | **Complete** |
| 9.3 | `form_filler` eval suite: 5 fixtures (basic / Workday / Greenhouse / Lever w/ recovery / Ashby long select), `field_mapping_match` and `no_proposal_for_label` scorers, baseline JSON, CLI gate at `--min-pass-rate 0.85`. | **Complete** |
| 9.4 | Cost / latency telemetry: `prompt_tokens` / `output_tokens` / `cost_usd` per AgentStep, aggregated into AgentResult, TraceRecord, EvalReport. Surfaces in CLI eval output, web trace viewer, persisted JSON. Rates configurable via env. | **Complete** |
| 9.5 | Docs: new `AGENT_ARCHITECTURE.md`, README updates, CHANGELOG entries for Agent Phase 8 + 9. | **Complete** |

**Verification**: 553 passed, 1 skipped. `ruff check` clean. `autoapply eval --suite form_filler --min-pass-rate 0.85` exits 0 with 5/5 passing at ~$0.23 estimated cost under default rates.

### Phase 10: LLM Provider Abstraction (was originally planned as "cover-letter agent" -- pivoted)

Multi-provider LLM layer so AutoApply is no longer locked to the
Claude CLI + Codex CLI subprocess pair. Adds REST adapters for the
big three API providers and treats the CLI tools as just another
provider kind.

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 10.1 | Provider abstraction (`LLMProvider` ABC, `ProviderKind`, `ProviderTestResult`) + secure credential store (file-backed, OS keyring fallback) | **Complete** |
| 10.2 | OpenAI / Anthropic / Gemini REST adapters using `httpx`. Per-provider error normalization, model listing, `test_connection` deep probe. | **Complete** |
| 10.3 | (Originally Codex OAuth wrapper -- rewritten in 10.7 as `CodexCliProvider`, a subprocess provider mirroring Claude CLI.) | **Superseded** |
| 10.4 | `ClaudeCliProvider` subprocess provider (`auth_type=SUBPROCESS`) -- `codex login`/`claude login` own their own auth; AutoApply stores nothing. | **Complete** |
| 10.5 | Wire `ProviderRegistry` into `src.utils.llm.generate_text` -- old call sites unchanged, dispatch picks the configured primary provider. | **Complete** |
| 10.6 | `autoapply provider` CLI subcommands: `list`, `set-key`, `test`, `set-primary`, `set-fallback`, `disconnect`. | **Complete** |
| 10.7 | Settings page UI for provider management: connect / disconnect / test / set-primary / set-fallback. Distinguishes subprocess vs API-key providers. `test_connection` for subprocess providers runs `codex login status` so installed-but-unauthenticated is reported correctly. | **Complete** |

**Verification**: 669 passed, 1 skipped. `ruff check` clean. Frontend rebuilt and committed. PR #12 open against `master`.

## Current Session Context

- **Active branch**: `feat/llm-providers`
- **Current phase**: Phase 10 complete; PR #12 open for review
- **Last verification**: 669 passed, 1 skipped; `ruff check` clean; frontend builds; manual smoke OK on Settings page in light + dark
- **Blockers**: None
- **Next step**: Land PR #12, then start Phase 11 (Reliability & Cleanup).

## Roadmap: Phase 11 -- 16

Re-planned 2026-05-12 after Phase 10 pivot. Original architecture
doc had "cover-letter agent" as Phase 10 and "matching agent" as
Phase 11; those slid down a number once Phase 10 became the LLM
provider abstraction. Two new cross-cutting concerns -- caching and
scheduled tasks -- are promoted to their own phases because they
each unblock multiple downstream phases.

### Phase 11: Reliability & Cleanup (~1 week)

Tighten the provider layer Phase 10 introduced; ship the migration
tool needed for users upgrading from earlier revisions.

| Sub | Scope |
|-----|-------|
| 11.1 | Provider fallback chain: `generate_text()` accepts primary + ordered fallbacks; quota / network / auth failures fail over automatically; attempt chain recorded in trace. The Settings UI fallback field finally takes effect. |
| 11.2 | `autoapply migrate` CLI command: cleans stale `managed_by: codex-cli` credential breadcrumbs, renames legacy settings.yaml keys, detects and prompts about stale credentials. Run once per upgrade. |
| 11.3 | Docs sync: bring PROJECT_MANAGEMENT.md / AGENT_ARCHITECTURE.md / CHANGELOG.md up to Phase 10 complete state; add the Phase 11-16 plan inline. |
| 11.4 | Provider health monitor: `/api/providers/health` background probe every 5 min; Settings page "Last verified" line shows real telemetry instead of "just now". |

**Verification**: revoke OpenAI key mid-run → fallback chain kicks in → eval still passes; `autoapply migrate` against a fixture environment with legacy breadcrumbs leaves state clean.

### Phase 12: Caching Foundation + Integration (~1.5 weeks)

Build a general-purpose cache layer and wire it through the
expensive call sites (LLM, JD scraping, embeddings).

| Sub | Scope |
|-----|-------|
| 12.1 | `src/cache/` module: tiered cache (L1 in-memory LRU + L2 SQLite-backed), per-namespace TTL (`llm:7d`, `jd:24h`, `embedding:30d`, `linkedin:6h`), explicit invalidation API, version-stamped keys. |
| 12.2 | JD / scrape caching: Greenhouse / Lever / LinkedIn scrapers consult cache before HTTP; 24h TTL; ETag / Last-Modified aware. |
| 12.3 | LLM response caching: `generate_text()` accepts `cache=True` and computes `cache_key=hash(provider+model+prompt+system+temperature)`; agent loops default to `cache=False`, deterministic retrieval steps default to `cache=True`. |
| 12.4 | Cache inspector UI at `/settings/cache`: per-namespace entry count / size / hit-rate / $ saved; one-click clear. |
| 12.5 | Cost dashboard upgrade: split Phase 9.4 aggregates into "cached vs fresh" with a $-saved line. |

**Verification**: same job batch run twice -- second run's LLM cache hit-rate > 80%, wall time < 20% of first run, total cost < 5% of first run.

### Phase 13: Scheduled Task System (~1.5 weeks)

Production-grade scheduler. Lays the foundation Phase 16 needs to
run nightly batches without the user being at the keyboard.

| Sub | Scope |
|-----|-------|
| 13.1 | Engine: APScheduler + SQLite jobstore (not Celery -- single-user app doesn't need a broker; not OS cron -- needs persistent state and live management). Integrated into FastAPI lifespan; auto-resume on process start. |
| 13.2 | Built-in jobs: `daily_search`, `jd_health_check`, `application_status_sync`, `linkedin_cookie_refresh`, `cache_eviction`. Each is a plain function registered with a cron expression. |
| 13.3 | CLI: `autoapply schedule list / add / remove / pause / run-now / logs`. `add` accepts `--cron "0 9 * * *"` or `--every 2h`. |
| 13.4 | Web UI at `/schedule`: table of jobs (cron / last-run / next-run / status), manual trigger, pause/resume, history viewer. |
| 13.5 | Trace integration: each scheduled run emits a trace record (reuses Phase 8.3 store); failures carry stacktrace; viewable in the existing trace viewer. |
| 13.6 | (Optional) Notification hook on N consecutive failures: desktop notification only -- no email/Slack yet. |

**Verification**: register `daily_search` with `* * * * *`, wait 1 minute, new trace appears; restart the process, jobstore is restored and the next tick fires.

**Constraint**: single-instance only. APScheduler with the SQLite jobstore is not safe across multiple `autoapply web` processes; document this and add a startup check.

### Phase 14: Cover-letter Agent (~2 weeks)

The original "Phase 10" plan, now done third. Benefits from Phase
12 caching to keep cost predictable.

| Sub | Scope |
|-----|-------|
| 14.1 | New tools: `jd_lookup` (read JD by section, replaces pasting whole JD into the prompt). Reuses `profile_lookup`. Read-only. |
| 14.2 | `AgentCoverLetter` orchestrator: agent emits cover-letter IR (structured paragraphs with evidence citations) → existing fact-drift checker in `src/generation/` as post-guard → fallback to deterministic path on failure. |
| 14.3 | Eval suite: 5 fixtures (varied roles / company styles); scorers `fact_drift_score`, `keyword_coverage`, `length_compliance`. |
| 14.4 | HITL gate: letter generation itself does not block; gate fires only when the agent tries to mutate bullet pool / story bank (writing newly-discovered stories back to memory). |
| 14.5 | Cache integration: JD retrieval results use 12.3; profile lookups use 12.1 in-memory LRU. |

**Verification**: 5/5 eval pass; per-letter cost ≤ $0.08 on cache-miss, ≤ $0.02 on cache-hit; quality matches or beats deterministic baseline (human judgement).

### Phase 15: Filter Agent + Explainability Layer (~1.5 weeks)

Not a replacement for the deterministic filter -- an explainability
layer on top, plus agent invocation for borderline jobs only.

| Sub | Scope |
|-----|-------|
| 15.1 | Filter reason chain: every reject in `src/matching/` records `{rule_id, rule_name, reason, evidence_excerpt}` instead of just a score. |
| 15.2 | Edge-case agent: invoked only for jobs with score ∈ [0.4, 0.6]; explains why borderline and whether to surface for human review. Uses Phase 8 harness + new `score_breakdown` tool. |
| 15.3 | Web UI "Why was this filtered?": ⓘ button on every rejected job in JobsView; popover shows rule-based reasons and agent commentary if present. |
| 15.4 | Eval suite: 10 human-annotated borderline jobs; agent decision matches human ≥ 70%. |

**Verification**: any rejected job's reason can be surfaced in < 5 seconds from the UI; agent cost stays < $0.50 per 100 jobs (agent fires on ~10%).

### Phase 16: Daily Run Loop + Review Queue (~2 weeks)

Integration phase. Threads Phase 13 (scheduler) + Phase 12 (cache)
+ Phase 9/14 (agents) into the "sleep, wake up to a review queue"
end-to-end flow.

| Sub | Scope |
|-----|-------|
| 16.1 | `nightly_run` orchestrator (registered with Phase 13): search → filter (with 15's explainability) → take top-N → run form-filler agent (Phase 9) + cover-letter agent (Phase 14) → enqueue into review queue. **Never auto-submits.** |
| 16.2 | Review queue model: new table `review_queue(id, job_id, materials_path, status, created_at, reviewed_at, decision, reason)`; state machine `pending → approved → submitted` or `pending → rejected`. |
| 16.3 | Review UI at `/review`: kanban with `[Pending] [Approved] [Submitted] [Rejected]` columns; each card has job summary + materials preview + one-click approve/reject. |
| 16.4 | Bulk operations: multi-select approve, bulk-reject by company/keyword, approve-and-submit (still gated by Phase 4/9 HITL final gate). |
| 16.5 | Daily digest at 08:00: desktop notification + dashboard banner -- "Last night: 12 new jobs, 7 passed filter, 3 in review queue, est. cost $0.21". |
| 16.6 | Kill switch: `autoapply pause-nightly` -- pauses all schedules and clears the pending queue (for vacation). |

**Verification**: schedule a nightly run at 23:00 Monday → wake Tuesday 08:00 → N pre-tailored applications in the review queue, each approvable in < 30s, submit triggers HITL gate as expected; no manual CLI invocation needed between Mon evening and Tue morning.

## Cross-cutting Concerns

These are not phases but quality bars enforced across all of 11-16:

- **Test discipline**: every new module ships with tests; no new code can drop the suite below the current 669 passing.
- **Lint discipline**: `ruff check src/ tests/` must stay clean.
- **Codex review per sub-phase**: each sub-phase gets a `codex review --uncommitted` pass before commit; P1 findings block merge.
- **Cost ceiling**: any eval suite that pushes total cost above $1.00 / 100 cases needs explicit justification.
- **Docs sync**: PROJECT_MANAGEMENT.md and CHANGELOG.md updated at the end of every Phase, not in a batch later.
