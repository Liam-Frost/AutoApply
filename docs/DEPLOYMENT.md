# AutoApply Deployment And Usage Guide

This guide documents the real, working setup flow for the current project.
It covers local deployment, first-time initialization, CLI usage, and the web dashboard.

## 1. What You Are Deploying

AutoApply currently supports:

- ATS job intake from Greenhouse and Lever
- LinkedIn search with external ATS redirect discovery
- Tailored resume and cover letter generation per job
- QA template loading from `qa_bank`
- Browser automation for Greenhouse and Lever applications
- Application tracking, analytics, CSV export, and web dashboard

Direct apply support is currently implemented for:

- Greenhouse
- Lever

## 2. Prerequisites

Install these before starting:

- Python `3.12+`
- `uv`
- PostgreSQL `16+`
- PostgreSQL `pgvector` extension
- Chromium for Playwright
- At least one document-to-PDF path:
  - Microsoft Word + `docx2pdf`, or
  - LibreOffice
- Claude Code CLI and/or Codex CLI if you want LLM-backed parsing/generation

## 3. Clone And Install

```bash
git clone https://github.com/Liam-Frost/AutoApply.git
cd AutoApply
uv sync
uv run playwright install chromium
```

After `uv sync`, the project exposes the CLI entrypoint. You can use either:

```bash
autoapply --help
```

or the more portable form:

```bash
uv run autoapply --help
```

## 4. Database Setup

Create a PostgreSQL database and user first.

Example SQL:

```sql
CREATE USER autoapply WITH PASSWORD 'change-me';
CREATE DATABASE autoapply OWNER autoapply;
\c autoapply
CREATE EXTENSION IF NOT EXISTS vector;
```

## 5. Configure Environment

Copy the example environment file:

```bash
cp config/.env.example .env
```

Set the database values in `.env`:

```env
AUTOAPPLY_DB_HOST=localhost
AUTOAPPLY_DB_PORT=5432
AUTOAPPLY_DB_NAME=autoapply
AUTOAPPLY_DB_USER=autoapply
AUTOAPPLY_DB_PASSWORD=change-me
AUTOAPPLY_LOG_LEVEL=INFO
```

Notes:

- `config/settings.yaml` provides defaults
- `.env` overrides those defaults
- environment variables override both

## 6. Run Migrations

```bash
uv run alembic upgrade head
```

You can also let `autoapply init` validate the database and run migrations for you.

## 7. First-Time Initialization

### Option A: interactive setup

```bash
uv run autoapply init
```

### Option B: import an existing structured profile

```bash
uv run autoapply init --profile data/profile/profile.yaml
```

### Option C: parse a resume into a profile

```bash
uv run autoapply init --resume "/path/to/resume.pdf"
```

Useful flags:

```bash
uv run autoapply init --skip-db
uv run autoapply init --skip-llm
```

What `init` does:

- validates `config/settings.yaml` and `.env`
- tests database connectivity
- runs Alembic migrations
- imports or creates `data/profile/profile.yaml`
- checks LLM CLI availability

## 8. Profile And Config Files

Main files you will edit:

- `data/profile/profile.yaml`
- `config/settings.yaml`
- `config/filters.yaml`
- `config/companies.yaml`

Guidance:

- put your identity, education, experiences, projects, skills, `story_bank`, and `qa_bank` in `profile.yaml`
- put ATS company slugs in `companies.yaml`
- define matching filters in `filters.yaml`

## 9. Job Search Workflow

### ATS search

```bash
uv run autoapply search --profile default --score
```

### ATS search for one company or ATS

```bash
uv run autoapply search --ats greenhouse --company stripe --score
```

### LinkedIn search

```bash
uv run autoapply search \
  --source linkedin \
  --keyword "software engineer intern" \
  --location "United States" \
  --time-filter week \
  --max-pages 3
```

### Combined search

```bash
uv run autoapply search --source all --keyword "backend intern" --score
```

Notes:

- first LinkedIn use may require interactive login
- LinkedIn results can be enriched with external ATS links
- scoring requires a valid `data/profile/profile.yaml`

## 10. Application Workflow

### Apply to one ATS URL

```bash
uv run autoapply apply --url https://boards.greenhouse.io/company/jobs/123
```

### Dry run only

```bash
uv run autoapply apply --url https://jobs.lever.co/company/abc123/apply --dry-run
```

### Apply by tracked database job id

```bash
uv run autoapply apply --job-id <uuid>
```

### Batch apply to top matches

```bash
uv run autoapply apply --batch --top-n 5 --profile default
```

### Auto-submit instead of pausing for review

```bash
uv run autoapply apply --url <ats-url> --auto-submit
```

What happens during `apply` now:

- detects ATS type from the target URL
- loads job context from DB or ATS API when possible
- generates a job-specific resume and cover letter
- loads QA answers from `qa_bank`
- creates a tracked `Application` record
- fills the form with Playwright
- syncs screenshots and state back into tracking

## 11. Web Dashboard

Start the web UI:

```bash
uv run autoapply web --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Pages:

- `/` dashboard
- `/jobs` job search and apply actions
- `/applications` tracking and outcome updates
- `/profile` profile inspection and resume import

## 12. Tracking And Export

Show analytics in CLI:

```bash
uv run autoapply status
```

Export CSV:

```bash
uv run autoapply status --export-csv report.csv
```

Filter recent applications:

```bash
uv run autoapply status --company Stripe --status SUBMITTED --outcome interview
```

## 13. Recommended Deployment Modes

### Developer laptop / personal workstation

- use `uv run autoapply web --reload`
- keep PostgreSQL local
- keep Playwright and LibreOffice on the same machine

### Single Linux server or VM

- install Python, PostgreSQL, LibreOffice, and Chromium
- run PostgreSQL locally or use a managed database
- launch the dashboard behind a reverse proxy
- run the CLI manually or from a scheduler

Example dashboard command on a server:

```bash
uv run autoapply web --host 0.0.0.0 --port 8000 --no-open
```

## 14. Operational Notes

- `apply` automation is currently for Greenhouse and Lever
- LinkedIn is primarily for search and ATS link discovery
- PDF conversion depends on Word/docx2pdf or LibreOffice
- LLM-dependent features degrade gracefully when the CLI is unavailable, but some parsing/generation quality will drop
- the default workflow is human-in-the-loop; auto-submit is optional

## 15. Troubleshooting

### `autoapply` command not found

Use:

```bash
uv run autoapply --help
```

If needed, rerun:

```bash
uv sync
```

### Database connection failed

Check:

- PostgreSQL is running
- `.env` values are correct
- the database and user exist
- `pgvector` can be created

### Web app fails on startup

Run:

```bash
uv sync
uv run autoapply web
```

### Browser automation fails

Run:

```bash
uv run playwright install chromium
```

Then try non-headless mode:

```bash
uv run autoapply apply --url <ats-url> --no-headless
```

### No PDF output generated

Install one of:

- Microsoft Word with `docx2pdf`
- LibreOffice

### LinkedIn login problems

- run LinkedIn search with `--no-headless`
- complete login manually on the first run
- reuse the saved session under `data/.linkedin_session`

## 16. Validation Checklist

Use this after deployment:

```bash
uv run ruff check .
uv run pytest -q
uv run autoapply --help
uv run autoapply status
uv run autoapply web --no-open
```

Expected current baseline:

- tests passing
- CLI loads
- dashboard starts
- database-backed tracking is available after initialization
