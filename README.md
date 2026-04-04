# AutoApply

An AI-powered agent that automates the entire job application process — from job discovery to submission tracking.

## Docs

- [Deployment Guide (EN)](docs/DEPLOYMENT.md)
- [部署与使用教程（中文）](docs/DEPLOYMENT_zh.md)
- [Implementation Plan (EN)](docs/plan_en.md)
- [实施计划（中文）](docs/plan_zh.md)
- [Changelog](docs/CHANGELOG.md)

## What It Does

- **Job Intake**: Scrape and standardize job postings from Greenhouse, Lever, and LinkedIn-discovered external ATS links
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
| Target Platforms | Greenhouse, Lever, LinkedIn discovery |

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
- **Phase 5** (CLI + Tracking + Full Pipeline) — Complete
- **Phase 6** (LinkedIn Integration) — Complete
- **Phase 7** (Web GUI) — Complete

244 tests passing. See [CHANGELOG](docs/CHANGELOG.md) for details.

## CLI Usage

```bash
# First-time setup
autoapply init

# Search for matching jobs
autoapply search --profile default --score

# Apply to a single job
autoapply apply --url https://boards.greenhouse.io/company/jobs/123

# Batch apply to top matches
autoapply apply --batch --top-n 5

# View tracking dashboard
autoapply status

# Export applications to CSV
autoapply status --export-csv report.csv
```

## Getting Started

> Start here: [Deployment Guide (EN)](docs/DEPLOYMENT.md) | [部署与使用教程（中文）](docs/DEPLOYMENT_zh.md)

### Prerequisites

- Python 3.12+
- PostgreSQL 16+ with pgvector extension
- At least one local LLM CLI: Claude Code CLI or Codex CLI
- uv package manager

### Setup

```bash
# Clone
git clone https://github.com/Liam-Frost/AutoApply.git
cd AutoApply

# Install dependencies
uv sync

# Install Playwright browser
uv run playwright install chromium

# Install at least one LLM CLI locally
# npm install -g @anthropic-ai/claude-code
# npm install -g @openai/codex

# Configure
cp config/.env.example .env
# Edit .env with your settings

# Setup database
alembic upgrade head

# First-time setup with explicit LLM priority
uv run autoapply init --llm-primary claude-cli --llm-fallback codex-cli
```

## Design Principles

1. **State machine-driven** — Every application is interruptible, resumable, auditable
2. **Block-based resume** — Select from bullet pool + light rewrite, no full-text LLM hallucination
3. **Constrained generation** — All LLM output bounded by structural templates
4. **Human-in-the-loop** — Default pause before submit; auto-submit only under validated conditions
5. **Full audit trail** — Screenshots, DOM snapshots, file versions, QA responses all recorded

## License

Private — not yet determined.
