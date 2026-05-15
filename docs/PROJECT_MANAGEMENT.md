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
| `data/templates/` | Document template packages (DOCX today; LaTeX manifest packages planned in Phase 15) |

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

- **Active branch**: `feat/phase-16` (PR pending)
- **Current phase**: Phase 16 implementation complete -- 16.1 through 16.4 all landed + one round of codex-review P2 fix folded in (removed committed runtime trace artifacts; `data/agent_traces/` is now gitignored).
- **Last verification**: 1398 passed, 1 skipped on `feat/phase-16`; `ruff check` clean; frontend build clean (vite 6.00s, 126kB gzip JS). `codex review` second pass not yet re-run after the trace-cleanup commit.
- **Blockers**: None
- **Next step**: Open PR `feat/phase-16 -> dev`, then start **Phase 17 (Daily Run Loop + Review Queue)** on a fresh `feat/phase-17` branch. The first sub-phase (17.1) is the `nightly_run` orchestrator -- threads Phase 14 (task queue) + Phase 13 (job index) + Phase 12 (cache) + Phases 9/15/16 (agents) into the "sleep, wake to a review queue" end-to-end flow. **Never auto-submits.**

## Roadmap: Phase 11 -- 18

Re-planned **2026-05-14 (v3)** after re-evaluating four inputs: (a) the
project actually runs on PostgreSQL + pgvector (not SQLite, which the
prior draft mistakenly assumed in 12.1 / 13.1); (b) a commercial path
is being preserved, so Redis is adopted as the L1 cache / distributed
lock / task queue substrate from Phase 12 onward, and a new Phase 18
plants the multi-tenancy seeds that would otherwise force a painful
schema migration later; (c) fully automated application runs need a
real task queue + worker boundary rather than synchronous web / CLI
calls; (d) the materials system needs separate paths for patching a
user's original resume and for LaTeX-first generation.

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
| 11.3 | Docs sync: bring PROJECT_MANAGEMENT.md / AGENT_ARCHITECTURE.md / CHANGELOG.md up to Phase 10 complete state; add the Phase 11-18 plan inline. | **Complete** (commit `47dbfba`) |
| 11.4 | Provider health monitor: `/api/providers/health` background probe every 5 min; Settings page "Last verified" line shows real telemetry instead of "just now". | **Complete** (commit `f8ea3dd`) |
| 11.5 | Writer sync for list+scalar fallback shapes: `update_llm_settings`, `use_provider_as_primary`, `disconnect_provider`, `use_cmd`, and `autoapply migrate` all keep `fallback_providers` (list, authoritative) and `fallback_provider` (legacy scalar) in agreement. Added across four codex review rounds — preserves `allow_fallback: false` through disconnect cleanup, handles the comma-string chain shape, prunes without re-promoting stale scalars, and promotes the orphan `llm.provider` key for pre-Phase-10 configs. | **Complete** (commit `a8f8c59`) |

**Verification**: revoke OpenAI key mid-run → fallback chain kicks in → eval still passes; `autoapply migrate` against a fixture environment with legacy breadcrumbs leaves state clean; `/api/providers/health` snapshot reflects live `test_connection` results; codex review of 11.5 returned no findings after round 4.

### Phase 12: Cache Infrastructure (~1.5 weeks)

First introduction of Redis. Builds the generic cache + lock + queue
substrate that Phases 13, 14, 17, and 18 will all consume. Scope is
deliberately narrow: **LLM and embedding responses only**. JD / job
content caching moves to Phase 13 because it needs content
versioning, not TTL eviction.

| Sub | Scope | Status |
|-----|-------|--------|
| 12.1+12.2 | `src/cache/` module (L1 LRU + L2 Redis, namespace TTL, version-stamped keys) **and** Redis infrastructure (connection pool, REDIS_URL, docker-compose w/ AOF, `autoapply redis ping/flush/info` CLI). Merged into a single sub-phase because the cache module's L2 needed real Redis end-to-end. | **Complete** (commit `f225508`) |
| 12.3 | Distributed lock primitive: `with cache.lock(key, ttl=600, blocking=False)` on Redis `SET NX PX` with WATCH/MULTI/EXEC release. Process-local `threading.Lock` fallback when L2 unavailable. | **Complete** (commit `c327f48`) |
| 12.4 | LLM response caching: `generate_text(cache=True)` -- SHA256 over `provider+model+base_url+system+prompt+output_format`; agent loops default `cache=False`, deterministic retrieval opts in. Only the primary's successful responses are cached. | **Complete** (commit `efe3b24`) |
| 12.5 | Embedding cache: `embed_text(text, cache=True)` in `src/matching/semantic.py` -- OpenAI `/v1/embeddings` via httpx, 30-day TTL, graceful degrade to keyword fallback when not configured. | **Complete** (commit `47da9d1`) |
| 12.6 | Cache inspector UI at `/settings/cache`: per-namespace counts, hit-rate, $-saved, one-click clear (confirm-gated). New `/api/cache` + `DELETE /api/cache/{namespace}` endpoints. | **Complete** (commit `52759b6`) |
| 12.7 | Cost dashboard upgrade: `AgentStep.cached`, `AgentResult.cached_step_count` / `fresh_step_count` / `total_cost_usd_fresh` / `total_cost_saved_usd`. Trace viewer shows "N fresh + M cached" plus a saved-$ pill. | **Complete** (commit `a9e4138`) |

