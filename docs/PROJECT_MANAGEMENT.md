# AutoApply — Project Management

## Overview

This document tracks development progress, decisions, and context for the AutoApply project. It is designed to be self-contained so that any AI assistant or developer can pick up where the previous session left off.

## Architecture Summary

AutoApply is a 7-layer modular job application automation system:

| Layer | Module | Purpose |
|-------|--------|---------|
| 1 | `src/intake/` | Scrape & standardize job postings from ATS (Greenhouse, Lever, Workday) |
| 2 | `src/matching/` | Rule-based + semantic + risk filtering to score jobs |
| 3 | `src/memory/` | Structured applicant profile, bullet pool, story bank, QA bank |
| 4 | `src/generation/` | Block-based resume assembly, constrained CL generation, QA answering |
| 5 | `src/execution/` | Playwright browser automation, form filling, ATS adapters |
| 6 | `src/documents/` | Word/PDF creation, template system, file versioning |
| 7 | `src/tracker/` | Application tracking, analytics, reporting |

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
- **Target platforms**: English ATS only (Greenhouse, Lever, Workday)

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
| 1.1 | Project init: uv, PostgreSQL+pgvector, Alembic, config loader, LLM CLI wrapper, logging | Not started |
| 1.2 | Applicant Memory: profile YAML schema, resume importer, bullet pool, story bank, QA bank, embeddings | Not started |
| 1.3 | Document Processing: Word template engine, block-based resume assembly, PDF conversion, file versioning | Not started |

**Verification**: Load profile YAML → ingest to DB → generate one tailored Word resume + PDF

### Phase 2: Job Intake + Smart Filtering (Weeks 3-4)

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 2.1 | Job schema, Greenhouse scraper, Lever scraper, JD parsing (LLM-assisted) | Not started |
| 2.2 | Hard rule filters, semantic matching, composite scorer, low-quality job filtering | Not started |

**Verification**: Scrape Greenhouse jobs → score & rank → output top-N list

### Phase 3: Resume/CL Tailoring + QA (Weeks 5-6)

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 3.1 | JD keyword extraction, bullet selection, lexical rewrite, fact-drift check | Not started |
| 3.2 | Cover letter generation (structure-constrained), company research | Not started |
| 3.3 | Quick question answering (classify → match → generate → review flag) | Not started |

**Verification**: Given JD → auto-select bullets → generate resume + CL + answer questions

### Phase 4: Browser Automation + Form Filling (Weeks 7-8)

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 4.1 | Playwright browser management, application state machine, ATS adapters | Not started |
| 4.2 | Form field detection, file upload, screenshot/DOM capture, error recovery | Not started |
| 4.3 | Anti-detection: random intervals, rate control, cooldown | Not started |

**Verification**: Greenhouse job → auto-fill form → upload files → screenshot (no submit)

### Phase 5: Tracking & Full Pipeline (Weeks 9-10)

| Sub-phase | Scope | Status |
|-----------|-------|--------|
| 5.1 | Application tracking DB, status updates, timeline | Not started |
| 5.2 | Analytics: hit rate, platform quality, keyword effectiveness, resume version comparison | Not started |
| 5.3 | Agent main loop, CLI interface, batch scheduling | Not started |

**Verification**: Run full pipeline on 10 jobs → tracking dashboard → analytics report

## Current Session Context

- **Active branch**: `dev`
- **Current phase**: Phase 1.1 — Project initialization
- **Last commit**: Initial project setup with architecture plan (master)
- **Blockers**: None
- **Next step**: Set up uv project, install dependencies, configure PostgreSQL + pgvector, create Alembic migrations, implement config loader and LLM CLI wrapper
