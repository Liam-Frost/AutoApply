# AutoApply

An AI-powered agent that automates the entire job application process — from job discovery to submission tracking. Provider-agnostic LLM layer (OpenAI / Anthropic / Gemini / Claude CLI / Codex CLI), human-in-the-loop on every submit, fully auditable trace.

> **License**: [PolyForm Noncommercial 1.0.0](LICENSE). Personal / academic / nonprofit use is free. Commercial use requires a separate license — see [Commercial Use](#commercial-use).

## Docs

- [Deployment Guide (EN)](docs/DEPLOYMENT.md)
- [部署与使用教程（中文）](docs/DEPLOYMENT_zh.md)
- [Implementation Plan (EN)](docs/plan_en.md)
- [实施计划（中文）](docs/plan_zh.md)
- [Agent Architecture](docs/AGENT_ARCHITECTURE.md)
- [Changelog](docs/CHANGELOG.md)
- [Architecture Decisions](docs/DECISIONS.md)
- [Project Management](docs/PROJECT_MANAGEMENT.md)

## What It Does

- **Job Intake**: Scrape and standardize job postings from Greenhouse, Lever, Ashby, and LinkedIn-discovered external ATS links
- **Smart Filtering**: Three-tier scoring (hard rules + semantic matching + risk filtering) to only target high-fit positions
- **Applicant Memory**: Structured knowledge base of your education, projects, skills, stories, and Q&A templates
- **Materials Workspace**: Web workflow for selecting a job/JD, applicant profile, templates, formats, preview, and downloads
- **Tailored Materials**: DOCX-first resume and cover letter generation from structured IR — no full-text LLM hallucination
- **Quick Question Answering**: Auto-answer common application questions with confidence-based routing and human review flags
- **Form Automation**: Playwright-driven form filling with state machine recovery, screenshots, and human confirmation before submit
- **Document Pipeline**: Template packages (`template.docx` + manifest/style lock), deterministic rendering, PDF export, validation, and version tracking
- **Application Tracking**: Full CRM with analytics on hit rates, platform quality, and resume version effectiveness
- **Provider-Agnostic LLM Layer**: Plug in OpenAI / Anthropic / Gemini (REST) or Claude CLI / Codex CLI (subprocess) interchangeably. Credentials stored at `0600` with OS-keyring fallback; primary + fallback chain configurable per call site
- **Agent Mode** (form-filler today, cover-letter & filter next): allow-listed tool registry, bounded ReAct loop, file-backed HITL approval gate, fixture-driven eval harness, per-step cost / latency telemetry

## Architecture

7-layer modular system:

```
Layer 1: Job Intake          — Scrape & standardize JDs
Layer 2: Matching & Filtering — Rule + semantic + risk scoring
Layer 3: Applicant Memory     — Structured profile & knowledge base
Layer 4: Generation           — Resume/CL tailoring & QA
Layer 5: Execution            — Browser automation & form filling
Layer 6: File Pipeline        — DOCX templates, PDF export, validation & versioning
Layer 7: Analytics            — Tracking, statistics & optimization
```

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| Frontend | Vue 3 + Vue Router + Vite + Tailwind v3 + shadcn-vue + reka-ui |
| Web Backend | FastAPI JSON API |
| Browser Automation | Playwright |
| LLM Providers | OpenAI / Anthropic / Gemini (REST via httpx) **or** Claude Code CLI / Codex CLI (subprocess) — interchangeable through `ProviderRegistry` |
| Agent Harness | In-house ReAct loop with allow-listed `ToolRegistry`, file-backed HITL gate, JSON-on-disk trace store, fixture-driven eval runner |
| Database | PostgreSQL + pgvector |
| Cache / Lock / Queue | Redis (from Phase 12) — L2 cache, distributed locks, task substrate |
| Document Processing | python-docx, docx2pdf / LibreOffice |
| Package Manager | uv + npm |
| Target Platforms | Greenhouse, Lever, Ashby, LinkedIn discovery |

## Project Structure

```
frontend/            # Vue frontend source and build config
src/
├── application/   # Shared use cases for CLI and Web
├── core/          # Orchestration & state machine
├── intake/        # Job scraping & schema
├── matching/      # Filtering & scoring
├── memory/        # Applicant profile, story bank, QA bank, bullet pool
├── generation/    # Resume/cover IR, fitting, validation, QA responder
├── execution/     # Playwright browser, form filler, ATS adapters
├── documents/     # DOCX/PDF engine, template packages, page count helpers
├── tracker/       # Database, analytics, export
├── providers/     # LLM provider abstraction: OpenAI / Anthropic / Gemini REST
│                  # adapters + Claude CLI / Codex CLI subprocess providers,
│                  # credential store, registry, dispatch bridge
├── agent/         # In-house agent harness:
│   ├── tools/     #   tool ABC + builtin / browser / profile tools
│   ├── core/      #   ReAct loop, cost telemetry
│   ├── trace/     #   JSON-on-disk trace store
│   ├── eval/      #   fixture-driven eval runner + scorers
│   └── gate/      #   file-backed HITL approval queue
├── cli/           # `autoapply` Click CLI (search, apply, status,
│                  #   provider, eval)
├── utils/         # LLM dispatch wrapper, rate limiter, logger
└── web/           # FastAPI API + built SPA assets
```

## Current Status

### Shipped

- **Phase 1** (Infrastructure + Applicant Memory + Document Processing) — Complete
- **Phase 2** (Job Intake + Smart Filtering) — Complete
- **Phase 3** (Resume/CL Tailoring + QA) — Complete
- **Phase 4** (Browser Automation + Form Filling) — Complete
- **Phase 5** (CLI + Tracking + Full Pipeline) — Complete
- **Phase 6** (LinkedIn Integration) — Complete
- **Phase 7** (Web GUI) — Complete
- **Phase 8** (Materials Workspace + DOCX Template Packages + Hardening) — Complete
- **Agent Phase 8** (Agent Harness: tools / loop / trace / eval / HITL gate) — Complete
- **Agent Phase 9** (Form-Filler Agent with HITL review + eval suite + cost telemetry) — Complete
- **Phase 10** (LLM Provider Abstraction: REST adapters for OpenAI / Anthropic / Gemini + subprocess providers for Claude CLI / Codex CLI; credential store; `autoapply provider` CLI; `/settings` provider management UI) — Complete
- **Phase 11** (Reliability & Cleanup: ordered provider fallback chain with `ProviderErrorKind` classification, `autoapply migrate` upgrade CLI, background `/api/providers/health` monitor with live "Last verified" telemetry, writer-side list+scalar sync for `fallback_providers`) — Complete

**727 tests passing**, 1 skipped. `ruff` clean. Frontend builds clean. See [CHANGELOG](docs/CHANGELOG.md) and [AGENT_ARCHITECTURE.md](docs/AGENT_ARCHITECTURE.md) for details.

### Roadmap (Phase 11 → 18)

Re-planned 2026-05-12 (v2). Redis is adopted from Phase 12 as cache / lock / queue substrate; JD caching graduates into a dedicated Job Index & Freshness Engine (Phase 13) with content-hashed snapshots and audit binding from generated materials back to the exact JD version they were built from; a new Phase 18 plants the multi-tenancy seeds for a future commercial deployment. See [DECISIONS.md](docs/DECISIONS.md) D018-D021 for rationale.

| Phase | Scope | Est. |
|---|---|---|
| 11 | Reliability & Cleanup — provider fallback chain, `autoapply migrate`, provider health monitor, docs sync — **Complete** | ~1 week |
| 12 | Cache Infrastructure (Redis) — `src/cache/` L1 LRU + L2 Redis, distributed lock primitive, LLM + embedding response caching, inspector UI, cost-saved dashboard | ~1.5 weeks |
| 13 | Job Index & Freshness Engine — `job_postings` / `job_snapshots` / `search_queries` / `search_results` / `refresh_tasks` tables, content-hash versioning, freshness state machine, cache-first search + force-refresh UX, audit binding via `job_snapshot_id` | ~2 weeks |
| 14 | Scheduled Task System — APScheduler + Postgres jobstore, RefreshTask worker, built-in jobs (`daily_search`, `jd_health_check`, `status_sync`, `cookie_refresh`, `cache_eviction`), multi-instance safe | ~1.5 weeks |
| 15 | Cover-letter Agent — `jd_lookup` tool, `AgentCoverLetter` orchestrator, snapshot-bound generation, fact-drift guard, 5-fixture eval suite (was originally Phase 10) | ~2 weeks |
| 16 | Filter Agent + Explainability — reason chain in `src/matching/`, edge-case agent for borderline scores, "Why was this filtered?" UI | ~1.5 weeks |
| 17 | Daily Run Loop + Review Queue — `nightly_run` orchestrator, `/review` kanban, bulk operations, pre-submit freshness gate, morning digest, kill switch | ~2 weeks |
| 18 | Multi-Tenancy & Auth Hardening — `tenants` / `users` tables, FastAPI auth middleware, Postgres RLS, per-tenant Redis namespace, quotas, audit log | ~2 weeks |

~3 months to v1.0 commercial-ready core. See [PROJECT_MANAGEMENT.md](docs/PROJECT_MANAGEMENT.md) for the full sub-phase breakdown and per-phase verification commands.

## CLI Usage

```bash
# First-time setup
autoapply init

# Search for matching jobs
autoapply search --profile default --score

# Search with machine-readable output
autoapply search --profile default --score --json

# Search LinkedIn with authenticated enrichment
autoapply search --source linkedin --keyword "software engineer intern" --location "Canada" --max-pages 3

# Apply to a single job
autoapply apply --url https://boards.greenhouse.io/company/jobs/123

# Apply with machine-readable output
autoapply apply --url https://boards.greenhouse.io/company/jobs/123 --json

# Batch apply to top matches
autoapply apply --batch --top-n 5

# View tracking dashboard
autoapply status

# Export applications to CSV
autoapply status --export-csv report.csv

# Inspect tracking data as JSON
autoapply status --json

# Run agent regression evals (form_filler suite, gated at 85% pass)
autoapply eval --suite form_filler --min-pass-rate 0.85

# List available eval suites
autoapply eval --list

# Manage LLM providers (Phase 10)
autoapply provider list                          # show all providers + auth state
autoapply provider set-key openai sk-...         # store API key (file 0600 + keyring fallback)
autoapply provider test openai                   # deep round-trip test, not just key presence
autoapply provider set-primary anthropic         # which provider gets called by generate_text
autoapply provider set-fallback openai           # provider chain (Phase 11.1 fail-over: transient errors advance, BAD_REQUEST/PARSE stop)
autoapply migrate                                # Phase 11.2: one-shot upgrade tool; --apply writes a .bak before fixing legacy settings.yaml / credential rows
autoapply provider disconnect openai             # remove stored credential
```

## Agent Mode

The form-filler can run in agent mode (Phase 9). Tool access is
allow-listed, all proposals go through a confidence-threshold review,
and submit always requires human approval through the gate at
`/api/agent/viewer` (web GUI). Per-step token + cost telemetry is
recorded into the trace.

See [docs/AGENT_ARCHITECTURE.md](docs/AGENT_ARCHITECTURE.md) for the
HITL contract, layering, and eval workflow. Cost rates are
configurable via `AUTOAPPLY_AGENT_COST_PROMPT_PER_1K` /
`AUTOAPPLY_AGENT_COST_OUTPUT_PER_1K` env vars.

The deterministic `form_filler.py` remains the default; agent mode is
opted in via `AgentFormFiller` / `run_agent_form_fill(...)` from
`src.execution.agent_form_filler`.

CLI is the agent-facing control plane and now supports structured `--json` output for the core `search`, `apply`, and `status` commands. The Web GUI remains the human-facing control plane.

## Web Usage

```bash
uv run autoapply web --host 127.0.0.1 --port 8000
```

Primary routes:

- `/jobs` searches ATS/LinkedIn jobs and links each result to the Materials workflow
- `/materials` generates resumes and cover letters from search results or pasted JDs
- `/applications` tracks outcomes and pipeline status
- `/profile` manages applicant profile data
- `/settings` manages LLM providers (connect / test / set-primary / set-fallback / disconnect for OpenAI, Anthropic, Gemini, Claude CLI, Codex CLI), LinkedIn session, and search-cache settings
- `/api/agent/viewer` agent trace viewer + HITL approval queue (read traces, approve/reject pending submits)

The Materials page is the main human-in-the-loop generation workflow: select a job or paste a JD, choose an applicant profile, select resume/cover letter templates and formats, generate, preview, then download DOCX/PDF artifacts.

## Getting Started

> Start here: [Deployment Guide (EN)](docs/DEPLOYMENT.md) | [部署与使用教程（中文）](docs/DEPLOYMENT_zh.md)

### Prerequisites

- Python 3.12+
- PostgreSQL 16+ with pgvector extension
- **At least one LLM provider** — any of:
  - **API key**: OpenAI / Anthropic / Gemini (configured via `autoapply provider set-key <name> <key>` or the `/settings` page)
  - **CLI**: Claude Code CLI (`npm install -g @anthropic-ai/claude-code`) or Codex CLI (`npm install -g @openai/codex`) — auth managed by the CLI itself via `claude login` / `codex login`
- uv package manager
- Node.js and npm only if you plan to rebuild the frontend assets locally

### Setup

```bash
# Clone
git clone https://github.com/Liam-Frost/AutoApply.git
cd AutoApply

# Install dependencies
uv sync

# Install frontend dependencies
cd frontend
npm install
npm run build
cd ..

# Install Playwright browser
uv run playwright install chromium

# Configure
cp config/.env.example .env
# Edit .env with your settings

# Setup database
alembic upgrade head

# Pick at least one LLM provider:

#   --- Option A: API key (no CLI install needed) ---
uv run autoapply provider set-key openai sk-...
uv run autoapply provider set-primary openai
uv run autoapply provider test openai

#   --- Option B: Use a local CLI (auth lives in the CLI) ---
# npm install -g @anthropic-ai/claude-code   # then `claude login`
# npm install -g @openai/codex               # then `codex login`
uv run autoapply provider set-primary claude-cli   # or codex-cli
uv run autoapply provider test claude-cli

# First-time setup wizard (interactive; configures profile, provider, settings)
uv run autoapply init
```

The committed repo includes built frontend assets under `src/web/static/spa`, so rebuilding the Vue app is mainly needed when you change files under `frontend/`.

## Design Principles

1. **State machine-driven** — Every application is interruptible, resumable, auditable
2. **Block-based resume** — Select from bullet pool + light rewrite, no full-text LLM hallucination
3. **DOCX-first rendering** — LLM/content planning produces structured IR; deterministic renderers own final DOCX/PDF output
4. **Human-in-the-loop** — Default pause before submit; auto-submit only under validated conditions
5. **Full audit trail** — Screenshots, DOM snapshots, file versions, QA responses all recorded

## License

AutoApply is released under the **[PolyForm Noncommercial License 1.0.0](LICENSE)**.

### What this means

| | Allowed | Requires Commercial License |
|---|---|---|
| Run AutoApply to apply for **your own** jobs | ✅ | |
| Personal experimentation, learning, hobby use | ✅ | |
| Academic research, coursework, thesis projects | ✅ | |
| Use by a registered nonprofit / public-research org / educational institution | ✅ | |
| Open-source forks for noncommercial experimentation | ✅ | |
| Read, modify, and redistribute the source code (noncommercial) | ✅ | |
| Run AutoApply as a **paid service** for other job seekers | | ❌ |
| Bundle AutoApply (in whole or in part) into a **commercial product** | | ❌ |
| Use AutoApply inside a **for-profit company's** workflow (e.g., a recruiting service) | | ❌ |
| Sell **support, hosting, or modifications** based on AutoApply | | ❌ |

### Commercial Use

Commercial use is **not** granted under the default license. If your use case falls on the right column of the table — or you're unsure — please contact the author to negotiate a separate commercial license:

- **Email**: <frostnova986@gmail.com>
- **GitHub**: <https://github.com/Liam-Frost/AutoApply>

When you reach out, please briefly describe (a) your organization, (b) the intended use case, and (c) expected scale. I'll respond with terms.

### Required Notice

> Required Notice: Copyright (c) 2026 Liam Frost (frostnova986@gmail.com)

This notice must be preserved in any redistribution of the software, in source or binary form.

### Warranty disclaimer

The software is provided **as-is**, without any warranty. See the [full LICENSE text](LICENSE) for the legally binding terms.
