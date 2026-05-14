# Architecture & Design Decisions

This log captures key decisions, their rationale, and alternatives considered. Each entry is immutable once written — new decisions that supersede old ones should reference the original.

---

## D001 — Build from scratch, not fork existing projects (2026-04-02)

**Decision**: Self-built modular framework. No fork of AIHawk, get_jobs, or GodsScion as main trunk.

**Rationale**: Existing projects are tightly coupled to specific platforms, mix concerns across layers, and have high maintenance cost from platform anti-bot changes. Our system needs 7 independent layers; no existing project provides more than 2-3 of these well.

**What we borrow**:
- AIHawk: Agent architecture patterns, config organization
- get_jobs: Chinese platform action chains (deferred to future phase)
- GodsScion: Applicant profile config, QA bank design, material customization triggers

---

## D002 — Playwright over Selenium (2026-04-02)

**Decision**: Use Playwright (Python) as the browser automation layer.

**Rationale**: Better multi-context/session management, cleaner file upload and wait strategies, better DOM/network event orchestration for recoverable workflows, built-in screenshot/trace support. Selenium ecosystem is larger but Playwright is better suited for a long-term multi-site orchestration system.

---

## D003 — LLM via CLI subprocess, not API SDK (2026-04-02)

**Decision**: Invoke Claude Code CLI (`claude -p`) and Codex CLI via `subprocess.run()` instead of using Anthropic/OpenAI Python SDKs.

**Rationale**: CLI handles its own authentication (no API key management), supports context capabilities, and simplifies the dependency chain. Trade-off is slightly higher latency per call and less fine-grained control over parameters.

**Future consideration**: May add direct API SDK as a fallback if CLI latency becomes a bottleneck for batch operations.

---

## D004 — PostgreSQL + pgvector over SQLite + ChromaDB (2026-04-02)

**Decision**: Use PostgreSQL with pgvector extension from day one.

**Rationale**: Need relational integrity (foreign keys between jobs, applications, profiles) AND vector search in the same database. SQLite + ChromaDB would split data across two systems. PostgreSQL scales to production; pgvector is mature enough for our embedding dimensions (1536).

---

## D005 — Block-based resume assembly, not full-text LLM rewrite (2026-04-02)

**Decision**: Resumes are assembled from a tagged bullet pool. LLM only does light lexical rewrite on selected bullets, not full-text generation.

**Rationale**: Full-text LLM generation causes style drift, fact fabrication, and inconsistent formatting. Block-based approach keeps facts grounded (every bullet traces to a real experience), maintains consistent formatting (template-driven), and enables keyword injection without hallucination.

---

## D006 — English ATS first, Chinese platforms deferred (2026-04-02)

**Decision**: Target Greenhouse, Lever, Workday initially. Chinese platforms (Boss, Liepin, 51job, Zhilian) deferred.

**Rationale**: English ATS systems have more standardized form structures and lower anti-bot enforcement. Chinese platforms require aggressive anti-detection measures and have high maintenance cost from frequent UI changes (documented in get_jobs issues). Better to validate the full pipeline on easier targets first.

---

## D007 — uv for package management (2026-04-02)

**Decision**: Use `uv` instead of pip, poetry, or pdm.

**Rationale**: Fastest resolver, compatible with pyproject.toml standards, growing ecosystem adoption. User preference.

---

## D008 — Codex CLI for code review workflow (2026-04-02)

**Decision**: Use `codex review --uncommitted` for automated code review after each sub-phase.

**Rationale**: Provides a second-opinion review pass before committing. Catches issues that the primary developer (Claude Code) might miss. Non-blocking — findings are addressed before commit, not after.

---

## D009 — LinkedIn scraping via Playwright, not API (2026-04-03)

**Decision**: Use Playwright browser automation to scrape LinkedIn job listings, not LinkedIn's official API or third-party scraping services.

**Rationale**: LinkedIn's official Jobs API is restricted (requires partner access). Third-party scraping services add cost and dependency. Playwright approach reuses our existing browser automation stack (Phase 4), supports authenticated sessions via cookie persistence, and can extract ATS redirect URLs (the key value prop: find jobs on LinkedIn, apply via Greenhouse/Lever where our pipeline already works). Trade-off is fragility to LinkedIn DOM changes, mitigated by selector-based extraction with fallbacks.

