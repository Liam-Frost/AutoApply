# Changelog

All notable changes to AutoApply are documented here, organized by Phase.

## [Unreleased]

### UI Overhaul -- Phase A: Design System
- Generated the AutoApply design system spec via the `ui-ux-pro-max` agent — color palette, typography scale, spacing rhythm, and component inventory

### UI Overhaul -- Phase B: Tailwind + shadcn-vue Foundation
- Installed Tailwind v3 and `tailwindcss-animate`, configured `darkMode: ["class", '[data-theme="dark"]']`, and aliased every theme color (`background`, `foreground`, `card`, `primary`, `secondary`, `muted`, `accent`, `destructive`, `success`, `warning`, `popover`, `border`, `input`, `ring`) to HSL CSS variables
- Added the HSL token sets in `frontend/src/tokens.css` for both light and dark themes
- Added shadcn-style base components under `frontend/src/components/ui/`: `Button`, `Input`, `Label`, `Card` (+ `CardHeader` / `CardTitle` / `CardContent` / `CardFooter` / `CardDescription`), `Badge`, `Dialog` (+ `DialogContent` / `DialogHeader` / `DialogTitle` / `DialogDescription` / `DialogFooter` / `DialogClose`), `Skeleton`, and `EmptyState`

### UI Overhaul -- Phase C: View Rebuilds
- Rebased `styles.css` onto the Phase B HSL tokens; tightened core controls (button / input / chip / banner / page header) and tightened layout (workspace 1400px, denser tables, hoverable rows)
- Rebuilt every view shell with shadcn `Card` + Lucide icons: Dashboard, Applications, Settings, Materials, Profile, Jobs
- Replaced empty states with the shared `EmptyState`, switched primary actions to shadcn `Button` (default / ghost / destructive / icon variants), and added `tabular-nums` to numeric columns

### UI Overhaul -- Phase D: Primitives + a11y Polish
- Added shadcn `Alert` (+ `AlertTitle` / `AlertDescription`) with destructive / success / warning / default variants and migrated every `.banner is-*` div across all views to the new primitive
- Migrated the JobsView "Apply Materials" modal and the MaterialsView Template Library modal to reka-ui `Dialog` (portal, overlay, scroll-lock, focus-trap, built-in close button)
- Rebuilt `AppSelect.vue` as a wrapper around reka-ui Select primitives (portal, scroll buttons, animated open/close); preserved the existing `{ value, label }` API by mapping empty-string sentinels to an internal token
- Rebuilt `TagInput.vue` with shadcn-style chip pills (rounded-full, `bg-secondary`) and a flush inline `Input`; preserved the keyboard / paste / commit-on-blur behavior
- Replaced `AppIcon.vue` and `DockIcon.vue` (hand-rolled SVG dictionaries) with direct lucide-vue-next components everywhere, then deleted both files
- Migrated the dock navigation, theme toggle, and the ProfileView / JobsView / PaginationBar accordion + pagination icon-buttons to shadcn `Button` (`variant="ghost"`, `size="icon"`); destructive variants pick up `text-destructive` + `hover:bg-destructive/10`
- Added `aria-expanded` bindings to every accordion-head and editor-item-head button across ProfileView and JobsView
- Pruned dead CSS for the migrated banner / modal patterns; bundle CSS dropped from 53 kB to 52 kB

### Materials Workspace
- Added a dedicated Vue Materials page at `/materials` for job/JD selection, applicant profile selection, resume/cover letter options, template selection, preview, and artifact downloads
- Job search results now route `Generate Apply Materials` into `/materials?jobId=...` so the selected search result carries into the generation workflow
- Added Preview tabs for Resume and Cover Letter, collapsed-by-default review, validation chips, version metadata, and selected-format download links
- Moved template upload into a Template Library modal so low-frequency template management does not interrupt the core generation flow
- Removed TXT as a product-facing Cover Letter output option; DOCX/PDF are the supported UI formats

### DOCX-First Template Packages
- Added first-class template package assets under `data/templates/<document_type>/<template_id>/`
- Template packages now include `template.docx`, `manifest.json`, `style.lock.json`, and sample JSON assets
- Added default packages: `resume/ats_single_column_v1` and `cover_letter/classic_v1`
- Added template APIs for listing packages and uploading DOCX templates
- Uploaded templates are validated, assigned safe IDs, given required named styles/markers, and serialized without leaking absolute filesystem paths
- Template package writes are stable on Windows with LF newlines and trailing final newline

### Generation Pipeline
- Added structured Resume/Cover Letter IR models, evidence retrieval, template-aware fitting, artifact validation, page counting, and local generation version persistence
- DOCX rendering now prefers manifest block markers such as `{{resume.sections}}` and `{{cover_letter.body}}`
- Renderers use named Word styles from template manifests instead of ad hoc formatting overrides
- Resume fitting applies template capacity limits for sections, items, bullets, bullet length, and skill lines
- Cover letter generation now follows the same DOCX-first artifact path with validation and version metadata

