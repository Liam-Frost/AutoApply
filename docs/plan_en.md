# AutoApply - Automated Job Application AI Agent Implementation Plan

## Context

The goal is to build a complete job-seeking automation system (not a simple application script) covering 7 layers of capability: job intake & filtering, applicant memory, resume/cover letter tailoring, Q&A auto-response, document processing, browser automation, and application tracking & analytics.

Core decisions (based on research report + architecture design):
- **Build from scratch** — do not fork any existing project as the main trunk
- **Playwright + Python + PostgreSQL** with pgvector for vector search
- Reference: AIHawk (architecture ideas), get_jobs (platform action patterns), GodsScion (config/QA/material customization)
- Phased approach: "high-hit semi-auto" first → conditional auto-submit → analytics-driven optimization

## Tech Stack

| Layer | Technology |
|---|---|
| Browser Automation | Playwright (Python) |
| Backend / Agent | Python 3.12+, asyncio |
| LLM | Claude Code CLI (`claude -p`) + Codex CLI — via subprocess, no API SDK |
| Database | PostgreSQL + pgvector |
| Document Processing | python-docx + docx templates, docx2pdf / LibreOffice CLI |
| Task Scheduling | asyncio (MVP), upgradeable to Celery + Redis |
| Frontend | CLI (MVP), Next.js later |
| Package Manager | uv |
| Configuration | YAML |
| Target Platforms | English ATS: Greenhouse / Lever / Workday (Chinese platforms later) |

### LLM Integration

The system invokes Claude Code CLI and Codex CLI via `subprocess` rather than calling APIs directly:

```python
# src/utils/llm.py core interface
import subprocess, json

def claude_generate(prompt: str, system: str = "", max_tokens: int = 4096) -> str:
    """Call Claude Code CLI for text generation"""
    cmd = ["claude", "-p", prompt]
    if system:
        cmd.extend(["--system", system])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.stdout.strip()

def codex_generate(prompt: str) -> str:
    """Call Codex CLI for text generation"""
    cmd = ["codex", "--quiet", "--full-auto", prompt]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.stdout.strip()
```

Advantages: No API key management (CLI handles auth), leverages CLI's context capabilities.

## Project Structure

```
AutoApply/
├── src/
│   ├── core/                    # Core Agent orchestration & state machine
│   │   ├── agent.py             # Main Agent orchestrator
│   │   ├── state_machine.py     # Application state machine
│   │   └── config.py            # Global config loader
│   ├── intake/                  # Layer 1: Job Intake
│   │   ├── base.py              # Scraper base class
│   │   ├── greenhouse.py        # Greenhouse ATS
│   │   ├── lever.py             # Lever ATS
│   │   ├── workday.py           # Workday ATS
│   │   └── schema.py            # Unified job schema
│   ├── matching/                # Layer 2: Matching & Filtering
│   │   ├── rules.py             # Hard rule filters
│   │   ├── semantic.py          # Semantic matching (embedding)
│   │   └── scorer.py            # Composite scorer
│   ├── memory/                  # Layer 3: Applicant Memory
│   │   ├── profile.py           # Identity/education/skills
│   │   ├── story_bank.py        # Reusable story bank
│   │   ├── qa_bank.py           # Q&A knowledge base
│   │   └── bullet_pool.py       # Resume bullet pool
│   ├── generation/              # Layer 4: Resume/CL Generation
│   │   ├── resume_builder.py    # Block-based resume assembly
│   │   ├── cover_letter.py      # Constrained CL generation
│   │   └── qa_responder.py      # Quick question answering
│   ├── execution/               # Layer 5: Form Filling & Submission
│   │   ├── browser.py           # Playwright browser management
│   │   ├── form_filler.py       # Form field detection & filling
│   │   ├── file_uploader.py     # File upload
│   │   └── ats/                 # ATS adapters
│   │       ├── base.py
│   │       ├── greenhouse.py
│   │       ├── lever.py
│   │       └── workday.py
│   ├── documents/               # Layer 6: File Pipeline
│   │   ├── docx_engine.py       # Word creation/editing
│   │   ├── pdf_converter.py     # Word -> PDF
│   │   └── templates.py         # Template management
│   ├── tracker/                 # Layer 7: Tracking & Analytics
│   │   ├── database.py          # Database operations
│   │   ├── analytics.py         # Statistical analysis
│   │   └── export.py            # Report export
│   └── utils/
│       ├── llm.py               # LLM call wrapper
│       ├── rate_limiter.py      # Rate limiting & anti-detection
│       └── logger.py            # Logging & screenshots
├── data/
│   ├── profile/                 # Applicant profile YAML
│   ├── templates/               # Word templates
│   └── output/                  # Generated resumes/CLs
├── config/
│   ├── settings.yaml            # Global settings
│   ├── filters.yaml             # Filter rules
│   └── .env.example             # Environment variable template
├── migrations/                  # Database migrations
├── tests/
├── pyproject.toml
└── README.md
```