**Key design**: LinkedIn scraper is a new scraper class under `src/intake/` following the same `BaseScraper` interface pattern. It uses Playwright (async) instead of httpx since LinkedIn requires JavaScript rendering and authentication.

---

## D010 — Web GUI: FastAPI JSON API + Vue SPA (2026-04-04)

**Decision**: Replace the server-rendered Jinja2/HTMX dashboard with a Vue SPA served by the existing FastAPI app.

**Rationale**: The GUI needed a cleaner and more controllable interaction model than the template-heavy dashboard could provide. Splitting the frontend into `frontend/` keeps the UI independent, makes the visual system easier to simplify, and preserves the existing Python backend as a thin JSON API over the current services.

**Alternative considered**: Keep the Jinja2/HTMX stack and simplify templates in place. That would have avoided adding a Node build step, but it would keep the frontend tightly coupled to server templates and make larger layout simplifications slower to iterate.

---

## D011 — Materials as a first-class web workspace (2026-04-29)

**Decision**: Treat application materials generation as its own primary route at `/materials`, not as an inline modal inside job search results.

**Rationale**: Generating application materials requires multiple user choices: job/JD source, applicant profile, material types, output formats, templates, preview, validation, and downloads. A dedicated workspace keeps the high-frequency generation path visible and separates it from search-result browsing. Job cards link into this workspace with `jobId` query state so search context is preserved without duplicating generation UI.

**Alternative considered**: Keep generation in the Jobs page. That approach made template selection and preview/download state harder to reason about and would have crowded the search-result card layout.

---

## D012 — DOCX-first template packages, not free-form renderer styling (2026-04-29)

**Decision**: Store document templates as first-class packages: `template.docx`, `manifest.json`, `style.lock.json`, and sample JSON assets. The renderer only references manifest-declared block markers and named Word styles.

**Rationale**: Word documents own the visual style. Code should assemble validated content into named blocks and styles rather than scattering font, margin, and bold overrides through the renderer. This makes uploaded templates predictable, keeps user-owned style changes in DOCX, and allows capacity/fitting rules to live beside the template that imposes them.

**Key design**: LLM/content planning produces structured IR. Deterministic renderers convert IR into DOCX and PDF. The LLM does not generate final document files.

---

## D013 — Template and artifact APIs must not expose filesystem authority (2026-04-29)

**Decision**: Validate template IDs, constrain artifact downloads to `data/output`, limit template upload size, and serialize template preview paths as project-relative/public-safe values instead of absolute paths.

**Rationale**: Template IDs and artifact paths cross the HTTP boundary. Even for a local-first app, these APIs should not allow path traversal, arbitrary large uploads, or leakage of host filesystem layout.

---

## D014 — Claude Code CLI review for final hardening (2026-04-29)

**Decision**: Use Claude Code CLI as the final review pass for this Materials/template work, while keeping Codex review as an earlier-phase practice documented in D008.

**Rationale**: The current development environment already depends on Claude Code CLI and the review found concrete security and regression issues in template IDs, LinkedIn enrichment, upload limits, parser heuristics, and cache keys. Automated review is treated as an input to engineering judgment; findings are fixed and verified with tests before commit.

---

## D015 — Tailwind v3 + shadcn-vue + reka-ui as the SPA design system (2026-04-30)

**Decision**: Adopt Tailwind v3 (with `tailwindcss-animate`), HSL CSS variables in `frontend/src/tokens.css`, and shadcn-style Vue components built on reka-ui primitives as the standard UI layer. Keep `darkMode: ["class", '[data-theme="dark"]']` so the existing dock theme switcher and the new utility classes both drive the same dark-mode state.

**Rationale**: The original SPA shipped a hand-rolled scoped-style system (`.surface`, `.button`, `.banner`, `.material-modal`, `AppSelect`, `AppIcon`, `DockIcon`, custom dropdowns, custom modals) that drifted as features were added. Switching to Tailwind + shadcn primitives gives consistent focus rings, dark-mode coverage, accessible Dialog / Select / Alert behavior, and a single token source of truth without locking the project into a heavy component library. reka-ui is chosen over a Vue-port of Radix because it is the upstream port shadcn-vue tracks and exposes the full primitive surface (Dialog portal/overlay/scroll-lock/focus-trap, Select portal/scroll-buttons, Collapsible) needed for the existing workflows.

