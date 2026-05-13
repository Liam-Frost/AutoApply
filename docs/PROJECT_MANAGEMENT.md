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

**Verification**: 669 passed, 1 skipped at Phase 10 close. `ruff check` clean. Frontend rebuilt and committed. PR #12 merged into `dev` (commit `9cbb354`).

## Current Session Context

- **Active branch**: `feat/phase-11`
- **Current phase**: Phase 11 in progress -- 11.1 + 11.2 + 11.3 landed, 11.4 pending
- **Last verification**: 718 passed, 1 skipped on `feat/phase-11` after 11.2; `ruff check` clean; frontend untouched in this phase
- **Blockers**: None
- **Next step**: 11.4 Provider health monitor → end-of-phase codex review → docs sweep → PR to `dev`.

## Roadmap: Phase 11 -- 18

Re-planned **2026-05-12 (v2)** after re-evaluating two inputs: (a) the
project actually runs on PostgreSQL + pgvector (not SQLite, which the
prior draft mistakenly assumed in 12.1 / 13.1); (b) a commercial path
is being preserved, so Redis is adopted as the L1 cache / distributed
lock / task queue substrate from Phase 12 onward, and a new Phase 18
plants the multi-tenancy seeds that would otherwise force a painful
schema migration later.

The earlier "JD scrape caching" sub-phase has been promoted to a
full phase (**Phase 13: Job Index & Freshness Engine**) because the
problem is not a key-value cache -- it is content versioning,
freshness state machines, and audit binding between a generated
material and the JD snapshot it was built from.

### Phase 11: Reliability & Cleanup (~1 week)

Tighten the provider layer Phase 10 introduced; ship the migration
tool needed for users upgrading from earlier revisions.

| Sub | Scope | Status |
|-----|-------|--------|
| 11.1 | Provider fallback chain: `generate_text()` accepts primary + ordered fallbacks; quota / network / auth failures fail over automatically; attempt chain recorded in trace. The Settings UI fallback field finally takes effect. | **Complete** (commit `a60e846`) |
| 11.2 | `autoapply migrate` CLI command: cleans stale `managed_by: codex-cli` credential breadcrumbs, renames legacy settings.yaml keys, detects and prompts about stale credentials. Run once per upgrade. | **Complete** (commit `c45a2f6`) |
| 11.3 | Docs sync: bring PROJECT_MANAGEMENT.md / AGENT_ARCHITECTURE.md / CHANGELOG.md up to Phase 10 complete state; add the Phase 11-18 plan inline. | **Complete** |
| 11.4 | Provider health monitor: `/api/providers/health` background probe every 5 min; Settings page "Last verified" line shows real telemetry instead of "just now". | Pending |

**Verification**: revoke OpenAI key mid-run → fallback chain kicks in → eval still passes; `autoapply migrate` against a fixture environment with legacy breadcrumbs leaves state clean.

### Phase 12: Cache Infrastructure (~1.5 weeks)

First introduction of Redis. Builds the generic cache + lock + queue
substrate that Phases 13, 14, 17, and 18 will all consume. Scope is
deliberately narrow: **LLM and embedding responses only**. JD / job
content caching moves to Phase 13 because it needs content
versioning, not TTL eviction.

| Sub | Scope |
|-----|-------|
| 12.1 | `src/cache/` module: L1 in-process LRU + L2 **Redis**. Namespace TTL (`llm:7d`, `embedding:30d`, `response:5m`). Unified `get/set/invalidate(namespace, key)` API. Version-stamped keys for safe rolling deploys. |
| 12.2 | **Redis infrastructure**: connection pool, health check, `REDIS_URL` env var, `docker-compose.yml` service, AOF persistence on, `autoapply redis ping/flush/info` CLI. Single-node Redis is fine through Phase 17; Sentinel/Cluster is a Phase 18+ concern. |
| 12.3 | **Distributed lock primitive**: `with cache.lock(key, ttl=10min, blocking=False)` built on Redis `SET NX PX`. Phase 13 force-refresh will use it. |
| 12.4 | LLM response caching: `generate_text(cache=True)` -- key=`hash(provider+model+prompt+system+temperature)`; agent loops default `cache=False`, deterministic retrieval defaults `cache=True`. Cost-saved counter increments on hit. |
| 12.5 | Embedding cache: `embed_text(cache=True)` for `src/matching/semantic.py` with 30-day TTL. |
| 12.6 | Cache inspector UI at `/settings/cache`: per-namespace entry count / size / hit-rate / $ saved; one-click clear (with confirm). |
| 12.7 | Cost dashboard upgrade: split Phase 9.4 aggregates into "cached vs fresh" with a $-saved line. |

