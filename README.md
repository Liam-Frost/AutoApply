# AutoApply

An AI-powered agent that automates the entire job application process — from job discovery to submission tracking.

## What It Does

- **Job Intake**: Scrape and standardize job postings from Greenhouse, Lever, Workday, and company career pages
- **Smart Filtering**: Three-tier scoring (hard rules + semantic matching + risk filtering) to only target high-fit positions
- **Applicant Memory**: Structured knowledge base of your education, projects, skills, stories, and Q&A templates
- **Tailored Materials**: Block-based resume assembly and constrained cover letter generation per position — no full-text LLM hallucination
- **Quick Question Answering**: Auto-answer common application questions with confidence-based routing and human review flags
- **Form Automation**: Playwright-driven form filling with state machine recovery, screenshots, and human confirmation before submit
- **Document Pipeline**: Word template system with PDF export and version tracking
- **Application Tracking**: Full CRM with analytics on hit rates, platform quality, and resume version effectiveness

## Architecture

7-layer modular system:

```
Layer 1: Job Intake          — Scrape & standardize JDs
Layer 2: Matching & Filtering — Rule + semantic + risk scoring
Layer 3: Applicant Memory     — Structured profile & knowledge base
Layer 4: Generation           — Resume/CL tailoring & QA
Layer 5: Execution            — Browser automation & form filling
Layer 6: File Pipeline        — Word/PDF creation & versioning
Layer 7: Analytics            — Tracking, statistics & optimization
```

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| Browser Automation | Playwright |
| LLM | Claude Code CLI + Codex CLI (via subprocess) |
| Database | PostgreSQL + pgvector |
| Document Processing | python-docx, docx2pdf / LibreOffice |
| Package Manager | uv |
| Target Platforms | Greenhouse, Lever, Workday (English ATS) |

## Project Structure

```
src/
├── core/          # Agent orchestration & state machine
├── intake/        # Job scraping & schema
├── matching/      # Filtering & scoring
├── memory/        # Applicant profile, story bank, QA bank, bullet pool
├── generation/    # Resume builder, cover letter, QA responder
├── execution/     # Playwright browser, form filler, ATS adapters
├── documents/     # Word/PDF engine & templates
├── tracker/       # Database, analytics, export
└── utils/         # LLM wrapper, rate limiter, logger
```

## Current Status

- **Phase 1** (Infrastructure + Applicant Memory + Document Processing) — Complete
- **Phase 2** (Job Intake + Smart Filtering) — Complete
- **Phase 3** (Resume/CL Tailoring + QA) — Complete
- **Phase 4** (Browser Automation + Form Filling) — Complete
- **Phase 5** (Tracking & Full Pipeline) — Next

156 tests passing. See [CHANGELOG](docs/CHANGELOG.md) for details.

## Getting Started

> Project is in active development. See [Implementation Plan (EN)](docs/plan_en.md) | [实施计划 (中文)](docs/plan_zh.md)

### Prerequisites

- Python 3.12+
- PostgreSQL 16+ with pgvector extension
- Claude Code CLI and/or Codex CLI
- uv package manager

### Setup

```bash
# Clone
git clone https://github.com/Liam-Frost/AutoApply.git
cd AutoApply

# Install dependencies
uv sync

# Configure
cp config/.env.example .env
# Edit .env with your settings

# Setup database
alembic upgrade head
```

## Design Principles

1. **State machine-driven** — Every application is interruptible, resumable, auditable
2. **Block-based resume** — Select from bullet pool + light rewrite, no full-text LLM hallucination
3. **Constrained generation** — All LLM output bounded by structural templates
4. **Human-in-the-loop** — Default pause before submit; auto-submit only under validated conditions
5. **Full audit trail** — Screenshots, DOM snapshots, file versions, QA responses all recorded

## License

Private — not yet determined.