**Migration path**: Phases A → D over 9.A through 9.D-10 in `PROJECT_MANAGEMENT.md`. Each sub-phase ships a single commit with `npm run build` verification and a code-review pass before merge to `dev`. View shells are migrated to `Card` + Lucide icons first; banners and modals follow; primitive components (`AppSelect`, `TagInput`) are rewritten last; legacy `AppIcon` / `DockIcon` are deleted once nothing references them.

---

## D016 — LLM Provider abstraction promoted ahead of cover-letter agent (2026-05-11)

**Decision**: Reorder the roadmap so that Phase 10 is "LLM Provider Abstraction" (REST adapters for OpenAI / Anthropic / Gemini + subprocess providers for Claude CLI / Codex CLI behind a `ProviderRegistry`), and the original "cover-letter agent" plan slides to Phase 14. Insert two new infrastructure phases between them: Phase 12 (caching) and Phase 13 (scheduled tasks). The "multi-agent orchestrator" idea is descoped to a batch + review-queue pattern as Phase 16.

**Rationale**: After Agent Phase 9 (form-filler) shipped, every subsequent agent phase would have been written against a hard-coded `subprocess.run(['claude', ...])` or `codex exec` call. That blocked: (a) users without the CLI tools installed; (b) future cost-control via OpenAI batch APIs or Anthropic prompt caching; (c) provider-level fallback chains. Doing the provider abstraction first means the cover-letter agent, the matching agent, and the nightly run loop all inherit the same provider plumbing for free.

**Trade-off**: pushes user-visible agent features (cover letter, filter explainability) ~5 weeks later than the original plan. Accepted because the alternative was rewriting all three agents once provider support landed anyway.

---

## D017 — No LangChain / LangGraph for agent orchestration (2026-05-12)

**Decision**: Continue evolving the in-house agent harness in `src/agent/` for Phases 14-16. Do not migrate to LangChain, LangGraph, LlamaIndex, or any equivalent framework.

**Rationale**:

1. **Heterogeneous LLM access.** AutoApply targets both REST APIs (OpenAI / Anthropic / Gemini) and CLI subprocesses (Claude CLI / Codex CLI). LangChain's `BaseChatModel` assumes HTTP + native tool-call protocol. Wrapping a CLI's stdout-parsed ReAct JSON into LangChain's `AIMessage(tool_calls=...)` would require a custom adapter per CLI and would re-break every time LangChain rev'd its agent API.
2. **HITL is a product feature, not a debugger.** The `gate/queue.py` + `/api/agent/gate/...` + Web UI is end-to-end production-grade with file-based persistence, restartability, and per-trace audit. LangGraph's `interrupt_before` is newer and less proven; the job-application domain is "wrong once is expensive" (ATS ban, mis-sent resume, PII leak) and warrants the strict gate we already have.
3. **Cost telemetry is plumbed end-to-end.** Phase 9.4 surfaces per-step `prompt_tokens / output_tokens / cost_usd` through `AgentStep → AgentResult → TraceRecord → EvalReport`, with rates configurable per provider for Phase 10. The LangChain equivalent (LangSmith) is a paid SaaS that ships data off-host.
4. **Framework churn risk.** LangChain rewrote its agent API three times in 18 months (initial AgentExecutor → LCEL → LangGraph). Each rewrite forced consumers to migrate. The in-house harness is ~1000 lines and stable.
5. **Domain mismatch.** LangChain's strengths are document loaders, vector stores, RAG templates, and chatbot patterns. AutoApply is not a chatbot and has narrow, structured RAG needs (profile + JD only) that don't justify the framework weight.

**Trade-off**: gives up the LangChain ecosystem of pre-built integrations and LangSmith hosted observability. Accepted because the integrations the project actually needs (browser tools, profile lookup, JD lookup, fact-drift check) are already in-house, and the trace store + viewer already serve the observability role locally.

**Re-evaluation trigger**: If Phase 17 reveals a genuine need for stateful multi-agent state machines (not just batch fan-out), LangGraph specifically — not full LangChain — may be reconsidered in isolation. The current Phase 17 plan uses asyncio fan-out + review queue, which does not require a framework.

---

## D018 — Adopt Redis from Phase 12 as cache / lock / queue substrate (2026-05-12)