**Verification**: same job batch run twice -- second run's LLM cache hit-rate > 80%, wall time < 20% of first run, total cost < 5% of first run. Redis restart preserves L2 entries (AOF replay). Lock acquired in process A blocks process B on the same key.

### Phase 13: Job Index & Freshness Engine (~2 weeks)

Replaces the file-backed `src/intake/search_cache.py` with a proper
**Job Intelligence Database**: typed entities, content-hashed
snapshots, search-query cache, freshness state machine, and audit
binding from generated materials back to the exact JD snapshot they
were produced from. This is the foundation Phase 14 / 15 / 17 all
build on -- it makes "what JD did we apply against?" answerable
forever.

| Sub | Scope |
|-----|-------|
| 13.1 | **Schema** (alembic): `job_postings` (entity), `job_snapshots` (content version), `search_queries` (normalized search condition), `search_results` (search → posting many-to-many), `refresh_tasks` (priority queue). Add `application_records.job_snapshot_id` FK. **Every new table carries `tenant_id` (default `"default"` until Phase 18).** |
| 13.2 | Normalization layer: `normalize_search_key()` (strips `currentJobId` / `origin` / tracking params; keeps `keywords` / `geoId` / filters / `sortBy`); `normalize_job_content()`; `content_hash()` excluding unstable fields (`applicant_count`, `promoted`, dynamic timestamps). |
| 13.3 | Freshness state machine in `src/jobs/state.py`: `new → active → stale → unknown → expired → archived` with the documented transition rules. Centralized so callers cannot drift. |
| 13.4 | Search flow: cache-first by default (`SearchQuery.status=fresh` → return without HTTP); force-refresh path wraps the scrape in a Phase 12 distributed lock to prevent concurrent duplicate fetches; old cache preserved on failure. |
| 13.5 | Detail enrichment with content versioning: scrape → normalize → hash → if `content_hash != latest_snapshot.content_hash` create new `job_snapshot`; emit `job.content_changed` event. Existing snapshots are immutable. |
| 13.6 | Context-aware freshness: `should_refresh(job, context)` where context ∈ {`search_display: 72h`, `generate_materials: 24h`, `before_submit: 6h`}. Replaces ad-hoc TTL checks. |
| 13.7 | Web UI: search page shows `Last updated 18h ago · [Refresh]`; refresh in progress shows cached + spinner; success banner reports `3 new · 2 expired · 5 updated`. |
| 13.8 | Migration: import legacy `data/cache/linkedin_search/*.json` into `search_queries` + `search_results`; remove the file-cache module. |

**Verification**: second visit to same search condition returns < 2s without HTTP; job content edit on LinkedIn produces a new snapshot row on next enrich (old snapshot retained); revoke LinkedIn cookie → cached results still served with `refreshFailed=true` flag. `tenant_id="default"` on every new row.

### Phase 14: Scheduled Task System (~1.5 weeks)

Production-grade scheduler. Lays the foundation Phase 17 needs to
run nightly batches without the user being at the keyboard.

| Sub | Scope |
|-----|-------|
| 14.1 | Engine: APScheduler + **Postgres SQLAlchemyJobStore** (corrects the earlier SQLite draft -- the app already runs on Postgres). Integrated into FastAPI lifespan; auto-resume on process start. |
| 14.2 | **RefreshTask worker**: consumes Phase 13 `refresh_tasks` rows. Priority levels `critical / high / normal / low`. Per-source concurrency limits (LinkedIn search: 1, LinkedIn detail: 3, ATS scrape: 5). |
| 14.3 | Built-in jobs: `daily_search`, `jd_health_check` (drives the Phase 13 state machine forward), `application_status_sync`, `linkedin_cookie_refresh`, `cache_eviction`. Each is a plain function with a cron expression. |
| 14.4 | CLI: `autoapply schedule list / add / remove / pause / run-now / logs`. `add` accepts `--cron "0 9 * * *"` or `--every 2h`. |
| 14.5 | Web UI at `/schedule`: table of jobs (cron / last-run / next-run / status), manual trigger, pause/resume, history viewer. |
| 14.6 | **Multi-instance safety**: APScheduler row-lock via Postgres advisory lock -- two `autoapply web` processes do not double-fire the same job. Foundation for horizontal scaling in the commercial path. |
| 14.7 | Trace integration: each scheduled run emits a trace record (reuses Phase 8.3 store); failures carry stacktrace; viewable in the existing trace viewer. |

