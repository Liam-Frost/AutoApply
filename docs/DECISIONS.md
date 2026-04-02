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