**Decision**: Introduce Redis as a hard runtime dependency starting Phase 12. It serves three orthogonal roles: (a) L2 of the tiered cache (`src/cache/` L1 LRU + L2 Redis); (b) distributed-lock primitive for Phase 13 force-refresh and Phase 14 multi-instance scheduler; (c) future task-queue substrate. Single-node Redis with AOF persistence is the target through Phase 17. Postgres remains the source of truth for everything durable (job postings, snapshots, applications, schedules, audit).

**Rationale**:

1. **Commercial path is being preserved.** The earlier "single-user, SQLite jobstore" framing is incompatible with a hosted deployment where two `autoapply web` processes must not double-fire the same scheduled job, and where one user's force-refresh of a popular search must not stampede LinkedIn. Redis solves both with primitives (`SET NX PX` for locks, atomic INCR for quotas) that are awkward to replicate over Postgres at the call-site density these features require.
2. **L1 alone is insufficient for hosted deployments.** A pure in-process LRU loses all entries on every process restart and on every replica added behind a load balancer. Redis L2 means cache survives restarts, is sharable across replicas, and gives the Phase 12.6 inspector UI a real surface to introspect.
3. **Postgres-as-cache is the wrong tool.** Using Postgres tables for short-TTL response caching forces autovacuum to chase millions of `DELETE`d rows, contends with the OLTP workload, and lacks native TTL eviction. The 5-minute response cache and the per-tenant rate-limit counters belong somewhere ephemeral and high-throughput.
4. **Lockless force-refresh is unsafe.** Phase 13's force-refresh path scrapes LinkedIn. Without a distributed lock, two simultaneous clicks (same user on two tabs, or two users on a shared search in the commercial mode) would scrape twice, doubling the rate-limit risk. Redis `SET NX PX` is the idiomatic primitive.

**Trade-off**: Adds an operational dependency. Local-only developers must run Redis (covered by `docker-compose up`); the credential surface gains `REDIS_URL`. Accepted because the cost is small relative to the architectural simplification it brings to Phases 12-18. Memory profile: < 100 MB through Phase 17 (cache entries are mostly JSON-serialized LLM responses with 7-day TTL).

**Scope guards**: No Redis Cluster / Sentinel until a real availability requirement exists (Phase 18+, and only if a paid tier is launched). No Redis-as-source-of-truth ever -- Redis is purely derived state, must be reconstructible from Postgres.

---

## D019 — Job Index & Freshness Engine as a dedicated phase (2026-05-12)

**Decision**: Promote the previously-planned "JD / scrape caching" sub-phase (old 12.2) to a full phase (**Phase 13: Job Index & Freshness Engine**). Model the domain explicitly with five entities -- `job_postings`, `job_snapshots`, `search_queries`, `search_results`, `refresh_tasks` -- plus a `job_snapshot_id` FK on every artifact derived from a JD (`application_records`, `cover_letter_versions`, `resume_versions`, `review_queue`). Replace `src/intake/search_cache.py` (file-backed JSON) entirely.

**Rationale**:

1. **TTL eviction is the wrong abstraction for JD content.** A JD's interesting events are "the description changed" / "the role was closed" / "applicant count crossed a threshold", none of which a clock-based TTL can detect. Content-hash versioning over an immutable snapshot table is the right model: the entity (`job_posting`) persists across content edits; each scrape produces a `job_snapshot` if-and-only-if `content_hash` changed.
2. **Audit trail is a product requirement.** When a user receives an interview from an application sent six months ago, "what JD did we write that cover letter against?" must be answerable forever. The only way to guarantee this is to bind every generated artifact to a specific immutable `job_snapshot_id`. A retention-policy cache cannot offer this.
3. **The freshness state machine is shared infrastructure.** `new / active / stale / unknown / expired / archived` and the `should_refresh(job, context)` policy (with `before_submit: 6h`, `generate_materials: 24h`, `search_display: 72h` tiers) is consumed by Phase 14 (`jd_health_check`), Phase 15 (cover letter pre-gen check), Phase 16 (filter binding), and Phase 17 (pre-submit gate). Without centralizing it, four phases each reinvent it inconsistently.
4. **Search-key normalization is non-trivial and was wrong in the file cache.** The current `src/intake/search_cache.py` hashes the raw query payload; that means `currentJobId`, `origin`, `trackingId`, and pagination cursors all spuriously invalidate the cache. The new normalization layer (Phase 13.2) strips these.

**Trade-off**: Phase 13 grows to ~2 weeks and pushes Phases 14-17 each one slot later. Accepted because every downstream phase actively needs the snapshot binding and the state machine; doing them later means rewriting those phases.