**Verification**: cache layer ships with 230+ unit tests across `tests/test_cache_*.py`, `test_llm_cache.py`, `test_embedding_cache.py`, `test_application_cache.py`, `test_web_cache.py`, `test_agent_cost_split.py`. L1+L2 round-trip with fakeredis; transport / URL / type failures degrade gracefully; namespace glob injection rejected at the boundary; lock keys live in their own Redis prefix; cached responses never replay a fallback under the primary key; pre-Phase-12.7 traces load with the partition invariant preserved.

### Phase 13: Job Index & Freshness Engine (~2 weeks)

Replaces the file-backed `src/intake/search_cache.py` with a proper
**Job Intelligence Database**: typed entities, content-hashed
snapshots, search-query cache, freshness state machine, and audit
binding from generated materials back to the exact JD snapshot they
were produced from. This is the foundation Phase 14 / 15 / 17 all
build on -- it makes "what JD did we apply against?" answerable
forever.

| Sub | Scope | Status |
|-----|-------|--------|
| 13.1 | **Schema** (alembic `c7d3a91b4e2f`): `job_postings` (entity), `job_snapshots` (content-versioned, unique by `(posting_id, content_hash)`), `search_queries` (normalized search condition), `search_results` (query↔posting many-to-many, CASCADE), `refresh_tasks` (priority queue). `applications.job_snapshot_id` FK added for audit binding. Every new table carries `tenant_id="default"` per D020. ORM models in `src/core/models.py` mirror the migration's uniques + indexes via `__table_args__`. | **Complete** (commit `c0f4ea4`) |
| 13.2 | Normalization layer in `src/jobs/normalize.py`. `normalize_search_key()` strips `currentJobId` / `origin` / `trk*` / `utm_*` / `gclid` / `fbclid`; sorts + de-dupes list values; case-folds string values but keeps key casing (so LinkedIn's `geoId` / `sortBy` survive). `search_query_fingerprint()` SHA256s the normalized dict for the `normalized_key` column. `normalize_job_content()` + `content_hash()` exclude `UNSTABLE_CONTENT_FIELDS` (`applicant_count`, `promoted`, `view_count`, scrape timestamps, `current_job_id`) so a flapping LinkedIn counter doesn't spawn a fresh snapshot row. | **Complete** (commit `3f55c45`) |
| 13.3 | Freshness state machine in `src/jobs/state.py`. `next_state(current, event)` covers the four documented events (`enriched_ok` / `refresh_failed` / `source_404` / `evict` / `tick`); illegal transitions raise `IllegalTransitionError`. `project_by_time()` is the pure time-decay projection (`active→stale @24h`, `stale→unknown @72h`, `unknown→expired @7d`) the Phase 14 `jd_health_check` job will drive. `is_safe_to_apply()` is the single Phase 17 pre-submit gate. | **Complete** (commit `86b8b2e`) |
| 13.4 | `cached_search()` in `src/jobs/search.py` -- the cache-first orchestrator. Normalizes params → upserts `SearchQuery` → returns cached postings when `status="fresh"` and within the freshness window → otherwise acquires a Phase 12 distributed lock keyed `jobs:search:{source}:{fingerprint}` → re-checks the freshness window inside the lock (concurrent writer may have populated fresh results) → calls `fetch_fn` (sync or async) → persists postings as `search_results` rows → **prunes links whose `last_seen_at < run_started_at`** so removed postings don't replay (codex P2 fix, commit `aacde6d`) → marks the query `fresh`. On scrape failure the old cache is preserved; the query flips to `stale` with `last_error`. Lock contention returns the cached rows with `stale=True` so the UI can show a "refresh in progress" spinner. `JobIndexStore` (`src/jobs/store.py`) is the persistence facade with `find_query` / `upsert_query` / `mark_query_run` / `upsert_posting` / `link_result` / `prune_results_not_seen_since` / `get_results` / `find_snapshot` / `insert_snapshot` / `enqueue_refresh`. | **Complete** (commit `ce6bac9`) |
| 13.5 | Detail enrichment in `src/jobs/enrich.py`. `enrich_posting()` runs `scrape → normalize → content_hash`, no-ops if the hash matches the latest snapshot (still advancing the state machine via `enriched_ok`), otherwise inserts a new immutable `JobSnapshot`, points `posting.latest_snapshot_id` at it, and emits `ContentChangedEvent` to any listener registered via `on_content_changed`. `mark_refresh_failed` / `mark_source_404` are the documented transient / 404 transitions. Listener exceptions are logged and swallowed -- a buggy downstream subscriber can't break enrichment. | **Complete** (commit `8f2d0f9`) |
| 13.6 | Context-aware predicate `should_refresh(posting, context, now=)` in `src/jobs/freshness.py`. Three documented contexts (`search_display: 72h`, `generate_materials: 24h`, `before_submit: 6h`). `new` always refreshes (no snapshot); `unknown` / `expired` / `archived` always refresh (degraded / terminal). The state machine + this predicate compose on two axes: state governs lifecycle, predicate judges time. Returns a `FreshnessVerdict(should_refresh, reason, age_hours, budget_hours)` so callers can both gate behaviour and surface "why" to the UI or trace store. | **Complete** (commit `6aaf3a4`) |
| 13.7 | Web UI freshness banner on the Jobs page. `POST /api/jobs/index/freshness` and `POST /api/jobs/index/refresh` (enqueues a `kind="search.refresh"` task on `refresh_tasks` for Phase 14 to consume); `GET /api/jobs/index/posting/{id}?context=...` for per-posting verdicts. Frontend: `frontend/src/components/JobIndexBanner.vue` renders "Last updated 18h ago · N indexed" plus a [Refresh] button; the banner emits `refresh` which `JobsView.forceRefreshSearch()` translates into a force-refresh by clearing `lastFetchSignature`. Application layer (`src/application/job_index.py`) owns the session lifecycle and degrades gracefully (`ProgrammingError → known=false`) when the migration hasn't been applied. | **Complete** (commit `eac302d`) |
| 13.8 | Legacy file-cache migration + removal. `src/jobs/legacy.py` walks `data/cache/linkedin_search/*.json` and replays each file as one `SearchQuery` (status='stale' so the next real search re-scrapes -- we don't trust historical disk data) plus one `SearchResult` link per contained job; idempotent across re-runs. `clear_indexed_searches()` replaces the old `clear_linkedin_search_cache()` (cascades `search_results` via the FK). `autoapply jobs import-legacy-cache --legacy-dir --delete` is the new CLI surface. `src/intake/search_cache.py` is deleted; `src/intake/search.py` removes the file-cache short-circuit (end-to-end wiring of `search_linkedin` into `cached_search` lands with Phase 17's daily run loop). | **Complete** (commit `99e2dea`) |
| **fix** | **codex review P2**: `JobIndexStore.prune_results_not_seen_since(query_id, threshold)` + `cached_search()` capture of `run_started_at` before `fetch_fn` -- postings missing from the new scrape lose their `search_results` link instead of replaying on the next cache hit. `outcome.counts` now carries `"removed"` so the UI can surface "N new / M removed / K updated". | **Complete** (commit `aacde6d`) |
| 13.9 | **tenant_id retrofit migration** (see D026). One alembic migration adds `tenant_id TEXT NOT NULL DEFAULT 'default'` to every legacy table from Phase 11 and earlier (`jobs`, `applications`, `applicant_profile`, `bullet_pool`, `story_bank`, `qa_bank`, `templates` / `template_packages`, plus any other table without the column today). Backfills existing rows. ORM models in `src/core/models.py` add the field. Existing query paths are not changed -- they keep their current global-read behavior -- but every new Phase-14 code path **must** thread an explicit tenant context. Verification: `alembic upgrade head` is idempotent, the full test suite still passes, every table reachable from `Base.metadata` has a `tenant_id` column. | **Pending** |

**Verification**: 1004 passed, 1 skipped on `feat/phase-13`; `ruff check` clean; frontend builds clean. Specifically: tracking-param collisions land on the same `normalized_key` (test_jobs_normalize.py); identical JD content does not spawn a second snapshot row, edited content does (test_jobs_enrich.py); cache hits return < 2 ms in the stub-store path; lock contention returns `stale=True` against real Redis (fakeredis); scrape failure preserves the previous run's rows + flips the query to `stale`; postings removed between runs are pruned on the next refresh (test_refresh_prunes_postings_no_longer_in_source). End-to-end LinkedIn integration via `cached_search` is deferred to Phase 17 per the in-code comment in `src/intake/search.py`. `tenant_id="default"` on every new row.

### Phase 14: Task Queue + Scheduled Work (~2.5 weeks, Celery-based)

Production-grade task execution substrate. Lays the foundation Phase
17 needs to run nightly batches without the user being at the keyboard
or a web request staying open. **Switched to Celery 5.x** as of roadmap
v3.1 (see D025): the originally-planned self-built task model + queue
transport + worker runtime is dropped. AutoApply layers an "agent
boundary + HITL + trace + tenant context" wrapper on top of Celery.
D023's principle ("queue owns execution reliability; agents own bounded
decisions") is preserved.

| Sub | Scope | Status |
|-----|-------|--------|
| 14.1 | **Celery wiring + skeleton.** `celery_app = Celery("autoapply", broker=REDIS_URL, backend=REDIS_URL)` with `task_acks_late=True`, `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1` (long-task model — do not prefetch). Four queues: `search`, `materials`, `application`, `maintenance`. Router maps task-name prefix → queue; unknown prefixes fall back to `maintenance`. JSON-only serialization. `redbeat_redis_url` + namespace pre-set so 14.5/14.10 Beat lock is consistent. | **Complete** (commit `83de0db`) |
| 14.2 | **Durable `tasks` audit table** (Postgres source of truth; Celery's result backend is transient). Schema: `id, tenant_id, celery_task_id (indexed), kind, queue, payload, idempotency_key, (tenant_id, idempotency_key) unique, status (queued/running/waiting_human/succeeded/failed/cancelled), attempts, parent_task_id, trace_id, last_error, scheduled_for, started_at, finished_at`. Lifecycle signals (`task_prerun` / `task_postrun` / `task_failure` / `task_retry` / `task_revoked`) keep it in sync; handlers tolerate missing rows and swallow exceptions so a bug in audit never poisons a worker. Migration `e1b4f72c8a05`. | **Complete** (commit `259c892`) |
| 14.3 | **`AutoApplyTask` base class** + `src/tasks/context.py` tenant ContextVar. `before_start` reads the `x-autoapply-tenant` header into the ContextVar; `after_return` pops it. `short_circuit_if_already_succeeded(session, key)` returns the prior payload on idempotency-key hit. `call_agent(fn, *a, **kw)` runs a bounded agent and normalises any return shape into `AgentDispatch` with one of five outcomes (`success`/`failed_retryable`/`failed_terminal`/`needs_human`/`needs_followup_task`). Static `enqueue(celery_task, session, EnqueueSpec)` atomically writes a `queued` audit row, sets tenant + `AUDIT_OK_HEADER` headers, and dispatches with the pre-allocated id. | **Complete** (commit `8b5fb4c`) |
| 14.4 | **HITL gate moved to Postgres `gate_queue`** (replaces single-process file backend per D026). Schema: `id, tenant_id, task_id (FK tasks.id ON DELETE SET NULL), kind, summary, payload, status (pending/approved/rejected/expired), requested_at, decided_at, decided_by, decision, reason, ttl_seconds`. `open_request` flips the linked task to `waiting_human` and the worker is *released immediately* — no thread parking. Double-approve returns the existing decision (UI double-click is not a 409); approve-then-reject is a real conflict. Old `src/agent/gate/queue.py` file backend kept as compat for one release. Migration `f2c5d83a91b6`. | **Complete** (commit `880887a`) |
| 14.5 | **Celery Beat** (retires APScheduler per D021 supersede note). `src/tasks/beat.py` publishes six entries: `daily_search` (02:00 UTC) → `search`; `jd_health_check` (hourly), `application_status_sync` (every 6h @ :15), `linkedin_cookie_refresh` (03:00 UTC daily), `cache_eviction` (hourly @ :30), `gate_expire_sweep` (every 15min) → `maintenance`. `install(celery_app)` wires `RedBeatScheduler` so multi-instance Beat acquires leader-election; idempotent under worker autoreload. Beat only enqueues; business logic never runs in the Beat process. | **Complete** (commit `12e3b21`) |
| 14.6 | **12 concrete task kinds** in `src/tasks/tasks.py`, each an `AutoApplyTask` wrapper with a Pydantic payload model — malformed payload raises `TypeError` so Celery treats it as terminal (no retry storm on bad input). Worker-driven: `search.refresh`, `jobs.enrich`, `materials.generate`, `application.{prepare,fill,submit}`. Beat-driven: `search.daily_fanout`, `maintenance.{status_sync,jd_health_check,linkedin_cookie_refresh,cache_eviction,gate_expire_sweep}`. Bodies log-and-return-stub today; Phase 15 / 17 swap bodies without changing task name or payload contract. | **Complete** (commit `f01cab5`) |
| 14.7 | **Four operator-facing CLI groups.** `autoapply worker` wraps `celery -A src.tasks worker`, validates `-Q` against the four-queue allowlist, exposes `--check` to print the resolved invocation. `autoapply beat` selects redbeat. `autoapply tasks list/inspect/retry/cancel/kinds` reads the 14.2 audit table; retry refuses non-failed/cancelled rows; cancel refuses non-queued rows. `autoapply schedule list/run-now` reads/dispatches Beat entries. All four registered in `src/cli/main.py`. | **Complete** (commit `ef59570`) |
| 14.8 | **Web JSON API + minimal SPA view.** `src/web/routes/tasks.py` adds `GET/POST /api/tasks`, `GET /api/tasks/{id}`, `POST /api/tasks/{id}/{cancel,retry}`, `GET /api/schedule`, `POST /api/schedule/{name}/run-now`, `GET /api/gate?status=...`, `GET /api/gate/{id}`, `POST /api/gate/{id}/{approve,reject}`. Every route scoped by `x-autoapply-tenant`; cross-tenant queries return 404. `frontend/src/views/TasksView.vue` adds the `/tasks` page (gate awaiting human, recent tasks, Beat schedule with one-click run-now). | **Complete** (commit `edb8661`) |
| 14.9 | **Task-shape trace integration.** `src/tasks/trace.py` hooks `task_prerun` / `task_postrun` / `task_failure` / `task_retry` to write a `TraceRecord` per attempt to the Phase 8.3 file store and stamp the `trace_id` onto the audit row at prerun (the SPA link is live the moment the task starts). Child tasks dispatched with `x-autoapply-parent-trace` inherit `parent_trace_id` so the viewer can walk the chain. Persistence is best-effort: failed `save()` logs and swallows. | **Complete** (commit `b7ecb57`) |
| 14.10 | **Postgres advisory-lock backstop.** `src/tasks/locks.py` adds `with advisory_lock(session, key)`, a non-blocking `pg_try_advisory_xact_lock` wrapper that the nightly_run orchestrator (Phase 17) and long materials.generate runs (Phase 15) use to guarantee deployment-wide critical sections. Auto-releases on commit/rollback/connection drop. Key is a SHA256-derived 63-bit signed int. | **Complete** (commit `707d94e`) |
| **codex** | **Two-round codex review** P1 + P2 fixes folded in: (a) cancel routes (web + CLI) call `celery_app.control.revoke(celery_task_id, terminate=False)` before flipping the row; (b) `before_task_publish_handler` writes a `queued` audit row for **every** Celery dispatch (Beat ticks, raw `send_task`, retries) so they all show up in `/api/tasks` and `autoapply tasks list` — `AutoApplyTask.enqueue` opts out via `AUDIT_OK_HEADER` because it has already written the row with `idempotency_key` + `parent_task_id`; (c) all four lifecycle handlers (`prerun` / `postrun` / `failure` / `retry`) treat `cancelled` as terminal so the audit row preserves operator intent even in the revoke-vs-claim race. 11 new tests in `test_tasks_codex_review_fixes.py` pin each guarantee. | **Complete** (commit `3de7084`) |

**Verification**: 1161 passed, 1 skipped on `feat/phase-14`; `ruff check` clean; frontend build clean (vite 5.73s, 125kB gzip JS); migrations `e1b4f72c8a05` + `f2c5d83a91b6` applied to dev DB; `codex review` returned no findings on second pass. `autoapply worker -Q materials --check` prints the resolved Celery invocation; `autoapply schedule list` shows all six Beat entries; cancelling a queued task issues a broker revoke and the row stays `cancelled` even if the worker raced the revoke; Beat-dispatched maintenance jobs appear in `/api/tasks` as `queued` rows.

### Phase 15: Resume & Cover Letter Generation v2 (~3 weeks)

Rebuilds materials generation around two explicit resume modes:
patching the user's original source when possible, and LaTeX-first
generation when creating a new resume from a template. Benefits from
Phase 12 (LLM caching), Phase 13 (snapshot binding), and Phase 14
(background material tasks).

| Sub | Scope | Status |
|-----|-------|--------|
| 15.1 | **Source-resume model.** Migration `a3b9d52e7c41` creates `source_resumes` (id, tenant_id required from D026, source_type CHECK IN (docx,latex,pdf), editable BOOL, original_filename, checksum SHA256 unique per tenant, storage_path project-relative, extracted_structure JSONB, size_bytes, notes). `src/generation/source_resume.py` ingests files into `data/source_resumes/<tenant>/<checksum><ext>`, dedupes on `(tenant_id, checksum)`, and extracts shallow structure per type: paragraph (style, text_head, is_bullet) for docx, `\section` positions for latex, heading list via pymupdf for pdf. PDF is editable=False (D024). `resolve_storage_path` rejects traversal. | **Complete** (commit `4e95e98`) |
| 15.2 | **DOCX patch mode** with named-style preservation. `src/generation/docx_patch.py` mutates runs in place rather than `add_paragraph`-ing fresh ones so font/size/bold/italic/style survive. Operations: summary (replace paragraph after 'Summary' heading), skills (rewrite body after 'Skills' heading), bullet (swap List Bullet runs under Experience/Projects; surplus appended via XML clone, deficit blanked since deleting would corrupt list numbering), section_drop (blank body of headings not in section_order, but IR-populated sections always kept so default section_order missing 'summary' does not accidentally blank summary content). Top-level vs sub-heading detection distinguishes 'Heading 1'/'Title' from 'Heading 2+' so bullets nested under Heading 2 job entries are reachable. PatchFallback exception signals 'route to template generation' per D024. | **Complete** (commit `697bd3d`) |
| 15.3 | **LaTeX template package spec.** TemplateManifest grows an optional `latex: LatexConfig` sub-model so DOCX-only packages keep working. LatexConfig declares `compile_engine` (pdflatex/xelatex/lualatex), `assets` (validated to stay inside package dir; D013 mirror), `escape_allowlist` (chars the template handles itself), `required_packages` (advisory), `field_mappings: list[LatexFieldMapping]` (IR-field-name -> LaTeX command + arity 0/1/2), `strict_field_coverage`. `src/documents/latex_manifest.py` exposes `escape_latex` / `resolve_field` / `render_command` / `validate_assets` / `validate_field_coverage` so engine + renderer + adapter share one schema. | **Complete** (commit `ef81afe`) |
| 15.4 | **Manifest-adapter LaTeX renderer.** `src/documents/latex_renderer.py` adds the path for user-uploaded templates with custom `\command{...}` semantics. Templates declare `{{resume.commands}}`; the renderer iterates `manifest.latex.field_mappings`, builds the command block via `render_command`, substitutes. Empty resolved fields produce no command (avoids `\cmd{}` rendering visibly empty). Strict mode errors with the list of uncovered IR fields. `compile_via_manifest` honors `compile_engine` (errors clearly when binary missing); copies assets preserving subdirectories (codex P2 fix). Falls through to `compile_latex_to_pdf` for placeholder-only templates. | **Complete** (commit `57de801`) |
| 15.5 | **Materials router** `src/generation/materials_router.py`. `patch_existing` (docx -> 15.2 patcher; PatchFallback routes to template; latex -> regenerate; pdf -> template per D024) vs `generate_from_template` (latex with manifest.latex -> 15.4 renderer; latex without manifest.latex -> legacy placeholder engine per codex P2 fix; docx -> existing resume_builder). Every MaterialsOutcome carries MaterialsBindings (job_snapshot_id, source_resume_id, template_package_id, profile_version, trace_id, tenant_id) so Phase 17 review queue + trace viewer can walk back to the JD + source/template. SourceResumeView keeps router decoupled from SQLAlchemy. | **Complete** (commit `e86f15d`) |
| 15.6 | **`jd_lookup` agent tool** `src/agent/tools/jd.py`. Read-only dotted-path access to a bound `JobSnapshot` (audit binding per D019). Empty path returns section index (snapshot_id + scalar/nested previews); scalar paths return truncated value; nested paths drill into JSONB with `_count`/keys summaries. Missing paths return helpful 'available keys at X: [...]' with `is_error=False` so the agent adjusts. Mirrors profile_lookup's shape so cover-letter / resume / filter agents share one retrieval idiom. | **Complete** (commit `95c8efb`) |
| 15.7 | **`AgentCoverLetter` orchestrator** + fact-drift post-guard + deterministic fallback. `src/generation/agent_cover_letter.py` runs a bounded agent (via injected `llm_fn`) to produce CoverLetterDocument IR; `src/generation/fact_drift.py` runs BETWEEN the IR and the renderer: number drift blocks (10k <-> 10000 normalized), entity drift warns, length sanity flags. Five-tier fallback: use_agent=False -> deterministic_only; no llm_fn -> deterministic_only; agent raises -> agent_error_fallback; agent returns malformed -> agent_error_fallback; drift detected -> agent_drift_fallback. The bounded-agent loop itself is wrapped by AutoApplyTask.call_agent in the materials task (D023 boundary preserved). | **Complete** (commit `983a5a5`) |
| 15.8 | **Template adapter assistant** `src/documents/template_adapter.py`. propose_manifest scans `\newcommand` declarations + `\foo{...}` usages, matches against curated `_CONVENTIONAL_MAPPINGS` (resumeheadername / experienceitem / etc.), warns on unmatched commands, errors when `{{resume.commands}}` is absent, records `\usepackage` as advisory required_packages, runs a sample render against a stub IR. finalize_proposal gates persistence on `sample_render_ok=True`, no error notes, and validate_assets passing; the operator's flow runs the real compile + the Phase 15.10 gate before this is called. Per D024: 'arbitrary LaTeX may be imported, but it is not active until a manifest exists and a sample compile passes.' | **Complete** (commit `98eacad`) |
| 15.9 | **Eval suites** for materials_docx_patch, materials_latex_template, cover_letter. Each ships a runner in `src/agent/eval/runner.py` + JSON fixtures under `tests/agent_evals/fixtures/`. Runners produce JSON envelopes; two new scorer types (`json_field_equals`, `json_field_contains`) walk dotted paths into the parsed envelope. 7 fixtures: bullet_swap_preserves_styles, fallback_when_source_missing, manifest_adapter_renders, escapes_special_chars, grounded_output_passes, number_drift_falls_back, agent_failure_falls_back. `autoapply eval --suite materials_docx_patch` etc. works from the CLI. | **Complete** (commit `488b23d`) |
| 15.10 | **HITL gate triggers** for persistent grounding mutations only (D023 boundary). `src/generation/gate_triggers.py` exposes `is_gateworthy(kind)` (True for `materials.bullet_pool_mutation` / `materials.story_bank_mutation` / `materials.template_manifest_persist`; False for one-shot generation) + propose helpers that open Phase 14.4 `gate_queue` rows with operator-friendly summaries ('1 add, 1 edit. Rationale: ...'). `find_pending_for_task(task_id)` lists pending gates blocking a `materials.generate` task. | **Complete** (commit `439d2d7`) |
| **codex** | **Codex review P2 fixes** folded in: (1) materials router no longer rejects legacy LaTeX templates that lack a Phase 15.3 latex manifest block -- now falls back to `latex_engine.build_resume_tex_from_ir` placeholder rendering; (2) PDF source-resume ingest captures `len(doc)` INSIDE the `pymupdf.open` `with` block so page_count survives close; (3) `compile_via_manifest` preserves manifest asset subdirectories so `\includegraphics{images/logo.png}` resolves at compile time. 5 new tests pin each fix; existing 'unsupported' assertion updated to the new fallback behavior. | **Complete** (commit `9b813a3`) |

**Verification**: 1332 passed, 1 skipped on `feat/phase-15`; `ruff check` clean; alembic upgraded dev DB to revision `a3b9d52e7c41`; `codex review` returned no findings on second pass. Manual smoke deferred to Phase 17 wiring (when Celery tasks actually invoke the agents end-to-end).

### Phase 16: Filter Agent + Explainability Layer (~1.5 weeks)

Not a replacement for the deterministic filter -- an explainability
layer on top, plus agent invocation for borderline jobs only.

| Sub | Scope | Status |
|-----|-------|--------|
| 16.1 | **`RuleVerdict` schema evolution.** `RuleResult` grows `rule_id` / `verdict` / `evidence_excerpt` fields kept in sync with the legacy `passed` field; each hard rule in `src/matching/rules.py` extracts a bounded JD excerpt (~200 chars, ~80 chars of context, whitespace collapsed, ellipsis on truncation) via curated regex patterns -- visa-sponsorship clauses for `work_authorization`, "5+ years" phrases for `experience`, degree mentions for `education`, structured `employment_type=...` markers when the rule fires on a struct field rather than text. `ScoreBreakdown` gains `job_snapshot_id` (Phase 13 binding) and `disqualify_results: list[RuleResult]` alongside the legacy string list. `score_job(job, ctx, job_snapshot_id=...)` + `score_jobs(snapshot_ids={job_id: snap_id})`. Aggregate `RuleVerdict.fail_reasons: list[str]` preserved unchanged so the existing 33 matching tests keep passing. | **Complete** (commit `203becb`) |
| 16.2 | **Edge-case agent + `score_breakdown` tool.** `src/agent/tools/score_breakdown.py` exposes a read-only dotted-path interface bound to one `ScoreBreakdown` (audit binding matches `jd_lookup` from 15.6): paths `""` (summary), scalar (`final_score` / `skill_overlap` / ...), `rules` (full list), `rules.<rule_id>`. `src/matching/edge_case_agent.py` ships `EdgeCaseAgent` which fires only when `0.4 <= final_score <= 0.6` AND the job isn't hard-rule disqualified. Returns `EdgeCaseDecision` with one of four `kind` values: `not_invoked` (out-of-band / disqualified / `use_agent=False` / no `llm_fn`), `agent_ok` (parsed JSON with `verdict` in {`surface`, `reject`, `abstain`}), `agent_error` (`llm_fn` raised), `agent_malformed` (JSON missing / wrong shape / invalid verdict literal). Confidence clamped to `[0,1]`. Trailing-JSON-after-thinking-text parsing supported. Hard rules NEVER overridden -- the agent's scope is score-band ambiguity only. | **Complete** (commit `bbc13b9`) |
| 16.3 | **"Why was this filtered?" UI.** `src/application/matching.py` adds `explain_job(payload)` which strips `serialize_job()` flat fields before coercing into `RawJob`, threads `raw_data.job_snapshot_id` into the breakdown when present, returns `{ok, score_breakdown, warnings}` so the route can report "no active profile" / "malformed payload" without raising. `POST /api/matching/explain` is the thin wrapper. `_score_jobs` + `_select_batch_jobs` now stash `ScoreBreakdown.to_dict()` into `job.raw_data['score_breakdown']` so the popover renders inline without a round-trip. `frontend/src/views/JobsView.vue` adds an Info chip-button next to the existing "Review" badge on disqualified job cards; the Dialog popover renders `final_score` chip, `job_snapshot_id` chip (truncated), per-rule cards with rule_name / verdict chip / reason / `evidence_excerpt` block; falls back to `api.matchingExplain(job)` when the inline breakdown is absent (legacy cached results). `api.js` gains `matchingExplain(job)`. | **Complete** (commit `c57d108`) |
| 16.4 | **`filter_borderline` eval suite (10 fixtures).** `src/agent/eval/runner.py` adds `_filter_borderline_runner` which builds a `ScoreBreakdown` from the fixture's `breakdown` dict (with optional `rules` list of `RuleResult`-shaped entries), instantiates `EdgeCaseAgent` with a stub `llm_fn` (returns fixture's `llm_output` verbatim; raises on `__raise__` sentinel; stays `None` when omitted), emits the decision as a JSON envelope. Ten fixtures cover the full decision matrix: 01 high-skill + low-keyword surface; 02 borderline-wrong-role reject; 03 quality-multiplier-drag surface; 04 hard-rule disqualified short-circuit (verifies agent never overrides hard rules); 05 below-band short-circuit; 06 above-band short-circuit as surface; 07 malformed output fall-back; 08 `llm_fn` raises fall-back; 09 abstain on thin signal; 10 invalid verdict literal fall-back. The 70%-human-agreement bar is a Phase 17 concern (real LLM); this suite is the deterministic offline harness. | **Complete** (commit `9198a3b`) |
| **codex** | **Codex review P2 fix** folded in: removed 33 committed runtime trace artifacts under `data/agent_traces/` that the existing `TraceStore` + `/api/agent/traces` viewer was serving as if they were real local history on fresh checkouts. Path now in `.gitignore`. | **Complete** (commit `5702da7`) |

**Verification**: 1398 passed, 1 skipped on `feat/phase-16`; `ruff check` clean; frontend build clean (vite 6.00s, 126kB gzip JS). The popover renders any rejected job's structured reasons + evidence excerpts in one click; the agent's per-call cost budget (the plan's "< $0.50 per 100 jobs") is a Phase 17 measurement once a real LLM is wired in.

### Phase 17: Daily Run Loop + Review Queue (~2 weeks)

Integration phase. Threads Phase 14 (task queue + scheduler) + Phase
13 (job index + freshness) + Phase 12 (cache) + Phase 9 / 15 (agents) into
the "sleep, wake up to a review queue" end-to-end flow.

| Sub | Scope |
|-----|-------|
| 17.1 | `nightly_run` orchestrator (registered with Phase 14): search (cache-first, refresh stale) → filter (with 16's explainability) → take top-N → enqueue `materials.generate` and `application.prepare` tasks. Workers run the resume/cover-letter agents (Phase 15) and form-filler agent (Phase 9) under task-level retry/timeout policy. **Never auto-submits.** |
| 17.2 | Review queue model: new table `review_queue(id, tenant_id, job_id, job_snapshot_id, materials_path, status, created_at, reviewed_at, decision, reason)`; state machine `pending → approved → submitted` or `pending → rejected`. |
| 17.3 | Review UI at `/review`: kanban with `[Pending] [Approved] [Submitted] [Rejected]` columns; each card has job summary + materials preview + one-click approve/reject. |
| 17.4 | Bulk operations: multi-select approve, bulk-reject by company/keyword, approve-and-submit (still gated by Phase 4 / 9 HITL final gate). |
| 17.5 | **Pre-submit hard gate**: every approve-and-submit re-runs `should_refresh(job, "before_submit")`; if the snapshot is now expired or > 6h stale, refresh first; if the job is `expired` block submission entirely. |
| 17.6 | Daily digest at 08:00: desktop notification + dashboard banner -- "Last night: 12 new jobs, 7 passed filter, 3 in review queue, est. cost $0.21". |
| 17.7 | Kill switch: `autoapply pause-nightly` -- pauses all schedules and clears the pending queue (for vacation). |

**Verification**: schedule a nightly run at 23:00 Monday → wake Tuesday 08:00 → N pre-tailored applications in the review queue, each approvable in < 30s, submit triggers HITL gate as expected; expired-job pre-submit gate blocks correctly; no manual CLI invocation needed between Mon evening and Tue morning.

### Phase 18: Multi-Tenancy & Auth Hardening (~2.5 weeks)

Activates the commercial-readiness work seeded across Phases 12-17.
SaaS business layer (billing, sign-up flow, marketing site) is NOT
in scope -- this phase only makes the existing system safe to host
for multiple isolated users.

**Honest scope note**: Phase 13.9 already landed `tenant_id` on every
table, so the schema retrofit is genuinely "activate existing work."
But 18.2 / 18.4 / 18.7 are **net-new construction**, not retrofit:
`src/web/` has no auth layer today, Redis keys have no tenant prefix
today, and `src/providers/store.py` is a single global JSON file
today. 18.1 / 18.3 / 18.5 / 18.6 are the only true "activations."

| Sub | Scope |
|-----|-------|
| 18.1 | `tenants` + `users` tables; bind the `tenant_id='default'` rows left behind by 13.9 to real tenants. |
| 18.2 | **Build from scratch** the FastAPI auth middleware: session/token parsing, `current_tenant_id` injected into a `ContextVar`, ORM sessions filter via SQLAlchemy event listeners, Celery task headers carry tenant context (14.3 reserves the hook). |
| 18.3 | Postgres Row-Level Security policies as DB-level backstop -- even a query that forgets the `tenant_id` filter cannot leak rows. |
| 18.4 | **Refactor** Redis key naming: every namespace prefixed `tenant:{id}:`; `src/cache/base.py` key construction *requires* tenant context (raises rather than falling back to a default). Inspector UI shows current tenant only. |
| 18.5 | Per-tenant quotas: LLM token budget / scrape rate / storage. Exceeding returns 429 with a structured retry-after. |
| 18.6 | Audit log table (`audit_events`): submission, settings change, credential operation, manual schedule trigger. Append-only. |
| 18.7 | **Refactor** the credential store: `src/providers/store.py` moves from one global JSON file to `data/tenants/{id}/credentials/`; keyring entries get tenant prefixes; migrate `data/providers/credentials.json` into the `default` tenant. |

**Verification**: two tenants seeded with overlapping email / LinkedIn cookies → tenant A's session cannot read tenant B's jobs / snapshots / applications / credentials / Redis keys, verified by direct SQL and direct Redis CLI; quota exhaustion returns 429; RLS policy in place even if the ORM layer is bypassed.

### Timeline summary

| Phase | Scope | Est. | Cumulative |
|-------|-------|------|------------|
| 11 | Reliability & Cleanup | 1w | 1w (done) |
| 12 | Cache Infrastructure (Redis) | 1.5w | 2.5w (done) |
| 13 | Job Index & Freshness Engine | 2w | 4.5w (13.1-13.8 done) |
| 13.9 | tenant_id retrofit migration | 0.3w | 4.8w |
| 14 | Task Queue + Scheduled Work (Celery) | 2.5w | 7.3w |
| 15 | Resume & Cover Letter Generation v2 | 3w | 10.3w |
| 16 | Filter Agent + Explainability | 1.5w | 11.8w |
| 17 | Daily Run Loop + Review Queue | 2w | 13.8w |
| 18 | Multi-Tenancy & Auth Hardening | 2.5w | 16.3w |

~3.5-4 months to v1.0 commercial-ready core (no SaaS business layer).
Phase 14 grows 0.5w over v3 to absorb the HITL gate backend migration;
Phase 18 grows 0.5w to honestly reflect that auth middleware / Redis
namespace refactor / credential store are net-new builds, not "activations."

## Cross-cutting Concerns

These are not phases but quality bars enforced across all of 11-18:

- **Test discipline**: every new module ships with tests; no new code can drop the suite below the current 680 passing (1 skipped LinkedIn smoke).
- **Lint discipline**: `ruff check src/ tests/` must stay clean.
- **Codex review per sub-phase**: each sub-phase gets a `codex review --uncommitted` pass before commit; P1 findings block merge.
- **Cost ceiling**: any eval suite that pushes total cost above $1.00 / 100 cases needs explicit justification.
- **Docs sync**: PROJECT_MANAGEMENT.md and CHANGELOG.md updated at the end of every Phase, not in a batch later.
- **Multi-tenancy hygiene** (Phase 12+): every new table carries `tenant_id`; every new Redis key is prefixed; every new background task accepts a tenant context. No exceptions -- otherwise Phase 18 turns into a rewrite.