## Data Model (PostgreSQL + pgvector)

### Core Tables

```sql
-- Unified job schema
CREATE TABLE jobs (
    id UUID PRIMARY KEY,
    source TEXT,               -- greenhouse/lever/workday/company_site
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT,
    employment_type TEXT,      -- intern/fulltime/coop
    seniority TEXT,
    description TEXT,
    description_embedding vector(1536),
    requirements JSONB,        -- {must_have_skills, preferred_skills, education, experience_years}
    visa_sponsorship BOOLEAN,
    ats_type TEXT,
    application_url TEXT,
    raw_data JSONB,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

-- Application records (state machine)
CREATE TABLE applications (
    id UUID PRIMARY KEY,
    job_id UUID REFERENCES jobs(id),
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    -- DISCOVERED -> QUALIFIED -> MATERIALS_READY -> FORM_OPENED
    -- -> FIELDS_MAPPED -> FILES_UPLOADED -> QUESTIONS_ANSWERED
    -- -> REVIEW_REQUIRED -> SUBMITTED -> FAILED -> NEEDS_RETRY
    match_score FLOAT,
    resume_version TEXT,
    cover_letter_version TEXT,
    qa_responses JSONB,
    screenshot_paths JSONB,
    error_log TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    outcome TEXT               -- pending/rejected/oa/interview/offer
);

-- Applicant profile (structured)
CREATE TABLE applicant_profile (
    id UUID PRIMARY KEY,
    section TEXT NOT NULL,     -- identity/education/skills/experience/projects
    content JSONB NOT NULL,
    content_embedding vector(1536),
    tags TEXT[],
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Bullet pool
CREATE TABLE bullet_pool (
    id UUID PRIMARY KEY,
    category TEXT,             -- experience/project/achievement
    source_entity TEXT,        -- Which company/project
    text TEXT NOT NULL,
    text_embedding vector(1536),
    tags TEXT[],               -- backend/frontend/ml/leadership/etc
    used_count INT DEFAULT 0
);

-- QA knowledge base
CREATE TABLE qa_bank (
    id UUID PRIMARY KEY,
    question_pattern TEXT,
    question_type TEXT,        -- authorization/sponsorship/experience_years/salary/why_company/why_role/custom
    canonical_answer TEXT,
    variants JSONB,            -- {by_geography, by_role_type}
    confidence TEXT DEFAULT 'high',
    needs_review BOOLEAN DEFAULT FALSE
);
```

## Layered Architecture

### Layer 1: Job Intake

Responsible for scraping, aggregating, and standardizing JDs.

- Input sources: Greenhouse / Lever / Workday / company careers pages
- Unified output schema: company, title, location, employment_type, seniority, skills, visa, ATS type, application URL, quick questions, deadline

Core principle: standardize first, don't "apply on sight."

### Layer 2: Matching & Filtering

Three-tier scoring:

1. **Rules layer (hard filter)**: location, job type, visa, education, experience years
2. **Semantic layer**: JD embedding vs profile embedding (courses/projects/tech stack/industry matching)
3. **Risk layer**: staffing spam / fake job / repost / ghost job filtering

Precise filtering is more valuable than mass-applying — don't waste 250 opportunities on wrong positions.

### Layer 3: Applicant Memory

A structured knowledge base, not just a resume dumped to an LLM:

- `identity_profile` — basic identity info
- `education_records` — education history
- `course_records` — courses and grades
- `work_experiences` — work history
- `projects` — project details
- `skills` — skill inventory
- `story_bank` — reusable stories by theme (why this direction/company, technical challenges, conflict resolution, ownership/impact)
- `qa_bank` — structured templates for common quick questions (canonical answer + variants + confidence + needs_review flag)

### Layer 4: Resume / Cover Letter Generation

**Resume**: Block-based assembly, no full-text LLM rewrite
- Each bullet tagged (backend/frontend/ml/security/leadership, etc.)
- JD arrives → extract keywords → map to tags → select best-matching bullets → light lexical rewrite → fact-drift check

**Cover Letter**: Structure-constrained semi-generation
- Opening: role + reason
- Middle: 2-3 best-matching evidence points
- Company tie-in: why this company
- Close: availability / interest