**Scope guard**: Cross-source canonical dedup (a LinkedIn job ≡ a Greenhouse job ≡ the company-site job) is explicitly out of scope. Source-level uniqueness (`UNIQUE(source, source_job_id)`) is the only dedup. Cross-source identity can be added later as a `canonical_job_id` FK without schema migration of the existing entities.

---

## D020 — `tenant_id` on every new table from Phase 12 onward (2026-05-12)

**Decision**: Every table created from Phase 12 forward carries a non-null `tenant_id` column (default value `"default"` until Phase 18 activates real multi-tenancy). Every new Redis key is prefixed `tenant:{id}:`. Every new background task accepts an explicit tenant context. No exceptions, including tables that "feel global" (e.g. `refresh_tasks`, `search_queries`).

**Rationale**: Retrofitting multi-tenancy onto a populated single-tenant schema is a known nightmare: every query gets a `WHERE tenant_id = ?` audit, every Redis key gets a rename migration, every cached result gets invalidated. Doing it pre-emptively from Phase 12 -- when the new tables are still empty in production -- adds one column and ~zero developer friction. Phase 18 then becomes "fill in the middleware and RLS policies" rather than "rewrite the schema".

**Trade-off**: Every Phase 12-17 PR carries an extra `tenant_id` column and a `default` literal in seed data. Accepted as cheap insurance.

**Enforcement**: Phase 11.3 docs sync notes this rule; subsequent code review treats a missing `tenant_id` on a new table as a P1 blocker.

---

## D021 — APScheduler with Postgres jobstore (corrects earlier SQLite draft) (2026-05-12)

**Decision**: Phase 14 (Scheduled Task System) uses APScheduler with `SQLAlchemyJobStore` pointing at the project's Postgres database (the same database `src/core/config.py:129` configures). Earlier draft (`docs/PROJECT_MANAGEMENT.md` old Phase 13.1) said "APScheduler + SQLite jobstore"; that was a documentation error -- the project has never run on SQLite. Multi-instance double-fire is prevented by a Postgres advisory lock (`pg_try_advisory_lock`) acquired in the job wrapper.

**Rationale**:

1. **Match the actual stack.** The project already depends on Postgres + alembic + pgvector. Adding a separate SQLite file for the scheduler would create a second migration story and a second backup story for no gain.
2. **Multi-instance safety is required by the commercial path** (D018). APScheduler's built-in jobstore on Postgres + an advisory lock is the documented pattern; it avoids the "two web replicas fire the same nightly job twice" failure mode.
3. **The earlier SQLite framing was based on the false assumption that the app is single-user.** Once D018 / D020 land, that framing is no longer self-consistent.

**Trade-off**: One additional `apscheduler_jobs` table in the Postgres schema. Accepted -- it is small and managed entirely by APScheduler.


---

## D022 — Job Index `search_results` links are pruned after a successful refresh (2026-05-14)

**Decision**: After a successful `cached_search` refresh, `search_results` rows for the affected `query_id` whose `last_seen_at < run_started_at` are deleted via `JobIndexStore.prune_results_not_seen_since(query_id, threshold)`. The `JobPosting` row itself is kept (other queries / applications may reference it); only the link from this query is removed. `SearchOutcome.counts` carries `"removed"` alongside `"scraped"` / `"new"` so the UI banner can render "N new · M removed · K updated".

**Rationale**: The original Phase 13.4 design left obsolete links in place on the rationale that `search_results` should be "every posting this query ever returned" so the UI can diff "new vs previously-seen". `codex review --base dev` flagged this as a P2: the next `get_results(query.id)` call returns every link, so a query whose source returned fewer postings on the second run will resurface the missing ones on the next cache hit. That is exactly the kind of silent inconsistency D019's snapshot model was supposed to eliminate.

**Trade-off**: Two compositional concerns get conflated -- "what did this query return today?" (now: the truth) versus "what has this query ever returned?" (now: lost). The latter has no current consumer; if a future feature needs the history (e.g. a "stop showing me jobs I've seen before" filter), it should be added as a dedicated `posting_history` table with its own retention policy, not by leaking stale links into the live search results.

**Enforcement**: Regression test `tests/test_jobs_search.py::test_refresh_prunes_postings_no_longer_in_source` pins the invariant.
