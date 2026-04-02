# Changelog

All notable changes to AutoApply are documented here, organized by Phase.

## [0.3.0] — 2026-04-02 — Phase 3: Resume/CL Tailoring + QA

### Phase 3.1: Resume Builder
- JD tag extraction from requirements and title keywords
- Bullet selection by tag overlap (ranked, configurable max per entity)
- Optional LLM-powered light lexical rewrite with keyword injection
- Fact-drift guard: rejects rewrites that change length >2x or <0.3x
- Full pipeline: extract → select → rewrite → docx assembly → PDF conversion

### Phase 3.2: Cover Letter Generator
- Structure-constrained generation: opening → evidence → company tie-in → close
- LLM generation bounded by system prompt (250-400 words, no fabrication)
- Template fallback when LLM unavailable
- Auto-selects best evidence bullets from profile by JD tag overlap

### Phase 3.3: QA Auto-Responder
- Question classifier for 10 types (authorization, sponsorship, salary, start_date, why_company, why_role, strengths, weaknesses, experience_years, custom)
- Confidence cascade: QA bank match → template → LLM → flag for review
- Geography and role-type variant selection from QA bank
- High-risk types (salary, authorization, sponsorship) always flagged for review
- LLM-generated answers always flagged for review

### Post-Review Fixes (Codex review)
- **P1**: Removed auto-generated authorization/sponsorship template answers — jurisdiction-sensitive, must use QA bank with explicit variants or flag for review
- **P2**: Experience year calculation now uses month-level precision with interval merging to avoid double-counting and calendar-year inflation

### Tests
- 43 generation tests (JD tag extraction, bullet selection/ranking, evidence selection, cover letter template, question classification, QA bank matching, variant selection, template answers, experience calculation, answer pipeline)

---

## [0.2.0] — 2026-04-02 — Phase 2: Job Intake + Smart Filtering

### Phase 2.1: Job Intake
- Unified Job schema (Pydantic): RawJob, JobRequirements, employment type/seniority classifiers
- Base scraper with httpx client, context manager, retry/timeout support
- Greenhouse ATS scraper (boards-api.greenhouse.io/v1)
- Lever ATS scraper (api.lever.co/v0/postings)
- LLM-assisted JD parser with regex fallback (skills, education, experience, visa, remote)
- Job storage with deduplication (source + company + source_id)
- Batch intake orchestrator with YAML company config
- Generic filter engine: YAML-driven profiles with location/work mode rules, title keywords, employment type, seniority, description regex exclusions, experience cap
- Batch search CLI: `python -m src.intake.search --profile default`
- Default filter profile: Vancouver/Toronto all modes, US remote-only, software intern roles, excludes Canadian PR/citizenship

### Phase 2.2: Smart Filtering & Scoring
- Hard rule matching: work authorization, experience (1-year grace), education level, employment type, spam/ghost job detection
- ApplicantContext loader from profile YAML
- Skill overlap scoring with normalization and fuzzy matching (JS→javascript, K8s→kubernetes)
- TF-based keyword similarity as embedding fallback
- Cosine similarity utility for future embedding support
- Composite scorer: weighted skill overlap (must-have 70% / preferred 30%) + keyword similarity + rule bonus + quality multiplier
- Quality multiplier penalizes sparse JDs and missing apply URLs
- Ranked output with `print_ranking()` CLI helper

### Post-Review Fixes
- **P1**: Added `source_id` column to Job model for proper indexed deduplication
- **P1**: Fixed dedup query to filter by company and use source_id directly
- **P1**: Added per-job IntegrityError handling in upsert_jobs
- **P1**: Separated `coop` vs `internship` in employment type classifier
- **P1**: Replaced hardcoded year with `datetime.now().year` in experience calculation
- **P1**: Wrapped JD text in XML tags to mitigate prompt injection
- **P1**: Used Pydantic `model_validate` for LLM output validation
- **P2**: Extracted shared HTML stripping, applied to Lever descriptions
- **P2**: Fixed Greenhouse office type check for non-dict entries
- **P2**: Normalized US work auth comparison to case-insensitive
- **P2**: Weighted must-have skills higher than preferred in scorer
- **P2**: Default IGNORECASE for filter regex patterns

### Tests
- 26 filter tests (work mode inference, title/location/description/experience matching)
- 34 matching tests (rules, semantic overlap, keyword similarity, scorer ranking)

---

## [0.1.0] — 2026-04-02 — Phase 1: Infrastructure + Memory + Documents

### Phase 1.1: Project Initialization
- uv project with pyproject.toml (sqlalchemy, psycopg, pgvector, alembic, python-docx, pymupdf, etc.)
- PostgreSQL 14 + pgvector 0.7.4 installed and configured
- Alembic migrations with 5 tables: jobs, applications, applicant_profile, bullet_pool, qa_bank
- SQLAlchemy 2.0 ORM models with vector columns and FK constraints
- Config loader (YAML + .env + env var overrides, credential URL encoding)
- LLM CLI wrapper (claude -p and codex exec via subprocess, with error handling)
- Logging setup (file + console with configurable level)

### Phase 1.2: Applicant Memory Layer
- Profile YAML schema definition (`data/profile/schema.yaml`)
- Profile loader: YAML → DB ingestion with tag extraction per section
- Bullet pool: extract tagged bullets from experiences/projects, query by tag overlap
- Story bank: STAR-format stories with theme/context filtering
- QA bank: structured Q&A with canonical answers, geography/role variants, confidence, review flag
- Resume importer: .docx/.pdf → Claude CLI → structured YAML

### Phase 1.3: Document Processing Layer
- Block-based docx engine: `{{PLACEHOLDER}}` substitution + section block rebuilding
- Section rebuilders clear stale template content before inserting new data
- PDF converter: docx2pdf with LibreOffice CLI fallback
- File manager: standardized naming (`type_company_role_date.ext`) + output path management
- Template registry with auto-discovery from template directory

### Post-Review Fixes (Codex review)
- **P1**: Migration now enables pgvector extension before creating VECTOR columns
- **P1**: Fixed table creation order (jobs before applications) for FK constraint
- **P2**: Added FK constraint `applications.job_id → jobs.id` in migration and ORM
- **P2**: Percent-encode DB credentials in connection URL (handles special characters)
- **P2**: Declared `pymupdf` as explicit dependency in pyproject.toml
- **P2**: `find_answer()` now ranks by pattern overlap score, not first-of-type

---

## [0.0.0] — 2026-04-02 — Project Setup

### Added
- Initial project skeleton with directory structure
- README with architecture overview and tech stack
- Implementation plan in English (`docs/plan_en.md`) and Chinese (`docs/plan_zh.md`)
- `.gitignore` and `config/.env.example`
- Project management documentation (`docs/PROJECT_MANAGEMENT.md`)
