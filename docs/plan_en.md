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
| Frontend | CLI + FastAPI-served Vue 3 SPA |
| Package Manager | uv |
| Configuration | YAML |
| Target Platforms | English ATS: Greenhouse / Lever / Ashby, LinkedIn discovery (Chinese platforms later) |

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
│   │   ├── linkedin.py          # LinkedIn search and ATS redirect discovery
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
│   │   ├── ir.py                # Resume/Cover Letter structured IR
│   │   ├── resume_builder.py    # Evidence-grounded resume assembly
│   │   ├── cover_letter.py      # Constrained CL generation
│   │   ├── fitting.py           # Template-aware capacity fitting
│   │   ├── validator.py         # Artifact validation
│   │   └── qa_responder.py      # Quick question answering
│   ├── execution/               # Layer 5: Form Filling & Submission
│   │   ├── browser.py           # Playwright browser management
│   │   ├── form_filler.py       # Form field detection & filling
│   │   ├── file_uploader.py     # File upload
│   │   └── ats/                 # ATS adapters
│   │       ├── base.py
│   │       ├── ashby.py
│   │       ├── greenhouse.py
│   │       └── lever.py
│   ├── documents/               # Layer 6: File Pipeline
│   │   ├── docx_engine.py       # DOCX rendering from structured IR
│   │   ├── pdf_converter.py     # Word -> PDF
│   │   ├── page_count.py        # DOCX/PDF page count helpers
│   │   └── templates.py         # Template package management
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
│   ├── templates/               # DOCX template packages
│   └── output/                  # Generated resumes/CLs
├── frontend/                     # Vue SPA source and Vite build config
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

- Input sources: Greenhouse / Lever / Ashby / LinkedIn / company careers pages
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

**Resume**: Structured IR + block-based assembly, no full-text LLM rewrite
- Each bullet is tagged and traceable to profile evidence
- JD arrives → extract keywords → retrieve evidence → select best-matching bullets → optional light lexical rewrite → template-aware fitting → validation

**Cover Letter**: Structure-constrained IR generation
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

- Template package: `template.docx` + `manifest.json` + `style.lock.json` + sample JSON asset
- Block markers such as `{{resume.sections}}` and `{{cover_letter.body}}`
- Named Word styles owned by the template manifest
- DOCX-first rendering, unified PDF export
- Artifact validation and page counting
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

### Phase 6: LinkedIn Integration (Complete)

**Goal**: Discover LinkedIn jobs, enrich descriptions, and resolve external ATS links for the existing application pipeline.

13. Authenticated LinkedIn session manager with Playwright persistent context
14. LinkedIn search URL builder, pagination, job-card extraction, cache, and deduplication
15. Detail enrichment and Apply-button redirect resolution for external ATS links
16. CLI/web integration for `--source linkedin` and search profiles

### Phase 7: Web GUI (Complete)

**Goal**: Provide a human-facing operator console over the existing application layer.

17. FastAPI JSON API + Vue 3 SPA served from `src/web/static/spa`
18. Dashboard, Jobs, Applications, Profile, and Settings pages
19. Search profiles, LLM provider settings, LinkedIn session management, search cache controls

### Phase 8: Materials Workspace + Template Packages (Complete)

**Goal**: Make application material generation a first-class, reviewable product workflow.

20. `/materials` workspace for search-result jobs or pasted JDs
21. Applicant profile selection, resume/cover template selection, DOCX/PDF format selection
22. Preview, validation status, generation versions, and artifact downloads
23. Template Library uploads and package validation
24. Security hardening for template IDs, artifact paths, upload sizes, profile IDs, LinkedIn cache/enrichment, and parser heuristics

### Agent Phase 8 + 9: Agent Harness + Form-Filler Agent (Complete)

**Goal**: Stand up a confined, evaluable, HITL-gated agent loop and convert the first business node (form-filling) onto it.

25. Tool abstraction layer with allow-list registry; bounded ReAct loop (works on Claude and Codex CLIs); JSON-on-disk trace store + web viewer; fixture-driven eval harness; file-backed HITL approval queue.
26. Browser tool layer (read-only inspect + propose-only fill); `AgentFormFiller` orchestrator with HITL gate on submit; 5-fixture eval suite; per-step cost / latency telemetry surfaced in eval output and trace viewer.

### Phase 10: LLM Provider Abstraction (Complete)

**Goal**: Break out of the "Claude CLI + Codex CLI subprocess" lock-in so every downstream agent phase can target any of the major LLM providers.

27. `LLMProvider` ABC + `ProviderRegistry` + secure credential store; REST adapters for OpenAI / Anthropic / Gemini using `httpx`; subprocess providers for Claude CLI / Codex CLI (`auth_type=SUBPROCESS`).
28. Deep `test_connection` for every provider (auth round-trip, not just key-present); `codex login status` probe for subprocess providers so installed-but-unauthenticated is reported correctly.
29. `autoapply provider` CLI subcommands (`list / set-key / test / set-primary / set-fallback / disconnect`) and a `/settings` Web UI that exposes the same operations.