### Web/API Hardening
- Added `/api/jobs/generate-material`, `/api/templates`, `/api/templates/upload`, and `/api/artifacts/download`
- Added artifact download path restrictions to `data/output`
- Added template ID validation to prevent path traversal outside `data/templates`
- Added template upload size limits before parsing DOCX content
- Restored strict search-profile ID validation at the service layer and mapped invalid DELETE requests to HTTP 400
- Added profile-aware material generation from saved applicant profiles

### Search, Intake, And ATS Fixes
- Added Ashby ATS adapter support and Ashby application URL normalization
- Hardened LinkedIn pagination, page-state probing, job-card scroll detection, primary Apply-button selection, popup cancellation, and description extraction
- Avoided double-enriching LinkedIn description-filter matches
- Restored duplicate collapse for no-keyword LinkedIn searches
- Normalized LinkedIn cache keys so keyword/filter order does not cause duplicate cache entries
- Fixed JD parser false positives for `ml`, `api`, and `data` substring matches

### Review And Verification
- Ran Claude Code CLI review, fixed all actionable findings, and rechecked the final cache-key/partition coverage fixes
- Current verification baseline: `uv run python -m pytest` -> 340 passed, 1 skipped
- Current lint/build baseline: `uv run ruff check .` and `npm run build` pass

### Packaging + Runtime Fixes
- Added package build metadata so `uv sync` installs the `autoapply` CLI entrypoint
- Added missing `itsdangerous` dependency required by FastAPI session middleware

### Apply Pipeline Fixes
- `autoapply apply` now loads a real job context from DB or ATS APIs instead of reusing the newest files in `data/output`
- Per-job resume and cover letter generation now runs inside the apply flow
- QA templates are loaded from `qa_bank` and persisted with tracked applications
- Application tracking is now created and synced during the apply flow
- Batch apply now uses the scoring layer correctly

### Web Fixes
- Dashboard and applications routes now pass template-safe stats structures
- Fixed HTMX outcome editing to call the real tracker update function
- Job search page now shows match scores when a profile is available
- Job search page now exposes an Apply action that triggers the existing pipeline

### Earlier Verification Snapshot
- `uv run autoapply --help`
- `uv run pytest -q` -> 244 passing at the packaging/runtime-fix checkpoint

## [0.7.0] -- 2026-04-03 -- Phase 7: Web GUI

### Phase 7.1: FastAPI Backend
- FastAPI app factory with Jinja2 templates, static files, session middleware
- 4 route modules: dashboard, jobs, applications, profile
- `autoapply web` CLI command with --host, --port, --reload, --no-open options
- Dependencies: fastapi, uvicorn, jinja2, python-multipart

### Phase 7.2: Dashboard Page
- Pipeline stats cards (total, pending, submitted, response rate)
- Pipeline breakdown with colored status badges
- Quick action buttons (search jobs, view applications, manage profile)
- DB connection warning when database is unavailable

### Phase 7.3: Job Search Page
- Search form with source selector (ATS/LinkedIn/All), keywords, location
- ATS and time posted filter controls
- HTMX-powered live search (partial page updates without full reload)
- Results list with ATS type badges, company, location, employment type
- "View" links to external application URLs

### Phase 7.4: Applications + Profile Pages
- Applications: pipeline stats grid, outcome breakdown, filterable table
  with inline HTMX-powered outcome editing (pending/rejected/oa/interview/offer)
- Profile: identity card, skills cloud, education/experience/projects sections
- Resume upload form for automatic profile generation via Claude CLI

### Phase 7.5: Tests
- 21 new test cases: app factory, all 4 pages, navigation, CLI integration
- Fixed Jinja2 template caching issue with TemplateResponse API
- Total test count: 228 (177 existing + 30 LinkedIn + 21 Web)

---

## [0.6.0] -- 2026-04-03 -- Phase 6: LinkedIn Integration

### Phase 6.1: LinkedIn Session Manager
- LinkedInSession: Playwright persistent context with cookie reuse for authenticated sessions
- Auto-detects login state; opens browser for manual login on first run
- Cookie persistence in `data/.linkedin_session/` avoids repeated logins

### Phase 6.2-6.3: LinkedIn Job Scraper + ATS Redirect Detection
- LinkedInScraper: search URL builder with all LinkedIn filter parameters (time, experience level, job type)
- Pagination through search results, job card extraction from DOM
- Job detail page enrichment: full description extraction
- ATS redirect detection: clicks "Apply" button to discover external Greenhouse/Lever URLs
- URL cleaning to remove tracking parameters
- Updated ATSType schema to include "linkedin"

