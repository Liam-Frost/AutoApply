# AutoApply — Full Project Plan

This document is the authoritative end-to-end project plan: what AutoApply
is, what it is built from, what is shipped, and what remains to ship through
Phase 18 (v1 commercial-ready core).

It is intentionally redundant with parts of `README.md`, `docs/PROJECT_MANAGEMENT.md`,
`docs/AGENT_ARCHITECTURE.md`, and `docs/DECISIONS.md`. Where any of those
documents disagree with this one, the source of truth is:

| Topic | Authoritative source |
|---|---|
| Per-sub-phase scope, ETAs, verification | `docs/PROJECT_MANAGEMENT.md` |
| Why we chose / rejected each design | `docs/DECISIONS.md` |
| Agent harness internals | `docs/AGENT_ARCHITECTURE.md` |
| User-facing setup | `docs/DEPLOYMENT.md` |
| This file | Strategy + history + roadmap summary |

Last refreshed: **2026-05-14 (roadmap v3.1)**. v3.1 calibrates v3 in four
places:
(a) Phase 14 task queue switches to Celery (the original "self-built task model +
queue transport + worker runtime" plan is dropped; see D025). APScheduler is
retired in favor of Celery Beat for cron triggers.
(b) A new Phase 13.9 sub-phase lands before Phase 14 starts: one-shot
`tenant_id` retrofit migration for every legacy table from Phase 11 and earlier,
turning D020's discipline into a schema-level guarantee (see D026).
(c) The HITL gate backend moves from single-process file JSON to a
Postgres-backed table that lives alongside the Celery task state (folded into
Phase 14), so Phase 14 multi-worker and Phase 17 review queue don't each
reinvent it (see D026).
(d) Phase 15.3 LaTeX scope is clarified: `src/documents/latex_engine.py` already
exists, so Phase 15 is not "build LaTeX from scratch" — it is "add the template
package spec + manifest + adapter convention on top of an existing engine."

---

## 1. Goal

Build an end-to-end job-application automation system covering seven
capability layers: job intake & filtering, applicant memory, resume &
cover-letter tailoring, quick-question response, document processing,
form-filling automation, and tracking / analytics.

Commercial ambition has been preserved since the 2026-05-12 v2 re-plan
and sharpened in the 2026-05-14 v3 update: multi-tenancy, Redis-backed
cache/queue transport, distributed locks, per-tenant quotas, Postgres
RLS, and a background worker model are all in the roadmap, even though
no SaaS business layer is on the table yet.

## 2. Design Principles

1. **State machine-driven.** Every application is a state machine —
   interruptible, resumable, auditable.
2. **Evidence-grounded materials.** No full-text LLM rewrite. Agents select
   from profile facts, story bank, and tagged bullet pools, optionally apply
   light lexical rewrite, and pass through fact-drift guards.
3. **Two resume paths.** Patch the user's original editable source when the
   goal is to preserve their existing style; use LaTeX-first template
   packages when generating a new resume from scratch. In both paths, LLMs
   produce structured IR or adapter proposals; deterministic renderers own
   final files.
4. **Human-in-the-loop on every submit.** Default pauses before submit;
   `--auto-submit` is an opt-in escape hatch that still passes through the
   gate queue.
5. **Full audit trail.** Screenshots, DOM snapshots, file versions, QA
   responses are all persisted. Phase 13 extends this with content-hashed
   JD snapshots so we know forever which JD version a given letter / resume
   was generated against.
6. **Provider-agnostic LLM.** No subprocess- or REST-specific code outside
   `src/providers/`. Every call site uses `generate_text()`.
7. **Queue-managed automation.** Background tasks own scheduling, retry,
   idempotency, and worker lifecycle. Agents run inside one bounded task and
   return structured outcomes; they do not own queue ack/nack or global
   orchestration.

## 3. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Language / runtime | Python 3.12+, `uv` | Standard async + typing baseline |
| Backend | FastAPI + Click CLI (`autoapply`) | Single codebase serves web + CLI |
| Frontend | Vue 3 + Vue Router + Vite + Tailwind v3 + shadcn-vue + reka-ui | See D015 |
| Browser automation | Playwright (Python, async) | Full DOM access + persistent context for LinkedIn login |
| LLM providers | OpenAI / Anthropic / Gemini (REST via `httpx`) **or** Claude Code CLI / Codex CLI (subprocess) — all behind `ProviderRegistry` | See D016 |
| Agent harness | In-house ReAct loop in `src/agent/` — bounded steps, allow-listed `ToolRegistry`, file-backed HITL gate, JSON-on-disk trace store, fixture-driven eval | See D017 (no LangChain / LangGraph) |
| Database (source of truth) | PostgreSQL + pgvector + alembic | Vector search for matching; alembic for schema migrations |
| Cache / lock / queue (Phase 12+) | Redis 7+ | L2 cache, distributed lock primitive (`SET NX PX`), task queue substrate; see D018 |
| Task queue / scheduler (Phase 14+) | Celery 5.x + Redis broker + Redis result backend + Celery Beat (cron trigger) | See D025 (replaces the original "self-built queue + APScheduler" plan); D023's agent/queue boundary principle is retained |
| Document processing | python-docx + LaTeX toolchain + docx2pdf / LibreOffice | DOCX patching for original resumes; LaTeX-first for newly generated resumes; PDF as derived output |
| Config | YAML (`config/settings.yaml`, `config/filters.yaml`, `config/companies.yaml`) + `.env` overrides | Defaults → file → env, with credential URL encoding |
| Target ATS platforms | Greenhouse / Lever / Ashby; LinkedIn for discovery | Direct-apply for the first three; LinkedIn auth via Playwright persistent context |

## 4. Code Layout (actual, not aspirational)

```
src/
├── core/                # Config loader, DB session, ORM models, state machine
├── agent/               # In-house agent harness
│   ├── tools/           #   tool ABC + builtin / browser / profile tools
│   ├── core/            #   bounded ReAct loop + cost telemetry
│   ├── gate/            #   file-backed HITL approval queue
│   ├── trace/           #   JSON-on-disk trace store
│   └── eval/            #   fixture-driven eval runner + scorers
├── providers/           # LLM provider abstraction
│   ├── base.py          #   LLMProvider ABC + ProviderKind + AuthType
│   ├── openai.py / anthropic.py / gemini.py   # REST adapters via httpx
│   ├── claude_cli.py / codex.py               # Subprocess adapters
│   ├── api_base.py      #   shared REST helpers
│   ├── store.py         #   credential storage (0600 file + OS keyring fallback)
│   └── registry.py      #   primary / fallback dispatch into generate_text
├── intake/              # Job scraping & schema
│   ├── greenhouse.py / lever.py / linkedin.py # Adapters
│   ├── schema.py        #   RawJob / JobRequirements / employment-type classifiers
│   ├── jd_parser.py     #   LLM-assisted parsing + regex fallback
│   ├── batch.py / search.py / storage.py
│   ├── filters.py       #   YAML-driven filter profiles
│   └── search_cache.py  #   File-backed JSON cache (slated for Phase 13.8 removal)
├── matching/            # Filtering & scoring
│   ├── rules.py         #   Hard rules (authorization, experience, education, ...)
│   ├── semantic.py      #   Embedding + TF-similarity scoring
│   └── scorer.py        #   Composite scorer + quality multiplier
├── memory/              # Applicant memory
│   ├── profile.py       #   Identity / education / skills / experiences / projects
│   ├── bullet_pool.py   #   Tagged bullets with usage counters
│   ├── story_bank.py    #   STAR stories with theme tags
│   ├── qa_bank.py       #   Question patterns + canonical answers + variants
│   └── resume_importer.py # PDF/DOCX → Claude CLI → structured YAML
├── generation/          # Resume + cover letter + QA
│   ├── ir.py            #   Resume / cover letter IR
│   ├── resume_builder.py
│   ├── cover_letter.py
│   ├── fitting.py       #   Template capacity-aware fitting
│   ├── validator.py     #   Artifact validation (page count, length)
│   └── qa_responder.py  #   Classifier + cascading answer generator
├── execution/           # Browser automation + form fill + submit
│   ├── browser.py       #   Playwright wrapper
│   ├── form_filler.py   #   Deterministic filler (default path)
│   ├── agent_form_filler.py # Phase 9 agent orchestrator
│   ├── file_uploader.py
│   └── ats/             #   Per-ATS adapters (greenhouse / lever / ashby / generic / base)
├── documents/           # DOCX + PDF + page-count + templates
├── tracker/             # CRM: applications table + analytics + CSV export
├── application/         # Shared application-layer services used by CLI + Web
├── cli/                 # Click command tree (autoapply, init, search, apply, status, provider, web, eval, ...)
├── web/                 # FastAPI app factory + JSON API routes + SPA static mount
└── utils/               # llm.generate_text bridge, rate limiter, logger
```

Five top-level skeleton folders from the original plan still exist
empty (`src/applicant/`, `src/cover_letter/`, `src/filter/`,
`src/resume/`, `src/scraper/`). They are historical placeholders and
should be deleted on the next housekeeping pass.

## 5. Data Model (current)

Current Postgres schema lives in `migrations/versions/` (alembic). The
core tables are:

```sql
jobs (
  id UUID PRIMARY KEY,
  source TEXT,                       -- greenhouse / lever / ashby / linkedin
  source_id TEXT,                    -- per-source job id; (source, company, source_id) is the dedup key
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT,
  employment_type TEXT,              -- intern / fulltime / coop
  seniority TEXT,
  description TEXT,
  description_embedding vector(1536),
  requirements JSONB,
  visa_sponsorship BOOLEAN,
  ats_type TEXT,
  application_url TEXT,
  raw_data JSONB,
  discovered_at TIMESTAMPTZ DEFAULT NOW(),
  expires_at TIMESTAMPTZ
);

applications (
  id UUID PRIMARY KEY,
  job_id UUID REFERENCES jobs(id),
  status TEXT NOT NULL DEFAULT 'DISCOVERED',
  match_score FLOAT,
  resume_version TEXT,
  cover_letter_version TEXT,
  qa_responses JSONB,
  screenshot_paths JSONB,
  error_log TEXT,
  state_history JSONB,
  fields_filled INT, fields_total INT,
  files_uploaded JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  submitted_at TIMESTAMPTZ,
  outcome TEXT,                      -- pending / rejected / oa / interview / offer
  outcome_updated_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ
);

applicant_profile (
  id UUID PRIMARY KEY,
  section TEXT NOT NULL,             -- identity / education / skills / experience / projects
  content JSONB NOT NULL,
  content_embedding vector(1536),
  tags TEXT[],
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

bullet_pool (
  id UUID PRIMARY KEY,
  category TEXT,
  source_entity TEXT,
  text TEXT NOT NULL,
  text_embedding vector(1536),
  tags TEXT[],
  used_count INT DEFAULT 0
);

qa_bank (
  id UUID PRIMARY KEY,
  question_pattern TEXT,
  question_type TEXT,
  canonical_answer TEXT,
  variants JSONB,
  confidence TEXT DEFAULT 'high',
  needs_review BOOLEAN DEFAULT FALSE
);
```

The application state machine has 11 states:

```
DISCOVERED → QUALIFIED → MATERIALS_READY → FORM_OPENED
→ FIELDS_MAPPED → FILES_UPLOADED → QUESTIONS_ANSWERED
→ REVIEW_REQUIRED → SUBMITTED → FAILED → NEEDS_RETRY
```

Phase 13 will add a separate cluster of tables for the **Job Index &
Freshness Engine**:

```sql
job_postings        -- entity identity (UNIQUE(source, source_job_id))
job_snapshots       -- content version, content_hash, immutable
search_queries      -- normalized search condition + freshness state
search_results      -- search → posting many-to-many (per scrape)
refresh_tasks       -- priority queue of pending scrapes
```

Plus a new `applications.job_snapshot_id` FK that pins every
generated artifact to the exact JD content it was produced against.
Every Phase-12+ table carries a `tenant_id` column (default `"default"`
until Phase 18). Phase 13.9 backfills the same column onto every legacy
table (`jobs`, `applications`, `applicant_profile`, `bullet_pool`,
`story_bank`, `qa_bank`, etc.) — see D020 / D026.

## 6. Layered Architecture

### Layer 1: Job Intake
Greenhouse / Lever / Ashby / LinkedIn adapters; unified `RawJob` schema;
LLM-assisted JD parsing with regex fallback; deduplication on `(source,
company, source_id)`. Phase 13 will replace the file-backed search cache
with the Job Index & Freshness Engine.

### Layer 2: Matching & Filtering
Three-tier scoring:
1. **Hard rules** (work authorization, experience-year cap with 1-year
   grace, education, employment type, spam / ghost-job detection)
2. **Semantic** (embedding overlap on description / responsibilities /
   requirements + TF-similarity fallback when embeddings unavailable)
3. **Risk** (visa, ghost reposting, sparse JDs, missing apply URL)

Composite scorer: weighted must-have (70%) / preferred (30%) skill
overlap + keyword similarity + rule bonus × quality multiplier.

Phase 16 adds a reason chain and an edge-case agent for borderline
scores `[0.4, 0.6]`.

### Layer 3: Applicant Memory
Profile YAML → DB ingestion with per-section embeddings and tagged
bullets. `qa_bank` includes geography + role-type variants and a
`needs_review` flag for high-risk question types (authorization,
sponsorship, salary, start date). Resume importer turns DOCX / PDF
resumes into structured YAML via Claude CLI.

### Layer 4: Resume / Cover Letter Generation
Structured IR + block-based assembly. Bullets are selected from the
pool by tag overlap, then optionally lexically rewritten under a
fact-drift guard (rejects rewrites whose length ratio falls outside
`[0.3, 2.0]`). Cover-letter generation is constrained to four
sections (opening, evidence, company tie-in, close), 250-400 words,
no fabrication. Quick-question answering cascades QA-bank → template →
LLM → flag for review.

Phase 15 promotes cover-letter generation to an agent (binding to a
specific `job_snapshot_id`).

### Layer 5: Form Filling & Submission
Each application is an 11-state state machine. The deterministic
`form_filler.py` is still the default; `agent_form_filler.py` (Phase
9) is the agent path, gated on confidence and the HITL approval
queue. ATS adapters live in `src/execution/ats/` (Greenhouse / Lever
/ Ashby / generic). Rate limiter enforces random delays, hourly caps,
and per-error cooldowns.

### Layer 6: File Pipeline
Template packages under `data/templates/<document_type>/<template_id>/`
contain `template.docx`, `manifest.json`, `style.lock.json`, and a
sample IR payload. DOCX rendering uses named Word styles from the
manifest plus block markers (`{{resume.sections}}`,
`{{cover_letter.body}}`). PDF export prefers Word + `docx2pdf` and
falls back to LibreOffice. File naming is
`{type}_{company}_{role}_{date}.{ext}`; every artifact is versioned.

### Layer 7: Analytics / CRM
Tracking table records source, company, role, date, platform, resume
version, match score, status, outcome, and outcome timestamp. Analytics
dashboard surfaces pipeline / outcome / platform / company breakdowns.
CSV export excludes `error_log` by default.

## 7. Phased Implementation — what has shipped

Test counts are snapshots at the close of each phase. Current
baseline (post-Phase-10): **680 passed, 1 skipped** (`pytest -q`),
`ruff check src/ tests/` clean, `npm run build` clean.

| Phase | Scope | Status | Test snapshot |
|---|---|---|---|
| 1 | Infrastructure + Applicant Memory + Document Pipeline | Complete | — |
| 2 | Job Intake + Smart Filtering | Complete | 156 |
| 3 | Resume / CL Tailoring + QA | Complete | — |
| 4 | Browser Automation + Form Filling | Complete | 156 |
| 5 | CLI + Tracking + Full Pipeline | Complete | 177 |
| 6 | LinkedIn Integration | Complete | 207 |
| 7 | Web GUI (FastAPI + Vue SPA) | Complete | 228 |
| 8 | Materials Workspace + DOCX Template Packages + Hardening | Complete | 340 |
| Agent 8 | Agent Harness (tools / loop / trace / eval / HITL gate) | Complete | — |
| Agent 9 | Form-Filler Agent + cost telemetry + 5-fixture eval | Complete | 553 |
| 10 | LLM Provider Abstraction (REST + subprocess + credential store + Settings UI) | Complete | 669 |

See `docs/CHANGELOG.md` for the per-sub-phase shipping log.

## 8. Roadmap (Phase 11 → 18) — v3.1, calibrated 2026-05-14

v3 corrected four issues from v1/v2 (preserved below); v3.1 further calibrates
v3 in four places (see the top-of-file version note).

The v2/v3 re-plan reflects four corrections to the v1 draft:

1. **PostgreSQL is the source of truth**, not SQLite. The v1 draft
   said "L2 SQLite cache" and "APScheduler + SQLite jobstore"; both
   were errors. The app has always run on Postgres + pgvector +
   alembic. (See D021.)
2. **Redis is adopted from Phase 12** as the cache / lock / queue
   substrate, preserving a commercial deployment path. (See D018.)
3. **Task queues are required for automated runs.** Phase 14 now makes the
   Redis queue + Postgres task-state + worker boundary explicit instead of
   treating background work as a scheduler detail. (See D023.)
4. **Materials generation needs two resume modes.** Phase 15 now covers
   original-resume patching plus LaTeX-first generation rather than only the
   cover-letter agent. (See D024.)

The earlier "JD scrape caching" sub-phase has been promoted to a full
phase (**Phase 13: Job Index & Freshness Engine**) because the
problem is content versioning + freshness state machines + audit
binding, not key-value eviction. (See D019.)

A new **Phase 18: Multi-Tenancy & Auth Hardening** closes the v1
commercial-ready core; every Phase 12-17 table is built with
`tenant_id` from day one. (See D020.)

### Phase 11: Reliability & Cleanup (~1 week)
Tighten the provider layer; ship the migration tool needed for users
upgrading from earlier revisions.
- **11.1** Provider fallback chain in `generate_text` (primary +
  ordered fallbacks; quota / network / auth failure auto-failover;
  attempt chain recorded in trace).
- **11.2** `autoapply migrate` CLI: cleans stale credential
  breadcrumbs, renames legacy settings keys, detects stale credentials.
- **11.3** Docs sync — push everything up to Phase 10 complete state.
- **11.4** Provider health monitor: `/api/providers/health` background
  probe every 5 minutes; Settings page "Last verified" surfaces real
  telemetry.

### Phase 12: Cache Infrastructure (~1.5 weeks)
**First introduction of Redis.** Scope is deliberately narrow — LLM
and embedding responses only. JD / job content caching moves to
Phase 13.
- **12.1** `src/cache/` module — L1 in-process LRU + L2 Redis;
  namespace TTL (`llm:7d`, `embedding:30d`, `response:5m`); unified
  `get/set/invalidate` API; version-stamped keys.
- **12.2** Redis infrastructure — connection pool, health check,
  `REDIS_URL` env var, `docker-compose.yml` service, AOF persistence,
  `autoapply redis ping/flush/info` CLI.
- **12.3** Distributed lock primitive — `with cache.lock(key, ttl)`
  built on Redis `SET NX PX`. Phase 13 force-refresh consumes it.
- **12.4** LLM response caching — `generate_text(cache=True)`;
  agent loops default `cache=False`, deterministic retrieval defaults
  `cache=True`. Cost-saved counter on hit.
- **12.5** Embedding cache — `embed_text(cache=True)` for
  `src/matching/semantic.py` with 30-day TTL.
- **12.6** Cache inspector UI at `/settings/cache`.
- **12.7** Cost dashboard upgrade — Phase 9.4 aggregates split into
  "cached vs fresh" with a $-saved line.

### Phase 13: Job Index & Freshness Engine (~2 weeks)
Replaces the file-backed `src/intake/search_cache.py` with a proper
Job Intelligence Database.
- **13.1** Schema (alembic) — `job_postings`, `job_snapshots`,
  `search_queries`, `search_results`, `refresh_tasks`; add
  `application_records.job_snapshot_id` FK; every new table carries
  `tenant_id`.
- **13.2** Normalization layer — `normalize_search_key()`,
  `normalize_job_content()`, `content_hash()` excluding unstable
  fields.
- **13.3** Freshness state machine in `src/jobs/state.py` —
  `new → active → stale → unknown → expired → archived`.
- **13.4** Search flow — cache-first by default; force-refresh wraps
  scrape in a Phase 12 distributed lock; old cache preserved on
  failure.
- **13.5** Detail enrichment with content versioning — scrape →
  normalize → hash → new `job_snapshot` if `content_hash` changed;
  emit `job.content_changed` event.
- **13.6** Context-aware freshness — `should_refresh(job, context)`
  where context ∈ {`search_display: 72h`, `generate_materials: 24h`,
  `before_submit: 6h`}.
- **13.7** Web UI — "Last updated 18h ago · Refresh"; refresh-success
  banner reports `N new / N expired / N updated`.
- **13.8** Migrate legacy `data/cache/linkedin_search/*.json` into
  `search_queries` + `search_results`; remove the file-cache module.
- **13.9** **tenant_id retrofit migration** (must land before Phase 14 starts;
  see D026). One alembic migration adds
  `tenant_id TEXT NOT NULL DEFAULT 'default'` to every legacy table from Phase
  11 and earlier (`jobs`, `applications`, `applicant_profile`, `bullet_pool`,
  `story_bank`, `qa_bank`, `templates` / `template_packages`, etc.) and
  backfills existing rows; ORM models add the field. Existing query paths
  are not forced to filter (preserving today's global-read behavior), but
  every new Phase-14 code path must thread an explicit tenant context. The
  "default tenant" fallback is replaced by Phase 18 auth middleware + RLS.

### Phase 14: Task Queue + Scheduled Work (~2.5 weeks, Celery-based) — **Complete**

All 10 sub-phases shipped on `feat/phase-14` (commits `83de0db` →
`707d94e`) + two rounds of codex-review fixes folded in (`3de7084`).
Verification baseline: 1161 passed, 1 skipped; `ruff check` clean;
frontend build clean; migrations `e1b4f72c8a05` (tasks audit table) +
`f2c5d83a91b6` (gate_queue) applied to dev DB.

Switches to Celery 5.x (see D025). The originally-planned self-built task
model + queue transport + worker runtime is dropped — Celery owns those.
AutoApply layers a thin "agent boundary + HITL + trace + tenant context"
wrapper on top. D023's principle ("queue owns execution reliability; agents
own bounded decisions") is preserved.

- **14.1** **Celery wiring + project skeleton.** `celery_app = Celery(
  "autoapply", broker=REDIS_URL, backend=REDIS_URL)`,
  `task_acks_late=True`, `task_reject_on_worker_lost=True`,
  `worker_prefetch_multiplier=1` (long-task model). Four queues:
  `search.*` / `materials.*` / `application.*` / `maintenance.*`.
- **14.2** **Durable audit table** (Postgres, source of truth). Celery's
  result backend is transient; AutoApply maintains its own `tasks` table
  (`id, celery_task_id, tenant_id, kind, payload, idempotency_key, status,
  attempts, parent_task_id, trace_id, created_at, finished_at`). Celery
  signals (`task_prerun` / `task_postrun` / `task_failure` / `task_retry`)
  keep it in sync.
- **14.3** **Custom `AutoApplyTask` base class** (subclass of Celery
  `Task`) — provides: (a) reads `tenant_id` from task headers and injects
  it into DB session + Redis namespace; (b) idempotency key check on
  entry (return early if already succeeded); (c) `self.call_agent(...)`
  wrapper that runs one bounded agent per task and dispatches the
  structured return (`success` / `failed_retryable` / `failed_terminal` /
  `needs_human` / `needs_followup_task`) to `raise self.retry()`, gate
  enqueue, or child-task enqueue; (d) writes trace records.
- **14.4** **HITL gate moved to the DB** (replaces single-process file
  JSON; see D026). New table `gate_queue(id, tenant_id, task_id, kind,
  payload, status, requested_at, decided_at, decision, reason)` with
  `pending → approved → rejected`. When a Celery task returns
  `needs_human`, the task row transitions to `waiting_human` and the
  worker is *released immediately* (no blocking). User approval calls
  `/api/gate/{id}/approve` which enqueues a `resume` task under the same
  idempotency key. The old file-backed `src/agent/gate/queue.py` stays as
  a compat layer for one release and is then removed.
- **14.5** **Celery Beat for cron triggers** (replaces APScheduler
  entirely). Beat schedule in `src/tasks/beat.py`: `daily_search`,
  `jd_health_check` (drives 13.3 freshness time decay),
  `application_status_sync`, `linkedin_cookie_refresh`, `cache_eviction`.
  Beat only enqueues; business logic never runs in the Beat process.
  Multi-instance Beat uses `celery-redbeat` or a Postgres advisory lock to
  prevent double-fire.
- **14.6** **Task kinds**: `search.refresh`, `jobs.enrich`,
  `materials.generate`, `application.prepare`, `application.fill`,
  `application.submit`, `status.sync`, each a Celery task built on the
  14.3 base. Payload schemas validated via Pydantic models.
- **14.7** **CLI**: `autoapply worker --queues search,materials,apply
  --concurrency 4` (wraps `celery -A src.tasks worker ...`);
  `autoapply beat`; `autoapply tasks list/retry/cancel/inspect` (reads the
  14.2 audit table); `autoapply schedule list/pause/run-now` (reads Beat
  schedule + enqueues a one-shot task).
- **14.8** **Web UI** `/schedule` + `/tasks` + `/gate`: reads the audit
  table for queue depth, live workers via Celery inspect API, failure
  reasons, manual retry/cancel. `/gate` replaces the legacy agent gate
  viewer.
- **14.9** **Trace integration**: `AutoApplyTask.on_success/on_failure/
  on_retry` auto-write trace records; child task headers carry
  `parent_trace_id` so the trace viewer can walk the parent/child chain.
- **14.10** **Multi-instance safety**: Celery itself guarantees a single
  worker picks up each task; Beat multi-instance uses redbeat leader
  election; Postgres advisory lock as a defense-in-depth backstop (D021's
  principle preserved).

### Phase 15: Resume & Cover Letter Generation v2 (~3 weeks) — **Complete**

All 10 sub-phases shipped on `feat/phase-15` (commits `4e95e98` →
`439d2d7`) + one codex-review P2 fix round (`9b813a3`). Verification
baseline: 1332 passed / 1 skipped; `ruff check` clean; migration
`a3b9d52e7c41` (`source_resumes`) applied to dev DB.

Implementation highlights:

* `src/generation/source_resume.py` -- upload ingest (DOCX / LaTeX / PDF)
* `src/generation/docx_patch.py` -- DOCX patch with named-style preservation
* `src/documents/latex_manifest.py` + `latex_renderer.py` -- manifest-adapter
  rendering on top of the existing `latex_engine.py` (not from scratch)
* `src/generation/materials_router.py` -- `patch_existing` vs
  `generate_from_template` dispatch with provenance bindings
* `src/agent/tools/jd.py` -- the `jd_lookup` agent tool
* `src/generation/agent_cover_letter.py` + `fact_drift.py` -- five-tier
  fallback ladder + numeric-drift blocking
* `src/documents/template_adapter.py` -- propose manifests for
  arbitrary user-uploaded LaTeX templates
* Three eval suites + 7 fixtures
* `src/generation/gate_triggers.py` -- HITL gate only for persistent
  grounding mutations
Benefits from Phase 12 (LLM caching), Phase 13 (snapshot binding), and
Phase 14 (background material tasks).
- **15.1** Source-resume model: uploaded originals stored with type, checksum,
  extracted structure, and editability flag. PDF import feeds fact extraction
  only; no format-preserving PDF edit promise.
- **15.2** DOCX patch mode: localized edits to summary, bullets, skills order,
  and section inclusion while preserving existing styles and layout structures
  where DOCX permits. **Fallback**: when patching fails (missing style, IR
  field unmappable, page overflow after edit), automatically degrade to
  `generate_from_template` and tell the user why in the UI / task result —
  do not let users assume DOCX patch is 100% fidelity-preserving.
- **15.3** LaTeX template package spec. Note that
  `src/documents/latex_engine.py` already provides the compile/render
  primitives (built alongside DOCX template packages in Phase 8). This
  sub-phase *normalizes the template package structure*: `template.tex`,
  assets, `template.manifest.yaml`, sample IR, compile engine choice
  (`pdflatex` / `xelatex` / `lualatex`), capacity / page rules, command /
  field mappings, escape allowlist. The focus is defining manifest schema
  + adapter conventions, not writing a renderer.
- **15.4** LaTeX-first resume generator: agent emits structured resume IR;
  the deterministic renderer (reusing existing `latex_engine.py`) escapes,
  maps via the manifest, compiles, and validates page/capacity. Refactors
  the LaTeX branch in `resume_builder.py` from "custom IR direct dispatch"
  to "manifest-adapter dispatch."
- **15.5** Materials router: `patch_existing` vs `generate_from_template`,
  both running as `materials.generate` tasks and binding outputs to
  `job_snapshot_id`, source/template ID, profile version, and trace ID.
- **15.6** Shared `jd_lookup` tool for resume and cover-letter agents.
- **15.7** `AgentCoverLetter` orchestrator emits cover-letter IR with evidence
  citations; existing fact-drift checker as post-guard; deterministic fallback
  on agent failure.
- **15.8** Template adapter assistant: agent may propose a manifest for a new
  arbitrary LaTeX template, but persistence requires sample compile + user
  confirmation.
- **15.9** Eval suite covers DOCX patch fixtures, LaTeX template fixtures, and
  cover-letter fixtures.
- **15.10** HITL gate fires on bullet/story-bank mutation or persistent
  template-adapter creation, not on ordinary generation.

### Phase 16: Filter Agent + Explainability (~1.5 weeks) — **Complete**

All 4 sub-phases shipped on `feat/phase-16` (commits `203becb` →
`9198a3b`) + one codex-review P2 fix (`5702da7`). Verification
baseline: 1398 passed / 1 skipped; `ruff check` clean; frontend
build clean.

Implementation highlights:

* `src/matching/rules.py` -- structured `RuleResult` fields with
  bounded JD excerpt extraction per hard rule
* `src/matching/scorer.py` -- `ScoreBreakdown.job_snapshot_id` +
  `disqualify_results` + `to_dict()`
* `src/agent/tools/score_breakdown.py` -- read-only dotted-path
  tool bound to one breakdown
* `src/matching/edge_case_agent.py` -- fires only on
  `0.4 <= score <= 0.6` with fail-closed fallback ladder; never
  overrides hard rules
* `src/application/matching.py` + `POST /api/matching/explain` --
  on-demand re-score endpoint for the popover
* `frontend/src/views/JobsView.vue` -- "Why was this filtered?"
  Dialog popover on every disqualified job card
* `tests/agent_evals/fixtures/filter_borderline/` -- 10 fixtures
  covering the full decision matrix

(Original plan retained below for the design rationale.)
Not a replacement for the deterministic filter — an explainability
layer + agent invocation for borderline jobs only.
- **16.1** **`RuleVerdict` schema evolution** (this is a schema change, not
  just "add a layer"). Today, `src/matching/scorer.py`'s
  `ScoreBreakdown.disqualify_reasons` is only a `list[str]` and
  `RuleVerdict` carries no `evidence_excerpt` or `rule_id` structure.
  This sub-phase: (a) restructures `RuleVerdict` into `{rule_id,
  rule_name, verdict, reason, evidence_excerpt}`; (b) each rule
  implementation in `src/matching/rules.py` actively extracts the
  relevant JD snippet as `evidence_excerpt`; (c) adds `job_snapshot_id`
  to `ScoreBreakdown` so the whole result can be pinned to a specific
  JD version. 16.3's UI consumes this structure directly.
- **16.2** Edge-case agent — invoked only for scores ∈ [0.4, 0.6];
  uses Phase 8 harness + new `score_breakdown` tool.
- **16.3** Web UI "Why was this filtered?" affordance.
- **16.4** Eval suite — 10 human-annotated borderline jobs; agent
  decision matches human ≥ 70%.

### Phase 17: Daily Run Loop + Review Queue (~2 weeks)
Integration phase. Threads Phase 14 (task queue + scheduler) + Phase 13
(job-index / freshness) + Phase 12 (cache) + Phase 9 / 15 (agents)
into the "sleep, wake to a review queue" end-to-end flow.
- **17.1** `nightly_run` orchestrator — search (cache-first, refresh
  stale) → filter (with 16's explainability) → top-N → enqueue
  `materials.generate` and `application.prepare`; workers run agents under
  task-level retry/timeout policy. **Never auto-submits.**
- **17.2** Review queue model — `review_queue(id, tenant_id, job_id,
  job_snapshot_id, materials_path, status, ...)`; state machine
  `pending → approved → submitted` or `pending → rejected`.
- **17.3** `/review` kanban UI.
- **17.4** Bulk operations — multi-select approve, bulk-reject by
  company / keyword.
- **17.5** Pre-submit hard gate — re-run
  `should_refresh(job, "before_submit")`; refresh if > 6h stale;
  block on expired jobs entirely.
- **17.6** Morning digest at 08:00.
- **17.7** `autoapply pause-nightly` kill switch.

### Phase 18: Multi-Tenancy & Auth Hardening (~2.5 weeks)
Activates the commercial-readiness work seeded across 12-17. SaaS
business layer (billing, sign-up flow, marketing site) is NOT in
scope — this phase only makes the existing system safe to host for
multiple isolated users.

**Honest scope**: Phase 13.9 already lands the schema-level `tenant_id`
column on every table, so the "add column + backfill" portion is genuinely
"activate existing work." But the following sub-phases are **net-new
construction**, not retrofit: 18.2 auth middleware (`src/web/` has no
auth layer today), 18.4 Redis namespace refactor (keys today are
`{version}:{namespace}:{key}` with no tenant prefix — every wrapper
needs to change), and 18.7 credential store (`src/providers/store.py`
is a single global JSON file today; needs per-tenant directory split +
keyring entry renaming). 18.1 / 18.3 / 18.5 / 18.6 are the only true
"activations."

- **18.1** `tenants` + `users` tables; bind the `tenant_id='default'`
  rows that 13.9 left behind to real tenants.
- **18.2** **Build from scratch** the FastAPI auth middleware —
  session/token parsing, `current_tenant_id` injected into a
  `ContextVar`; ORM sessions auto-filter via SQLAlchemy events; Celery
  task headers carry tenant context (14.3 reserves the hook).
- **18.3** Postgres Row-Level Security policies — DB-level backstop
  that catches any ORM bypass.
- **18.4** **Refactor** Redis key naming — every namespace now prefixed
  `tenant:{id}:`; `src/cache/base.py` key construction requires an
  explicit tenant context (raises rather than falling back to default).
- **18.5** Per-tenant quotas (LLM tokens, scrape rate, storage).
  Exceeding returns 429.
- **18.6** Audit log table — `audit_events` (submission, settings
  change, credential operation, manual schedule trigger). Append-only.
- **18.7** **Refactor** credential store — `src/providers/store.py`
  moves from one global JSON file to
  `data/tenants/{id}/credentials/`; keyring entries get tenant prefixes;
  migrate existing `data/providers/credentials.json` into the `default`
  tenant.

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
namespace / credential store are net-new builds.

## 9. Cross-cutting Quality Bars

Enforced from Phase 11 onward:

- **Tests** — no PR can drop the suite below the current 680 passing.
- **Lint** — `ruff check src/ tests/` stays clean.
- **Codex review per sub-phase** — `codex review --uncommitted` pass
  before commit; P1 findings block merge.
- **Cost ceiling** — any eval suite that pushes total cost above
  $1.00 / 100 cases needs explicit justification.
- **Docs sync** — `docs/PROJECT_MANAGEMENT.md` + `docs/CHANGELOG.md`
  updated at the end of every Phase, not in a batch later.
- **Multi-tenancy hygiene** (Phase 12+) — every new table carries
  `tenant_id`; every new Redis key is prefixed; every new background
  task accepts a tenant context. No exceptions, or Phase 18 turns
  into a rewrite.

## 10. Verification Checklist (per-phase smoke)

| Phase | Smoke command / observable |
|---|---|
| 1 | Load profile YAML → ingest to DB → generate one tailored Word resume + PDF |
| 2 | Scrape jobs from Greenhouse → score & rank → output top-N |
| 3 | Given a JD → auto-select bullets → tailored resume + CL + answer quick questions |
| 4 | For a Greenhouse job → auto-fill form → upload files → screenshot (no submit) |
| 5 | Run pipeline on 10 jobs → view tracking dashboard → analytics report |
| 6 | LinkedIn search → external ATS link resolution → existing apply / material pipeline |
| 7 | `autoapply web` → Vue SPA search / tracking / settings workflow |
| 8 | `/jobs` → `/materials?jobId=...` → DOCX/PDF generation, preview, validation, download |
| Agent 8 | `autoapply eval --suite agent_smoke` → all cases pass |
| Agent 9 | `autoapply eval --suite form_filler --min-pass-rate 0.85` → 5/5 pass, est. cost ≤ $0.25 |
| 10 | Settings page → connect / test / disconnect each provider; `autoapply provider test <name>` reports auth state accurately |
| 11 | Revoke primary provider mid-run → fallback chain kicks in → eval still passes; `autoapply migrate` cleans legacy state |
| 12 | Re-run same batch → LLM cache hit-rate > 80%, wall time < 20%, cost < 5%; Redis restart preserves L2 entries |
| 13 | Second visit to same search condition < 2s (no HTTP); job content change produces a new `job_snapshot`; revoke LinkedIn cookie → cached results still served |
| 13.9 | `alembic upgrade` → every legacy table carries `tenant_id='default'`; existing query paths unchanged (no regression) |
| 14 | `autoapply worker -Q materials` starts a Celery worker; 100 mixed tasks enqueue → routed by queue; kill a worker → `task_acks_late + task_reject_on_worker_lost` auto-requeues once; Celery Beat fires `daily_search` and only enqueues; agent returning `needs_human` transitions the task to `waiting_human` and the worker immediately picks up the next task |
| 15 | DOCX patch preserves named styles; three LaTeX templates compile from the same IR; cover-letter eval 5/5 pass; artifacts bind snapshot/source/template/trace IDs |
| 16 | Any rejected job in JobsView surfaces a reason chain in < 5s; agent cost < $0.50 per 100 jobs |
| 17 | Schedule nightly run Monday 23:00 → wake Tuesday 08:00 to N pre-tailored applications in review queue, each approvable in < 30s |
| 18 | Two tenants seeded with overlapping email / LinkedIn cookies → cannot read each other's jobs / snapshots / applications / credentials / Redis keys (verified by direct SQL and direct Redis CLI); quota exhaustion returns 429 |

## 11. Risk & Open Questions

- **LinkedIn rate-limiting / detection.** Mitigated by persistent
  context cookies, randomized delays, controlled concurrency, and
  the Phase 13 distributed-lock-gated force-refresh. Still a real
  risk for any aggressive nightly schedule.
- **LLM cost drift.** Mitigated by the Phase 12 cache + the Phase 11
  fallback chain (cheap models in the fallback slot) + the eval
  $1 / 100 ceiling. Cost telemetry (Phase 9.4) is the early-warning.
- **Task execution is still synchronous today.** Until Phase 14 lands,
  long-running search, generation, and apply work can still block CLI/web
  flows and manual retries remain operationally expensive.
- **Arbitrary LaTeX is not zero-config.** Phase 15 will accept arbitrary
  templates only after a manifest/adapter exists and sample compile passes.
  A fully automatic import may still need user correction.
- **Single-instance assumption today.** Phase 14 + D018/D023 plant the
  multi-instance work. Phase 18 makes it real. Until then, do not
  run two `autoapply web` processes against the same Postgres /
  Redis — the data layer permits it but the absence of advisory
  locks invites double-submission races.
- **Auto-submit safety.** `--auto-submit` exists in `apply`, but
  still routes through the HITL gate. We have not yet seen the eval
  data that would justify removing the gate even per-vendor.
- **No SaaS business layer.** Phase 18 is multi-tenant hosting
  infra, not billing / signup / marketing. That work is out of
  scope until / unless a commercial license customer signs.
