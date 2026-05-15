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

Last refreshed: **2026-05-14 (roadmap v3)**.

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
| Scheduler / task execution (Phase 14+) | APScheduler + Postgres `SQLAlchemyJobStore` + Redis queue transport + worker process | See D021 and D023 (not SQLite, not OS cron; Celery/RQ deferred) |
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

Plus a new `application_records.job_snapshot_id` FK that pins every
generated artifact to the exact JD content it was produced against.
Every Phase-12+ table carries a `tenant_id` column (default `"default"`
until Phase 18) — see D020.

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

## 8. Roadmap (Phase 11 → 18) — v3, re-planned 2026-05-14

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

### Phase 14: Task Queue + Scheduled Work (~2 weeks)
- **14.1** Durable task model in Postgres: status, tenant, payload schema,
  idempotency key, attempts, heartbeat, parent/child links, next-run time.
- **14.2** Redis-backed queue transport: ready task IDs by priority;
  workers claim, heartbeat, ack/nack, and requeue abandoned work.
- **14.3** Worker runtime: `autoapply worker`, per-kind concurrency limits,
  graceful shutdown, timeout and retry/backoff policy.
- **14.4** Agent boundary: workers call bounded agents for one task; agents
  return structured outcomes and can enqueue child work only through an
  allow-listed tool.
- **14.5** APScheduler + Postgres `SQLAlchemyJobStore` (NOT SQLite, see
  D021); scheduled jobs enqueue task records instead of running long work
  inline.
- **14.6** CLI: `autoapply schedule ...`, `autoapply tasks ...`, and
  `autoapply worker --queues ...`.
- **14.7** Web UI `/schedule` + `/tasks` with queue depth, workers, retries,
  failure reasons, manual retry/cancel.
- **14.8** Multi-instance safety via Postgres advisory locks for scheduled
  triggers and task-claim invariants for workers.
- **14.9** Trace integration: every task attempt emits a trace and child
  tasks link back to the parent.

### Phase 15: Resume & Cover Letter Generation v2 (~3 weeks)
Benefits from Phase 12 (LLM caching), Phase 13 (snapshot binding), and
Phase 14 (background material tasks).
- **15.1** Source-resume model: uploaded originals stored with type, checksum,
  extracted structure, and editability flag. PDF import feeds fact extraction
  only; no format-preserving PDF edit promise.
- **15.2** DOCX patch mode: localized edits to summary, bullets, skills order,
  and section inclusion while preserving existing styles and layout structures
  where DOCX permits.
- **15.3** LaTeX template packages: `template.tex`, assets,
  `template.manifest.yaml`, sample IR, compile engine, capacity/page rules,
  and command/field mappings.
- **15.4** LaTeX-first resume generator: agent emits structured resume IR;
  deterministic renderer escapes content, maps through the manifest, compiles,
  and validates page/capacity constraints.
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

### Phase 16: Filter Agent + Explainability (~1.5 weeks)
Not a replacement for the deterministic filter — an explainability
layer + agent invocation for borderline jobs only.
- **16.1** Filter reason chain in `src/matching/` — each reject
  records `{rule_id, rule_name, reason, evidence_excerpt,
  job_snapshot_id}`.
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

### Phase 18: Multi-Tenancy & Auth Hardening (~2 weeks)
Activates the commercial-readiness work seeded across 12-17. SaaS
business layer (billing, sign-up flow, marketing site) is NOT in
scope — this phase only makes the existing system safe to host for
multiple isolated users.
- **18.1** `tenants` + `users` tables; migrate existing data to
  `tenant_id="default"`.
- **18.2** FastAPI auth middleware — derive `current_tenant_id` per
  request; every query / Redis namespace / cache key / refresh-task
  selector filters by it automatically.
- **18.3** Postgres Row-Level Security policies (DB-level backstop).
- **18.4** Per-tenant Redis namespace — `tenant:{id}:llm:...`.
- **18.5** Per-tenant quotas (LLM tokens, scrape rate, storage).
  Exceeding returns 429.
- **18.6** Audit log table — `audit_events` (submission, settings
  change, credential operation, manual schedule trigger). Append-only.
- **18.7** Credential store per-tenant.

### Timeline summary

| Phase | Scope | Est. | Cumulative |
|-------|-------|------|------------|
| 11 | Reliability & Cleanup | 1w | 1w |
| 12 | Cache Infrastructure (Redis) | 1.5w | 2.5w |
| 13 | Job Index & Freshness Engine | 2w | 4.5w |
| 14 | Task Queue + Scheduled Work | 2w | 6.5w |
| 15 | Resume & Cover Letter Generation v2 | 3w | 9.5w |
| 16 | Filter Agent + Explainability | 1.5w | 11w |
| 17 | Daily Run Loop + Review Queue | 2w | 13w |
| 18 | Multi-Tenancy & Auth Hardening | 2w | 15w |

~3-3.5 months to v1.0 commercial-ready core (no SaaS business layer).

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
| 14 | Enqueue 100 mixed tasks → workers respect concurrency; kill a worker mid-task → heartbeat expiry requeues once; scheduler tick enqueues instead of blocking |
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
