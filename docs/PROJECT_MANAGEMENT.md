# Project Management

This document is the live operating context for AutoApply. It should stay short, current, and actionable. Historical implementation detail belongs in [Phase History](PHASE_HISTORY.md) and [Changelog](CHANGELOG.md). Architecture rationale belongs in [Architecture Decisions](DECISIONS.md).

## Current State

AutoApply is complete through **Phase 17.8: Material Strategy & Document Library**.

The product currently supports job discovery, job-index freshness, fit scoring and explanations, materials generation, document-library curation, automation plans, review queues, gated submission, application tracking, provider management, and background task execution.

The next planned hardening area is **Phase 18: Multi-Tenancy & Auth Hardening**.

## Verification Baseline

Last local verification in this workspace:

| Check | Result |
|---|---|
| `uv run pytest -q` | 1514 passed, 1 skipped |
| `npm run build` | Passed; existing Vite chunk-size warning remains |
| `python -m py_compile` on plan-run modules | Passed |
| Product-string cleanup | No remaining legacy batch-run naming in source docs or built SPA assets |

When schema changes are present, run `uv run alembic upgrade head` before launching the web app. The current head is `e7c3a5b91f48`, which creates the `user_documents` table for the Document Library.

## Active Roadmap

| Phase | Scope | Status |
|---|---|---|
| 17.8 | Material strategy defaults, user document library, plan-level material overrides, replace-materials review actions | Complete |
| 18 | Multi-tenancy and auth hardening | Planned |

### Phase 18 Working Scope

| Area | Intended Outcome |
|---|---|
| Tenant and user model | First-class `tenants` and `users` tables replacing implicit single-user assumptions |
| Auth middleware | FastAPI request identity and tenant context instead of ambient `default` fallback |
| PostgreSQL isolation | Row-level security or equivalent tenant filtering discipline for user data |
| Redis namespace hardening | Per-tenant keys for cache, locks, task metadata, and rate limits |
| Credential isolation | Provider credentials scoped by tenant/user rather than global project state |
| Audit and quotas | Durable audit events and usage limits suitable for a future hosted deployment |

## Architecture Snapshot

| Area | Source of Truth | Notes |
|---|---|---|
| Web UI | `frontend/` | Vue 3, Vue Router, Vite, Tailwind, shadcn-style components |
| API | `src/web/` | FastAPI JSON routes plus built SPA serving |
| Use cases | `src/application/` | Shared by CLI and Web; should own session lifecycle where possible |
| Persistence | `src/core/models.py`, `migrations/` | PostgreSQL + pgvector via SQLAlchemy/Alembic |
| Cache and queue | Redis, `src/cache/`, `src/tasks/` | Redis is derived state; PostgreSQL remains durable state |
| Background work | Celery, `src/tasks/beat.py` | Queues: `search`, `materials`, `application`, `maintenance` |
| Job intelligence | `src/jobs/`, `src/intake/` | Normalized search queries, immutable snapshots, freshness state |
| Materials | `src/generation/`, `src/documents/` | Template rendering, source patching, document library, material defaults |
| Automation | `src/orchestration/`, `src/application/review.py` | Plan runs, review queue, digest, gated submission |
| Agents | `src/agent/` | Bounded tool registry, trace store, eval suites, HITL contracts |
| Providers | `src/providers/`, `src/utils/llm.py` | OpenAI, Anthropic, Gemini, Claude CLI, Codex CLI through one registry |

## Operator Commands

| Task | Command |
|---|---|
| Upgrade database | `uv run alembic upgrade head` |
| Start web console | `uv run autoapply web --host 127.0.0.1 --port 8000` |
| Start all-purpose worker | `uv run autoapply worker --queues search,materials,application,maintenance` |
| Start scheduler | `uv run autoapply beat` |
| Build frontend | `cd frontend; npm run build` |
| Run backend tests | `uv run pytest -q` |
| Run targeted task tests | `uv run pytest tests/test_web_routes_tasks.py tests/test_tasks_beat.py tests/test_tasks_kinds.py -q` |

## Documentation Ownership

| Document | Role | Keep Out |
|---|---|---|
| `README.md` | Product overview, quick start, architecture map, doc index, license | Long phase logs, sub-phase implementation detail, internal review notes |
| `docs/PROJECT_MANAGEMENT.md` | Current project state, next roadmap, verification baseline, operating context | Historical phase narratives and duplicated changelog entries |
| `docs/PHASE_HISTORY.md` | Compact shipped-phase archive | Per-commit implementation bullets |
| `docs/CHANGELOG.md` | Detailed implementation changes, migrations, tests, review fixes | Product marketing copy and future planning prose |
| `docs/DECISIONS.md` | Design decisions with rationale and trade-offs | Status tracking and implementation logs |
| `docs/AGENT_ARCHITECTURE.md` | Agent/tool/HITL/trace/eval contracts | General product roadmap |
| `docs/DEPLOYMENT.md` and `docs/DEPLOYMENT_zh.md` | Installation, operations, service commands, troubleshooting | Architecture debate and phase history |
| `docs/plan_en.md` and `docs/plan_zh.md` | Long-form planning reference | Current status claims that need frequent updates |

## Maintenance Rules

- Keep README product-facing and concise.
- Update this file when the active phase, verification baseline, or next roadmap changes.
- Update CHANGELOG when a feature, migration, route, CLI command, or behavior change lands.
- Update DECISIONS only for architectural choices that should be stable and citeable.
- Do not duplicate long implementation bullets across README, PROJECT_MANAGEMENT, and CHANGELOG.
- Prefer current product names: `plan_run`, plan runs, automation plans, review queue, document library.
