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
| 4 | `src/generation/` | Block-based resume assembly, constrained CL generation, QA answering |
| 5 | `src/execution/` | Playwright browser automation, form filling, ATS adapters |
| 6 | `src/documents/` | Word/PDF creation, template system, file versioning |
| 7 | `src/tracker/` | Application tracking, analytics, reporting |

| 8 | `src/web/` | FastAPI web GUI: dashboard, job search, application pipeline, profile management |

Orchestration lives in `src/core/` (agent, state machine, config).
Shared utilities in `src/utils/` (LLM CLI wrapper, rate limiter, logger).

## Tech Stack

- **Language**: Python 3.12+
- **Package manager**: uv
- **Database**: PostgreSQL 16+ with pgvector
- **Browser automation**: Playwright
- **LLM**: Claude Code CLI (`claude -p`) + Codex CLI — invoked via subprocess, no API SDK
- **Document processing**: python-docx, docx2pdf / LibreOffice CLI
- **DB migrations**: Alembic + SQLAlchemy
- **Target platforms**: Greenhouse + Lever for direct apply, LinkedIn for job discovery / ATS redirect extraction

## Development Workflow

### Branching

- `master` — stable, merged after each completed Phase
- `dev` — active development, pushed after each sub-phase with code review

### Commit & Review Cadence

1. Write code for a sub-phase (e.g., Phase 1.1, 1.2, 1.3)
2. Run `codex review --uncommitted` for AI code review
3. Address review findings
4. Commit with descriptive message → push to `dev`
5. After full Phase completion: final code review → merge `dev` into `master` → update docs

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
| 7.1 | FastAPI backend + static assets + project structure (Jinja2 + HTMX + TailwindCSS) | **Complete** |
| 7.2 | Dashboard page: pipeline overview, stats cards, recent applications table | **Complete** |
| 7.3 | Job search page: search form, results table with scoring, save/apply actions | **Complete** |
| 7.4 | Application pipeline page + profile management page | **Complete** |
| 7.5 | Tests + code review | **Complete** |

**Verification**: `autoapply web` -> browser opens dashboard -> search jobs -> trigger apply -> view status

## Current Session Context

- **Active branch**: `dev`
- **Active branch**: `dev` (Phase 7 complete, merging to master)
- **Current phase**: All 7 phases complete
- **Last verification**: CLI packaging fixed, apply/tracking/web wiring repaired (244/244 tests passing)
- **Blockers**: None
- **Next step**: End-to-end testing, polish, production hardening