**Quick Questions**: classify → qa_bank exact match → template variants → LLM generation (descending confidence), high-risk questions flagged for human review.

### Layer 5: Form Filling & Submission (Application Execution)

Each application modeled as a state machine:

```
DISCOVERED → QUALIFIED → MATERIALS_READY → FORM_OPENED
→ FIELDS_MAPPED → FILES_UPLOADED → QUESTIONS_ANSWERED
→ REVIEW_REQUIRED → SUBMITTED → FAILED → NEEDS_RETRY
```

Every step: screenshot, save DOM/field mapping, log errors, resumable from any state.

### Layer 6: File Pipeline

- Master template in `.docx`, variable substitution + block-level content assembly
- Unified PDF export
- File versioning: `resume_{company}_{role}_{date}.pdf`
- Record which version was used for each application

### Layer 7: Analytics / CRM

Built from day one, not retrofitted:
- Track: source, company, role, date, platform, resume version, match score, status, outcome
- Analyze: which job types have highest hit rate, which platforms are highest quality, which keyword combos are most effective, which resume versions convert best

## Phased Implementation

### Phase 1: Infrastructure + Applicant Memory (Weeks 1-2)

**Goal**: Project skeleton running, applicant profile fully loaded into DB

1. Project initialization
   - pyproject.toml + uv dependency management
   - PostgreSQL + pgvector environment setup
   - Database migrations (alembic)
   - Config loading (YAML)
   - LLM CLI wrapper (claude -p / codex)
   - Logging system

2. Applicant Memory layer
   - Define profile YAML schema
   - **Resume importer**: parse existing Word/PDF resume → structured YAML → DB (Claude CLI-assisted parsing)
   - Profile loading & DB ingestion
   - Bullet pool management (with tags)
   - Story bank and QA bank
   - Embedding generation & storage

3. Document Processing layer
   - Word template system (python-docx)
   - Block-based resume assembly engine
   - Word → PDF conversion
   - File naming & version management

### Phase 2: Job Intake + Smart Filtering (Weeks 3-4)

**Goal**: Automated job scraping with precise scoring

4. Job Intake layer
   - Unified Job schema
   - Greenhouse + Lever scrapers
   - JD parsing & structuring (LLM-assisted)
   - Deduplication & freshness management

5. Matching & Filtering layer
   - Hard rule filters
   - Semantic matching
   - Composite scoring
   - Low-quality job filtering

### Phase 3: Resume/CL Tailoring + QA (Weeks 5-6)

**Goal**: Auto-generate tailored materials per position

6. Resume generation: JD keyword extraction → bullet selection → rewrite → fact check → docx + pdf
7. Cover Letter generation: structure constraints + controlled LLM generation
8. Quick Question answering: classify → match → generate → flag for human review

### Phase 4: Browser Automation + Form Filling (Weeks 7-8)

**Goal**: Auto-fill forms, upload files, pause before submit for human confirmation

9. Playwright browser management + application state machine + ATS adapters
10. Anti-detection: random intervals, concurrency limits, rate control, cooldown

### Phase 5: Tracking & Full Pipeline (Weeks 9-10)

**Goal**: Complete loop, semi-automated application workflow

11. Application tracking & statistical analytics
12. Agent main loop orchestration + CLI interactive interface

## Key Design Principles

1. **State machine-driven**: Every application is a state machine — interruptible, resumable, auditable
2. **Block-based resume**: No full-text LLM rewrite — select from bullet pool + light rewrite
3. **Constrained generation**: All LLM generation bounded by structural templates to prevent style drift and fabrication
4. **Human confirmation points**: Default pause before submit; auto-submit only under validated conditions
5. **Full audit trail**: Screenshots, DOM snapshots, file versions, QA responses all recorded

## Risk Mitigation

- Minimize indiscriminate mass submissions; retain human confirmation points
- Prioritize ATS / company site structured form flows
- Implement failure rollback, logging, rate limiting, and task scheduling
- Focus automation on "organizing materials, tailoring content, filling forms, tracking" rather than maximizing submission count

## Verification

- Phase 1: Load profile YAML → ingest to DB → generate one tailored Word resume + PDF
- Phase 2: Scrape jobs from Greenhouse → score & rank → output top-N recommendation list
- Phase 3: Given a JD → auto-select bullets → generate tailored resume + CL + answer quick questions
- Phase 4: For a Greenhouse job → auto-fill form → upload files → screenshot (no submit)
- Phase 5: Run full pipeline on 10 jobs → view tracking dashboard → analytics report
