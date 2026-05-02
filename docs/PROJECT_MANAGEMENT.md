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

## Current Session Context

- **Active branch**: `dev`
- **Current phase**: Phase 8 complete; docs updated after Materials/template hardening
- **Last verification**: `uv run python -m pytest` -> 340 passed, 1 skipped; `uv run ruff check .` passes; `npm run build` passes
- **Blockers**: None
- **Next step**: Create/merge PR from `dev` to `master`, then continue production hardening and UX refinement as needed