**Verification**: register `daily_search` with `* * * * *`, wait 1 minute, new trace appears; restart the process, jobstore is restored and the next tick fires; start two web processes -- the every-minute job fires once per minute, not twice.

### Phase 15: Cover-letter Agent (~2 weeks)

The original "Phase 10" plan. Benefits from Phase 12 (LLM caching)
and Phase 13 (snapshot binding -- the agent always works against a
fresh, immutable JD version).

| Sub | Scope |
|-----|-------|
| 15.1 | New tool `jd_lookup`: reads JD by section from a specific `job_snapshot_id`. Read-only. Reuses `profile_lookup`. |
| 15.2 | `AgentCoverLetter` orchestrator: agent emits cover-letter IR (structured paragraphs with evidence citations) → existing fact-drift checker as post-guard → fallback to deterministic path on failure. |
| 15.3 | Pre-generation freshness gate: if `should_refresh(job, "generate_materials")` is true, trigger an enrich task first; if it fails, prompt the user before continuing with stale JD. |
| 15.4 | Bind the produced `CoverLetterVersion.job_snapshot_id` -- the audit trail is "this letter was written against snapshot X of job Y at time T". |
| 15.5 | Eval suite: 5 fixtures (varied roles / company styles); scorers `fact_drift_score`, `keyword_coverage`, `length_compliance`. |
| 15.6 | HITL gate: letter generation itself does not block; gate fires only when the agent tries to mutate bullet pool / story bank. |

**Verification**: 5/5 eval pass; per-letter cost ≤ $0.08 on cache-miss, ≤ $0.02 on cache-hit (Phase 12 LLM cache); re-generating the same job + profile within TTL is served from cache.

### Phase 16: Filter Agent + Explainability Layer (~1.5 weeks)

Not a replacement for the deterministic filter -- an explainability
layer on top, plus agent invocation for borderline jobs only.

| Sub | Scope |
|-----|-------|
| 16.1 | Filter reason chain: every reject in `src/matching/` records `{rule_id, rule_name, reason, evidence_excerpt, job_snapshot_id}` instead of just a score. |
| 16.2 | Edge-case agent: invoked only for jobs with score ∈ [0.4, 0.6]; explains why borderline and whether to surface for human review. Uses Phase 8 harness + new `score_breakdown` tool. |
| 16.3 | Web UI "Why was this filtered?": ⓘ button on every rejected job; popover shows rule-based reasons + agent commentary if present + which snapshot the decision was made on. |
| 16.4 | Eval suite: 10 human-annotated borderline jobs; agent decision matches human ≥ 70%. |

**Verification**: any rejected job's reason can be surfaced in < 5 seconds from the UI; agent cost stays < $0.50 per 100 jobs (agent fires on ~10%).

### Phase 17: Daily Run Loop + Review Queue (~2 weeks)

Integration phase. Threads Phase 14 (scheduler) + Phase 13 (job
index + freshness) + Phase 12 (cache) + Phase 9 / 15 (agents) into
the "sleep, wake up to a review queue" end-to-end flow.

