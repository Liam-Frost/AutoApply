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

**Re-evaluation trigger**: If Phase 16 reveals a genuine need for stateful multi-agent state machines (not just batch fan-out), LangGraph specifically — not full LangChain — may be reconsidered in isolation. The current Phase 16 plan uses asyncio fan-out + review queue, which does not require a framework.
