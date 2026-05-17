# Phase History

This file is the compact archive of shipped AutoApply phases. It preserves project history without making the README carry implementation detail. For implementation-level bullets, migrations, tests, and review fixes, use [CHANGELOG.md](CHANGELOG.md). For rationale, use [DECISIONS.md](DECISIONS.md).

## Shipped Milestones

| Phase | Product Area | Summary |
|---|---|---|
| 1 | Infrastructure, applicant memory, document processing | Established the Python project, database/config foundation, structured applicant profile, resume import, bullet/story/QA memory, DOCX generation, PDF conversion, and file versioning. |
| 2 | Job intake and smart filtering | Added ATS job schemas, Greenhouse/Lever intake, JD parsing, search CLI, hard filters, semantic matching, composite scoring, and low-quality job filtering. |
| 3 | Resume and cover-letter tailoring | Added JD keyword extraction, bullet selection, lexical rewrite, fact-drift checks, cover-letter generation, company research, and quick-answer generation. |
| 4 | Browser automation and form filling | Added Playwright browser management, application state machine, form field detection, field filling, file upload, ATS adapters, screenshots, and rate limiting. |
| 5 | CLI, tracking, full pipeline | Added the `autoapply` CLI, setup wizard, application CRUD/status/outcome tracking, analytics, CSV export, and end-to-end apply/status flows. |
| 6 | LinkedIn integration | Added authenticated LinkedIn session handling, job search scraping, detail extraction, ATS redirect detection, and LinkedIn-to-application pipeline integration. |
| 7 | Web GUI | Replaced the older server-rendered dashboard with a Vue SPA and FastAPI JSON API for dashboard, jobs, applications, profile, and settings. |
| 8 | Materials workspace and template packages | Added the `/materials` workflow, DOCX template packages, manifests, style locks, validation, deterministic rendering, artifact preview/download, and API hardening. |
| UI Phase 9 | SPA design system overhaul | Migrated the frontend to Tailwind, shadcn-style Vue components, reka-ui primitives, Lucide icons, light/dark tokens, shared empty states, and cleaner view shells. |
| Agent Phase 8 | Agent harness foundations | Added the tool abstraction, allow-listed ToolRegistry, bounded ReAct loop, JSON trace store, eval runner, and HITL approval queue. |
| Agent Phase 9 | Form-filler agent | Added browser/profile tools, AgentFormFiller orchestration, proposal review, deterministic fallback, eval fixtures, and cost/latency telemetry. |
| 10 | LLM provider abstraction | Added OpenAI, Anthropic, Gemini, Claude CLI, and Codex CLI behind a provider registry with credential storage, provider CLI, and Settings UI management. |
| 11 | Reliability and cleanup | Added provider fallback chains, error classification, upgrade/migration cleanup CLI, provider health monitor, and fallback settings synchronization. |
| 12 | Cache infrastructure | Added Redis-backed L1/L2 cache, namespace TTL policy, distributed locks, LLM/embedding response caching, cache inspector UI, Redis CLI, and cache-aware cost telemetry. |
| 13 | Job Index and freshness engine | Added normalized job postings, immutable snapshots, search queries/results, refresh tasks, content-hash versioning, freshness state machine, cached search, enrichment, and legacy cache import. |
| 13.9 | Tenant retrofit | Added `tenant_id='default'` to legacy tables so later multi-tenancy hardening has a schema-level foundation. |
| 14 | Task queue and scheduled work | Added Celery, Redis broker, named queues, task audit table, AutoApplyTask base, Postgres HITL gate, Beat schedule, task CLI, schedule CLI, `/tasks` API/UI, traces, advisory locks, and cancellation semantics. |
| 15 | Resume and cover-letter generation v2 | Added source document ingestion, DOCX patch mode, LaTeX template manifests, manifest renderer, materials router, JD lookup tool, AgentCoverLetter, fact-drift guard, eval suites, and gate triggers for persistent grounding changes. |
| 16 | Filter agent and explainability | Added structured rule evidence, score breakdowns, score-breakdown tool, borderline EdgeCaseAgent, matching explanation API, rejected-job UI explanations, and filter-borderline eval suite. |
| 17 | Plan runs and review queue | Added `plan_run` orchestration, review queue state machine, review kanban, bulk actions, pre-submit freshness gate, morning digest, pause/resume plan-run kill switch, and application submission approval flow. |
| 17.8 | Material strategy and document library | Added `user_documents`, document upload/download/promote APIs, profile-from-library flow, material defaults, per-plan material overrides, replace-materials actions, and library/template tabs in the Materials workspace. |

## Current Product Baseline

The current baseline is a local-first automation product with a web console, durable Postgres records, Redis/Celery background execution, explicit review before submit, user-curated document library, and provider-agnostic LLM support.

The next planned milestone is Phase 18: Multi-Tenancy & Auth Hardening.

## Detail Pointers

| Need | Read |
|---|---|
| Exact code changes, migrations, tests, and review fixes | [CHANGELOG.md](CHANGELOG.md) |
| Why a technical direction was chosen | [DECISIONS.md](DECISIONS.md) |
| Current roadmap and verification baseline | [PROJECT_MANAGEMENT.md](PROJECT_MANAGEMENT.md) |
| Agent/tool/HITL architecture | [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md) |
| Deployment and operations | [DEPLOYMENT.md](DEPLOYMENT.md) |