| Sub | Scope |
|-----|-------|
| 17.1 | `nightly_run` orchestrator (registered with Phase 14): search (cache-first, refresh stale) → filter (with 16's explainability) → take top-N → run form-filler agent (Phase 9) + cover-letter agent (Phase 15) → enqueue into review queue. **Never auto-submits.** |
| 17.2 | Review queue model: new table `review_queue(id, tenant_id, job_id, job_snapshot_id, materials_path, status, created_at, reviewed_at, decision, reason)`; state machine `pending → approved → submitted` or `pending → rejected`. |
| 17.3 | Review UI at `/review`: kanban with `[Pending] [Approved] [Submitted] [Rejected]` columns; each card has job summary + materials preview + one-click approve/reject. |
| 17.4 | Bulk operations: multi-select approve, bulk-reject by company/keyword, approve-and-submit (still gated by Phase 4 / 9 HITL final gate). |
| 17.5 | **Pre-submit hard gate**: every approve-and-submit re-runs `should_refresh(job, "before_submit")`; if the snapshot is now expired or > 6h stale, refresh first; if the job is `expired` block submission entirely. |
| 17.6 | Daily digest at 08:00: desktop notification + dashboard banner -- "Last night: 12 new jobs, 7 passed filter, 3 in review queue, est. cost $0.21". |
| 17.7 | Kill switch: `autoapply pause-nightly` -- pauses all schedules and clears the pending queue (for vacation). |

**Verification**: schedule a nightly run at 23:00 Monday → wake Tuesday 08:00 → N pre-tailored applications in the review queue, each approvable in < 30s, submit triggers HITL gate as expected; expired-job pre-submit gate blocks correctly; no manual CLI invocation needed between Mon evening and Tue morning.

### Phase 18: Multi-Tenancy & Auth Hardening (~2 weeks)

Activates the commercial-readiness work seeded across Phases 12-17.
SaaS business layer (billing, sign-up flow, marketing site) is NOT
in scope -- this phase only makes the existing system safe to host
for multiple isolated users.

| Sub | Scope |
|-----|-------|
| 18.1 | `tenants` + `users` tables; migration of existing data to `tenant_id="default"` (the value all Phase 12-17 tables already carry). |
| 18.2 | FastAPI auth middleware: derive `current_tenant_id` from session / token; every query layer (SQLAlchemy session, Redis namespace, cache key prefix, refresh-task selector) automatically filters by it. |
| 18.3 | Postgres Row-Level Security policies as DB-level backstop -- even a query that forgets the `tenant_id` filter cannot leak rows. |
| 18.4 | Per-tenant Redis namespace: `tenant:{id}:llm:...`, `tenant:{id}:lock:...`. Inspector UI shows current tenant only. |
| 18.5 | Per-tenant quotas: LLM token budget / scrape rate / storage. Exceeding returns 429 with a structured retry-after. |
| 18.6 | Audit log table (`audit_events`): submission, settings change, credential operation, manual schedule trigger. Append-only. |
| 18.7 | Credential store per-tenant: keyring entries namespaced; file-backed entries moved under `data/tenants/{id}/credentials/`. |

**Verification**: two tenants seeded with overlapping email / LinkedIn cookies → tenant A's session cannot read tenant B's jobs / snapshots / applications / credentials / Redis keys, verified by direct SQL and direct Redis CLI; quota exhaustion returns 429; RLS policy in place even if the ORM layer is bypassed.

### Timeline summary

| Phase | Scope | Est. | Cumulative |
|-------|-------|------|------------|
| 11 | Reliability & Cleanup | 1w | 1w |
| 12 | Cache Infrastructure (Redis) | 1.5w | 2.5w |
| 13 | Job Index & Freshness Engine | 2w | 4.5w |
| 14 | Scheduled Task System | 1.5w | 6w |
| 15 | Cover-letter Agent | 2w | 8w |
| 16 | Filter Agent + Explainability | 1.5w | 9.5w |
| 17 | Daily Run Loop + Review Queue | 2w | 11.5w |
| 18 | Multi-Tenancy & Auth Hardening | 2w | 13.5w |

~3 months to v1.0 commercial-ready core (no SaaS business layer).

## Cross-cutting Concerns

These are not phases but quality bars enforced across all of 11-18:

- **Test discipline**: every new module ships with tests; no new code can drop the suite below the current 680 passing (1 skipped LinkedIn smoke).
- **Lint discipline**: `ruff check src/ tests/` must stay clean.
- **Codex review per sub-phase**: each sub-phase gets a `codex review --uncommitted` pass before commit; P1 findings block merge.
- **Cost ceiling**: any eval suite that pushes total cost above $1.00 / 100 cases needs explicit justification.
- **Docs sync**: PROJECT_MANAGEMENT.md and CHANGELOG.md updated at the end of every Phase, not in a batch later.
- **Multi-tenancy hygiene** (Phase 12+): every new table carries `tenant_id`; every new Redis key is prefixed; every new background task accepts a tenant context. No exceptions -- otherwise Phase 18 turns into a rewrite.