### Phase 6.4: Pipeline Integration
- search_linkedin() async function + search_linkedin_sync() wrapper
- CLI: `autoapply search --source linkedin --keyword "swe intern" --location "US"`
- New CLI options: --source (ats/linkedin/all), --keyword, --location, --time-filter, --max-pages, --no-enrich, --headless
- Combined ATS + LinkedIn results in "all" mode
- LinkedIn URL detection in apply command with helpful redirect message

### Phase 6.5: Tests
- 30 new test cases covering URL utilities, search URL builder, schema integration, CLI integration, mocked Playwright parsing, filter constants
- Total test count: 207 (177 existing + 30 new)

---

## [0.5.0] -- 2026-04-03 -- Phase 5: CLI + Tracking + Full Pipeline

### Phase 5.1: CLI Framework + Init Wizard
- Click command group with 4 commands: `autoapply init`, `search`, `apply`, `status`
- `autoapply init` wizard: config validation, DB connection + migration, profile import (YAML / resume parse / template), LLM CLI availability check
- `autoapply search` wraps intake layer with Click interface, adds --score for profile-based ranking
- Entry point: `[project.scripts] autoapply = src.cli.main:main`
- ASCII-safe output for Windows console compatibility

### Phase 5.2: Application Tracking
- tracker/database.py: Application CRUD, state machine sync to DB, outcome updates, filtered queries, joined queries
- tracker/analytics.py: Pipeline stats, outcome breakdown (response/positive rate), per-company stats, per-platform stats, daily activity timeline
- tracker/export.py: CSV export (error_log excluded by default), formatted text status report
- Application model extended: state_history, fields_filled/total, files_uploaded, updated_at, outcome_updated_at

### Phase 5.3: Apply + Status Commands
- `autoapply apply --url` / `--job-id` / `--batch`: single or batch application pipeline
- Batch mode: search -> score -> rate-limited apply with proper result tracking
- `autoapply apply --dry-run`: generate materials without browser
- `autoapply status`: analytics dashboard with pipeline/outcome/platform/company stats
- `autoapply status --export-csv`: export to CSV

### Post-Review Fixes (Codex review: 3 P1, 6 P2, 2 P3)
- **P1**: Alembic migration failure now correctly returns error
- **P1**: _execute_application returns ApplicationResult; batch only records submitted apps
- **P1**: UUID validation before DB job lookup
- **P2**: Sanitized DB connection errors in CLI output
- **P2**: tracker uses flush() not commit() for caller-owned transactions
- **P2**: submitted_at preserved on re-sync (only set when None)
- **P2**: CSV export excludes error_log by default
- **P2**: Resume/cover selection by most recent mtime

### Tests
- 21 CLI/tracker tests (command structure, init wizard, ATS detection, tracker CRUD, analytics, export)
- Total: 177 tests passing

---

## [0.4.0] — 2026-04-02 — Phase 4: Browser Automation + Form Filling

### Phase 4.1: Core Infrastructure
- Application state machine (FSM) with 11 states, validated transitions, audit trail
- Playwright browser manager: async context manager, anti-detection (configurable sandbox), random delays, screenshot capture

### Phase 4.2: Form Detection & Filing
- Form field detector: text, email, tel, select, checkbox, radio (grouped by name), textarea, file inputs
- Scoped detection: form_selector parameter constrains scanning to ATS form container
- Profile-to-field mapper: label keyword matching for identity, education, links, with QA fallback
- Multi-strategy file uploader: direct selector → auto-detect by label → file chooser dialog
- File extension allowlist validation (pdf, docx, doc, rtf, txt)

### Phase 4.3: ATS Adapters
- Abstract BaseATSAdapter with full apply() workflow: open → fill → upload → answer → review/submit
- GreenhouseAdapter: #application_form scoped, resume/cover selectors, custom questions, #submit_app
- LeverAdapter: .application-form scoped, .resume-upload, custom questions, submit with postings-btn
- Submit verification: wait for networkidle + check for error indicators before advancing FSM

### Phase 4.4: Rate Limiting & Anti-Detection
- RateLimiter: random action delays, error cooldowns, hourly application caps
- Concurrency-safe (asyncio.Lock) for all state mutations
- Configurable via settings.yaml (min_delay, max_delay, cooldown_on_error, max_applications_per_hour)

### Post-Review Fixes (Codex review: 3 P1, 7 P2, 2 P3)
- **P1**: Fully qualified CSS selector paths to prevent wrong-field targeting
- **P1**: File upload extension allowlist to prevent arbitrary file exfiltration
- **P1**: Submit verification — check for error indicators before marking as SUBMITTED
- **P2**: Added checkbox and radio button detection to form scanner
- **P2**: Scoped form detection to ATS form container (Greenhouse & Lever)
- **P2**: CSS attribute escaping in label lookup and selector generation
- **P2**: asyncio.Lock for rate limiter concurrency safety
- **P2**: Removed --no-sandbox default from browser launch args

### Tests
- 43 execution tests (state machine transitions, form mapping, rate limiter, ATS adapter workflows)
- Total: 156 tests passing

---

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
