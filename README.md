# AutoApply

An AI-powered agent that automates the entire job application process — from job discovery to submission tracking.

## Docs

- [Deployment Guide (EN)](docs/DEPLOYMENT.md)
- [部署与使用教程（中文）](docs/DEPLOYMENT_zh.md)
- [Implementation Plan (EN)](docs/plan_en.md)
- [实施计划（中文）](docs/plan_zh.md)
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
| Frontend | Vue 3 + Vue Router + Vite |
| Web Backend | FastAPI JSON API |
| Browser Automation | Playwright |
| LLM | Claude Code CLI + Codex CLI (via subprocess) |
| Database | PostgreSQL + pgvector |
| Document Processing | python-docx, docx2pdf / LibreOffice |
| Package Manager | uv + npm |
| Target Platforms | Greenhouse, Lever, Ashby, LinkedIn discovery |

## Project Structure

```
frontend/            # Vue frontend source and build config
src/
├── application/   # Shared use cases for CLI and Web
├── core/          # Agent orchestration & state machine
├── intake/        # Job scraping & schema
├── matching/      # Filtering & scoring
├── memory/        # Applicant profile, story bank, QA bank, bullet pool
├── generation/    # Resume/cover IR, fitting, validation, QA responder
├── execution/     # Playwright browser, form filler, ATS adapters
├── documents/     # DOCX/PDF engine, template packages, page count helpers
├── tracker/       # Database, analytics, export
├── utils/         # LLM wrapper, rate limiter, logger
└── web/           # FastAPI API + built SPA assets
```

## Current Status

- **Phase 1** (Infrastructure + Applicant Memory + Document Processing) — Complete
- **Phase 2** (Job Intake + Smart Filtering) — Complete
- **Phase 3** (Resume/CL Tailoring + QA) — Complete
- **Phase 4** (Browser Automation + Form Filling) — Complete
- **Phase 5** (CLI + Tracking + Full Pipeline) — Complete
- **Phase 6** (LinkedIn Integration) — Complete
- **Phase 7** (Web GUI) — Complete
- **Phase 8** (Materials Workspace + DOCX Template Packages + Hardening) — Complete

340 tests passing, 1 skipped. See [CHANGELOG](docs/CHANGELOG.md) for details.

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
```

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
- `/settings` manages LLM provider priority, fallback, and search cache settings

The Materials page is the main human-in-the-loop generation workflow: select a job or paste a JD, choose an applicant profile, select resume/cover letter templates and formats, generate, preview, then download DOCX/PDF artifacts.

## Getting Started

> Start here: [Deployment Guide (EN)](docs/DEPLOYMENT.md) | [部署与使用教程（中文）](docs/DEPLOYMENT_zh.md)

### Prerequisites

- Python 3.12+
- PostgreSQL 16+ with pgvector extension
- At least one local LLM CLI: Claude Code CLI or Codex CLI
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

The committed repo includes built frontend assets under `src/web/static/spa`, so rebuilding the Vue app is mainly needed when you change files under `frontend/`.

## Design Principles

1. **State machine-driven** — Every application is interruptible, resumable, auditable
2. **Block-based resume** — Select from bullet pool + light rewrite, no full-text LLM hallucination
3. **DOCX-first rendering** — LLM/content planning produces structured IR; deterministic renderers own final DOCX/PDF output
4. **Human-in-the-loop** — Default pause before submit; auto-submit only under validated conditions
5. **Full audit trail** — Screenshots, DOM snapshots, file versions, QA responses all recorded

## License

Private — not yet determined.