### Phase 11: Reliability & Cleanup (Next)

**Goal**: Make the provider layer production-grade and clean up upgrade paths.

30. Provider fallback chain in `generate_text` -- primary + ordered fallbacks; auto-failover on quota / network / auth; attempt chain recorded in trace.
31. `autoapply migrate` command to clean stale credential breadcrumbs and rename legacy settings keys on upgrade.
32. Background provider health probe; "Last verified" in Settings becomes real telemetry.

### Phase 12: Caching Foundation + Integration

**Goal**: General-purpose tiered cache for the project's expensive operations; wire it into LLM, JD scraping, and embeddings.

33. `src/cache/` -- L1 in-memory LRU + L2 SQLite-backed; per-namespace TTL; version-stamped keys; explicit invalidation API.
34. Hook into Greenhouse / Lever / LinkedIn scrapers and into `generate_text()` (opt-in via `cache=True`); cache inspector + cost-saved dashboard in the Web UI.

### Phase 13: Scheduled Task System

**Goal**: First-class scheduler for nightly batches, periodic refreshes, and cookie maintenance.

35. APScheduler + SQLite jobstore integrated into FastAPI lifespan; built-in jobs (`daily_search`, `jd_health_check`, `application_status_sync`, `linkedin_cookie_refresh`, `cache_eviction`).
36. CLI + Web UI for managing schedules; trace records for every scheduled run reusing the Phase 8.3 store.

### Phase 14: Cover-letter Agent

**Goal**: The original "agent-mode cover letter" plan, now done after the provider + cache + scheduler foundations are in place.

37. New `jd_lookup` tool; `AgentCoverLetter` orchestrator producing structured IR with evidence citations.
38. Fact-drift checker as post-guard; HITL gate fires only on bullet/story-bank mutation, not on letter generation; eval suite with 5 fixtures; Phase 12 cache participation keeps per-letter cost bounded.

### Phase 15: Filter Agent + Explainability

**Goal**: Make every job-filter decision explainable; only invoke an agent for borderline cases.

39. Filter reason chain in `src/matching/` -- every reject carries `{rule_id, reason, evidence_excerpt}`.
40. Edge-case agent for jobs scoring [0.4, 0.6]; "Why was this filtered?" affordance in JobsView; eval suite against human-annotated borderline jobs.

### Phase 16: Daily Run Loop + Review Queue

**Goal**: Integration phase. Thread the scheduler + cache + agents into a "sleep, wake to a review queue" flow.

41. `nightly_run` orchestrator: scheduled search → filter (with reasons) → top-N tailored via Phase 9 + Phase 14 agents → enqueue into review queue. Never auto-submits.
42. `/review` kanban (Pending / Approved / Submitted / Rejected) with bulk operations; morning digest; `autoapply pause-nightly` kill switch.

## Key Design Principles

1. **State machine-driven**: Every application is a state machine — interruptible, resumable, auditable
2. **Block-based resume**: No full-text LLM rewrite — select from bullet pool + light rewrite
3. **DOCX-first rendering**: LLM/content planning creates structured IR; deterministic renderers own final DOCX/PDF output
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
- Phase 6: LinkedIn search → external ATS link resolution → existing apply/material pipeline
- Phase 7: `autoapply web` → Vue SPA search/tracking/settings workflow
- Phase 8: `/jobs` → `/materials?jobId=...` → DOCX/PDF generation, preview, validation, download
- Agent Phase 8: `autoapply eval --suite agent_smoke` → all cases pass
- Agent Phase 9: `autoapply eval --suite form_filler --min-pass-rate 0.85` → 5/5 pass, est. cost ≤ $0.25
- Phase 10: Settings page → connect/test/disconnect each provider; `autoapply provider test <name>` reports auth state accurately for both REST and CLI providers
- Phase 11: revoke primary provider mid-run → fallback chain kicks in → eval still passes; `autoapply migrate` cleans legacy state
- Phase 12: re-run same batch → LLM cache hit-rate > 80%, wall time < 20%, cost < 5%
- Phase 13: register a cron'd job → restart process → trace record appears at next tick
- Phase 14: cover-letter eval 5/5 pass, ≤ $0.08/letter cache-miss, ≤ $0.02 cache-hit
- Phase 15: any rejected job in JobsView surfaces a reason chain in < 5s
- Phase 16: schedule nightly run Monday 23:00 → wake Tuesday 08:00 to N pre-tailored applications in review queue, each approvable in < 30s

Current baseline at Phase 10 close: `uv run python -m pytest` passes with 669 tests and 1 skipped; `uv run ruff check src/ tests/` and `npm run build` pass.
