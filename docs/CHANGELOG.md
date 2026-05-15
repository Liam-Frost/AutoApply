# Changelog

All notable changes to AutoApply are documented here, organized by Phase.

## [Unreleased]

### Roadmap Update: Task Queue + Materials Generation v2

- Re-planned Phase 14 from a scheduler-only phase into **Task Queue +
  Scheduled Work**: Redis is queue transport, Postgres is durable task
  state, workers own ack/nack/retry/heartbeat/concurrency, and agents
  run inside one bounded task with structured outcomes.
- Re-planned Phase 15 from cover-letter-only work into **Resume & Cover
  Letter Generation v2**: original editable resumes get a patch mode;
  newly generated resumes become LaTeX-first template packages with
  manifests/adapters; cover letters stay snapshot-bound and
  fact-checked.
- Added architecture decisions D023 and D024 to pin the queue/agent
  boundary and the materials-generation template contract.

### Roadmap v3.1 calibration (2026-05-14)

- **Phase 14 is now Celery 5.x-based** (D025). The originally-planned
  self-built task model + queue transport + worker runtime is dropped
  in favor of Celery 5.x + Redis broker + Celery Beat. AutoApply
  layers a thin AutoApplyTask base class on top for agent boundary +
  HITL + trace + tenant context. APScheduler is retired (D021 is
  superseded by D025).
- **Phase 13.9** (D026) lands a one-shot `tenant_id` retrofit
  migration on every legacy table before Phase 14 begins so D020's
  discipline becomes schema-enforced rather than just review-enforced.
- **HITL gate backend** moves from the single-process file backend in
  `src/agent/gate/queue.py` to a Postgres `gate_queue` table folded
  into Phase 14, so Phase 17's review queue does not have to reinvent
  it.
- **Phase 15.3 LaTeX scope** clarified — `src/documents/latex_engine.py`
  already exists, so Phase 15 is "template package spec + manifest +
  adapter conventions on top of an existing engine," not "build LaTeX
  from scratch."
- **Phase 18** plan call-out: 18.2 auth middleware, 18.4 Redis
  namespace refactor, and 18.7 credential store are honestly net-new
  construction rather than "activate existing work."

### Phase 13.9: `tenant_id` retrofit migration

Per D026: lands one alembic migration giving every legacy table from
Phase 11 and earlier a `tenant_id TEXT NOT NULL DEFAULT 'default'`
column with backfill, so D020's discipline ("every new table from
Phase 12 onward carries `tenant_id`") becomes a schema-level guarantee
before Phase 14 begins.

- **Migration `d8a5c2f1e9b3`** adds `tenant_id` to `jobs`,
  `applications`, `applicant_profile`, `bullet_pool`, `qa_bank` and
  backfills existing rows. ORM models in `src/core/models.py` add the
  field; `TENANT_DEFAULT` is moved to module-top for reuse. Existing
  query paths are intentionally not forced to filter — they keep
  today's global-read behavior — but every new Phase 14+ code path
  must thread an explicit tenant context. The "default tenant"
  fallback persists until Phase 18 auth middleware + RLS take over.
- 7 new tests in `test_phase_13_9_tenant_id_retrofit.py`: per-table
  invariants + a `Base.metadata` catch-all that fails if any future
  table lands without the column + migration-file metadata check.
- Verification: 1022 passed, 1 skipped on dev (`pytest -q`); `ruff
  check` clean; `codex review --uncommitted` returned no findings;
  `alembic upgrade head` moved dev DB to revision `d8a5c2f1e9b3`.
  (commits `ae46a39` + roadmap docs `0c8ec95`)

### Phase 14: Task Queue + Scheduled Work (Celery 5.x)

Production-grade task execution substrate built on Celery 5.x.
AutoApply layers an "agent boundary + HITL + trace + tenant context"
wrapper on top; D023's principle ("queue owns execution reliability;
agents own bounded decisions") is preserved.

- **14.1 Celery wiring + skeleton** -- `celery_app = Celery(
  "autoapply", broker=REDIS_URL, backend=REDIS_URL)` with the D025
  reliability commitments: `task_acks_late=True`,
  `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1`
  (long-task model — do not prefetch). Four queues (`search`,
  `materials`, `application`, `maintenance`) with a router that maps
  task-name prefix → queue; unknown prefixes fall back to
  `maintenance`. JSON-only serialization. `redbeat_redis_url` +
  namespace pre-configured for 14.5/14.10. +15 tests. (commit
  `83de0db`)

- **14.2 Durable `tasks` audit table** -- migration `e1b4f72c8a05`.
  Postgres is the source of truth; Celery's result backend is
  transient. Lifecycle signals (`task_prerun` / `task_postrun` /
  `task_failure` / `task_retry` / `task_revoked`) plumb state into
  this table; handlers tolerate missing rows and swallow exceptions
  so an audit bug never poisons a worker. +11 tests. (commit
  `259c892`)

- **14.3 `AutoApplyTask` base class** + tenant ContextVar in
  `src/tasks/context.py`. `call_agent(fn, *args, **kwargs)` runs a
  bounded agent and normalises any return shape into `AgentDispatch`
  with one of five outcomes (`success` / `failed_retryable` /
  `failed_terminal` / `needs_human` / `needs_followup_task`).
  `short_circuit_if_already_succeeded` handles idempotency-key
  replay. Static `enqueue(celery_task, session, EnqueueSpec)`
  atomically writes the audit row and dispatches. +17 tests. (commit
  `8b5fb4c`)

- **14.4 HITL gate moved to Postgres `gate_queue`** -- migration
  `f2c5d83a91b6`. Replaces the single-process file backend in
  `src/agent/gate/queue.py` (kept as compat for one release per
  D026). `open_request` flips the linked task to `waiting_human` and
  the worker is released immediately — no thread parking.
  Double-approve returns the existing decision (UI double-click is
  not a 409); approve-then-reject is a real conflict. +10 tests.
  (commit `880887a`)

- **14.5 Celery Beat schedule** retires APScheduler. Six entries in
  `src/tasks/beat.py`: `daily_search` (02:00 UTC) → `search` queue;
  `jd_health_check` (hourly), `application_status_sync` (every 6h @
  :15), `linkedin_cookie_refresh` (03:00 UTC daily), `cache_eviction`
  (hourly @ :30), `gate_expire_sweep` (every 15min) → `maintenance`.
  `install(celery_app)` wires `RedBeatScheduler` for multi-instance
  leader election. +7 tests. (commit `12e3b21`)

- **14.6 12 concrete task kinds** in `src/tasks/tasks.py`. Each is an
  `AutoApplyTask` wrapper with a Pydantic payload model; malformed
  payload raises `TypeError` which Celery treats as terminal (no
  retry storm). Worker-driven: `search.refresh`, `jobs.enrich`,
  `materials.generate`, `application.{prepare,fill,submit}`.
  Beat-driven: `search.daily_fanout`, `maintenance.{status_sync,
  jd_health_check,linkedin_cookie_refresh,cache_eviction,
  gate_expire_sweep}`. Bodies log-and-return-stub today; Phase 15 /
  17 swap bodies without changing task name or payload contract.
  +32 tests under Celery eager mode. (commit `f01cab5`)

- **14.7 CLI command groups** -- `autoapply worker -Q queues -c N`
  validates `-Q` against the four-queue allowlist (a typo errors
  immediately); `--check` prints the resolved Celery invocation
  without starting anything. `autoapply beat` selects
  `RedBeatScheduler`. `autoapply tasks list/inspect/retry/cancel/
  kinds` reads the 14.2 audit table; retry refuses non-failed/
  cancelled rows; cancel refuses non-queued rows. `autoapply
  schedule list/run-now` reads/dispatches Beat entries. +10 tests.
  (commit `ef59570`)

- **14.8 Web JSON API + minimal SPA view** -- `src/web/routes/
  tasks.py` adds `GET/POST /api/tasks`, `GET /api/tasks/{id}`,
  `POST /api/tasks/{id}/{cancel,retry}`, `GET /api/schedule`, `POST
  /api/schedule/{name}/run-now`, `GET /api/gate?status=...`, `GET
  /api/gate/{id}`, `POST /api/gate/{id}/{approve,reject}`. Every
  route scoped by `x-autoapply-tenant`; cross-tenant queries return
  404. `frontend/src/views/TasksView.vue` adds the `/tasks` page
  with three sections (gate awaiting human, recent tasks, Beat
  schedule). Frontend rebuilt clean (vite 5.73s, 125kB gzip). +14
  tests. (commit `edb8661`)

- **14.9 Task-shape trace integration** -- `src/tasks/trace.py`
  hooks `task_prerun` / `task_postrun` / `task_failure` /
  `task_retry` to write a `TraceRecord` per attempt and stamp the
  `trace_id` onto the audit row at prerun. Child tasks dispatched
  with `x-autoapply-parent-trace` inherit `parent_trace_id` for the
  viewer chain. Persistence is best-effort: a failed `save()` logs
  and swallows. +8 tests. (commit `b7ecb57`)

- **14.10 Postgres advisory-lock backstop** -- `src/tasks/locks.py`
  adds `with advisory_lock(session, key)`, a non-blocking
  `pg_try_advisory_xact_lock` wrapper for deployment-wide critical
  sections. Auto-releases on commit/rollback/connection drop. Key
  is a SHA256-derived 63-bit signed int. +4 tests. (commit `707d94e`)

- **codex review fixes** (two rounds, P1 + P2):
  - **P1 cancel-revoke**: cancel routes (web + CLI) now call
    `celery_app.control.revoke(celery_task_id, terminate=False)`
    before flipping the row, so a worker cannot still claim the
    queued message.
  - **P2 universal audit**: a new `before_task_publish_handler` in
    `src/tasks/audit.py` writes a `queued` row for every Celery
    dispatch (Beat ticks, raw `send_task`, retries) so they all show
    up in `/api/tasks` and `autoapply tasks list`. `AutoApplyTask.
    enqueue` opts out via the `AUDIT_OK_HEADER` because it has
    already written the row with `idempotency_key` +
    `parent_task_id`.
  - **P2 cancelled-terminal**: all four lifecycle handlers
    (`prerun` / `postrun` / `failure` / `retry`) respect `cancelled`
    as terminal so the audit row preserves operator intent even in
    the revoke-vs-claim race.
  - 11 new tests in `test_tasks_codex_review_fixes.py`. (commit
    `3de7084`)

Verification: 1161 passed, 1 skipped on `feat/phase-14`; `ruff check`
clean; frontend build clean; migrations `e1b4f72c8a05` +
`f2c5d83a91b6` applied; `codex review` returned no findings on second
pass.

### Phase 15: Resume & Cover Letter Generation v2

Rebuilds materials generation around two explicit resume modes
(D024): patching the user's original source when possible, and
LaTeX-first generation when creating a new resume from a template.
Cover-letter generation moves through a bounded agent with a
fact-drift post-guard and a five-tier deterministic fallback ladder.
HITL gates only fire for persistent grounding mutations -- one-shot
generation never blocks.

- **15.1 Source-resume table** -- migration `a3b9d52e7c41`;
  `source_resumes` (tenant_id required per D026, source_type CHECK
  IN docx/latex/pdf, editable BOOL, checksum SHA256 unique per
  tenant, storage_path project-relative, extracted_structure JSONB,
  size_bytes, notes). `src/generation/source_resume.py` ingests files
  under `data/source_resumes/<tenant>/<checksum><ext>`, dedupes,
  extracts shallow structure per type (DOCX paragraphs, LaTeX
  sections, PDF headings via pymupdf), rejects traversal in
  resolve_storage_path. +18 tests. (commit `4e95e98`)

- **15.2 DOCX patch mode** -- `src/generation/docx_patch.py` mutates
  runs in place to preserve font/size/bold/italic + named styles.
  Operations: summary, skills, bullet (List Bullet swap with surplus
  appended via XML clone + deficit blanked), section_drop (only
  blanks IR-empty sections; populated IR sections always kept).
  Top-level vs sub-heading distinction so bullets nested under
  Heading 2 job entries are reachable. PatchFallback exception
  signals route-to-template per D024. +9 tests. (commit `697bd3d`)

- **15.3 LaTeX template package spec** -- TemplateManifest grows an
  optional `latex: LatexConfig` sub-model. LatexFieldMapping declares
  IR-field -> LaTeX command + arity. `src/documents/latex_manifest.py`
  exposes the shared `escape_latex` / `resolve_field` /
  `render_command` / `validate_assets` / `validate_field_coverage`
  helpers. +37 tests. (commit `ef81afe`)

- **15.4 Manifest-adapter LaTeX renderer** --
  `src/documents/latex_renderer.py` renders user-uploaded LaTeX
  with custom commands via the field_mappings table. Templates
  declare `{{resume.commands}}`; missing fields skip their command
  (no `\cmd{}` rendering visibly empty). `compile_via_manifest`
  honors `compile_engine` and preserves asset subdirectories.
  +13 tests. (commit `57de801`)

- **15.5 Materials router** -- `src/generation/materials_router.py`
  dispatches `patch_existing` vs `generate_from_template`. Every
  outcome carries MaterialsBindings (job_snapshot_id,
  source_resume_id, template_package_id, profile_version, trace_id,
  tenant_id) for Phase 17 review queue + trace viewer audit binding.
  SourceResumeView keeps the router decoupled from SQLAlchemy.
  +15 tests. (commit `e86f15d`)

- **15.6 `jd_lookup` agent tool** -- `src/agent/tools/jd.py`
  read-only dotted-path access to a bound JobSnapshot. Empty path
  returns a section index; nested paths drill into JSONB with
  `_count`/keys summaries; missing paths report available keys.
  +18 tests. (commit `95c8efb`)

- **15.7 AgentCoverLetter + fact-drift post-guard** --
  `src/generation/fact_drift.py` (number drift blocking with
  10k<->10000 normalization; entity drift warning; length sanity)
  and `src/generation/agent_cover_letter.py` orchestrator with
  five-tier fallback ladder (deterministic_only / agent_ok /
  agent_drift_fallback / agent_error_fallback). Bounded-agent loop
  itself is wrapped by AutoApplyTask.call_agent in the materials
  task body. +21 tests. (commit `983a5a5`)

- **15.8 Template adapter assistant** -- `src/documents/template_adapter.py`
  scans `\newcommand` declarations + `\foo{...}` usages, matches
  against curated conventional name table, warns on unmatched,
  errors on missing `{{resume.commands}}`, runs sample render.
  finalize_proposal gates persistence on sample_render_ok + no
  error notes + assets validating. +15 tests. (commit `98eacad`)

- **15.9 Eval suites** -- three new suites
  (materials_docx_patch / materials_latex_template / cover_letter)
  with JSON fixtures + runners in `src/agent/eval/runner.py`. Two
  new scorer types (json_field_equals, json_field_contains) walk
  dotted paths into parsed envelopes. 7 fixtures + 7 verification
  tests. (commit `488b23d`)

- **15.10 HITL gate triggers** -- `src/generation/gate_triggers.py`.
  is_gateworthy(kind) returns True only for persistent grounding
  mutations (bullet_pool_mutation / story_bank_mutation /
  template_manifest_persist); one-shot generation never gates.
  propose_* helpers open Phase 14.4 gate_queue rows with
  operator-friendly summaries; find_pending_for_task lists blocking
  gates. +14 tests. (commit `439d2d7`)

- **codex review fixes** (one round, P2): legacy LaTeX templates
  without a Phase 15.3 latex block now fall back to the existing
  placeholder renderer in `latex_engine` instead of returning
  decision='unsupported'; PDF source-resume ingest captures
  `len(doc)` inside the pymupdf `with` block so page_count survives
  close; `compile_via_manifest` preserves manifest asset
  subdirectories (`images/logo.png` -> `workdir/images/logo.png`,
  not flattened). 5 new tests; existing 'unsupported' assertion
  updated. (commit `9b813a3`)

Verification: 1332 passed, 1 skipped on `feat/phase-15`; `ruff
check` clean; alembic upgraded dev DB to revision `a3b9d52e7c41`;
`codex review` returned no findings on second pass.

### Phase 13: Job Index & Freshness Engine

Replaces the file-backed ``src/intake/search_cache.py`` with a proper
**Job Intelligence Database**: typed entities, content-hashed
snapshots, search-query cache, freshness state machine, and audit
binding from generated materials back to the exact JD snapshot they
were produced from. Foundation for Phase 14 / 15 / 17.

- **13.1 Job Index schema** -- alembic migration ``c7d3a91b4e2f``
  adds ``job_postings``, ``job_snapshots`` (unique by
  `(posting_id, content_hash)`), ``search_queries`` (unique by
  `(tenant_id, source, normalized_key)`), ``search_results``
  (CASCADE on parent delete), ``refresh_tasks`` (composite index on
  `(tenant_id, status, priority, scheduled_for)`).
  ``applications.job_snapshot_id`` FK + index added for audit
  binding. ``latest_snapshot_id`` on the posting created with
  ``use_alter`` to break the bootstrap cycle. Every new table carries
  ``tenant_id`` with server_default 'default' per D020. ORM models
  in ``src/core/models.py`` mirror the migration's uniques + indexes
  via ``__table_args__``; smoke tests in
  ``tests/test_job_index_models.py`` guard the invariants. +9 tests.
  (commit ``c0f4ea4``)

- **13.2 Search-key + content-hash normalization** -- pure-function
  module ``src/jobs/normalize.py``. ``normalize_search_key()`` strips
  LinkedIn / generic tracking params (``currentJobId``, ``origin``,
  ``trk*``, ``lipi``, ``lici``, ``utm_*``, ``gclid``, ``fbclid``);
  strings are stripped + collapsed + lowercased; lists are sorted and
  de-duplicated (including lists of dicts via stable JSON form);
  empty / None / [] are dropped. Keys preserved verbatim so
  LinkedIn's camelCase ``geoId`` / ``sortBy`` survive. The blacklist
  is authoritative, not the whitelist, so new ATS-specific filters
  work without code changes. ``search_query_fingerprint()`` SHA256s
  the normalized dict for the ``normalized_key`` column.
  ``normalize_job_content()`` + ``content_hash()`` exclude
  ``UNSTABLE_CONTENT_FIELDS`` (``applicant_count``, ``promoted``,
  ``view_count``, scrape timestamps, ``current_job_id``). +15 tests.
  (commit ``3f55c45``)

- **13.3 Freshness state machine** -- ``src/jobs/state.py``
  centralizes the ``new → active → stale → unknown → expired →
  archived`` lifecycle. ``next_state(current, event)`` is the
  caller-driven transition table; illegal transitions raise
  ``IllegalTransitionError``. ``project_by_time()`` is the pure
  time-decay projection used by the Phase 14 ``jd_health_check``
  job (``active→stale @24h``, ``stale→unknown @72h``,
  ``unknown→expired @7d``; ``new`` / ``expired`` / ``archived`` are
  excluded from decay; missing ``last_checked_at`` is a no-op).
  ``is_safe_to_apply(state)`` is the single Phase 17 pre-submit gate
  -- only ``active`` qualifies. +18 tests. (commit ``86b8b2e``)

- **13.4 Cache-first search flow with distributed lock** --
  ``src/jobs/store.py`` (``JobIndexStore``) is the persistence facade
  over the ORM models; methods take a live ``Session`` and never
  commit. ``src/jobs/search.py`` (``cached_search()``) is the
  orchestrator: normalize params → upsert ``SearchQuery`` → cache hit
  if ``status="fresh"`` and within the freshness window → otherwise
  acquire a Phase 12 distributed lock keyed
  ``jobs:search:{source}:{fingerprint}`` → re-check inside the lock
  → call ``fetch_fn`` (sync or async) → persist as ``search_results``
  rows → mark query ``fresh``. Lock contention returns the cached
  rows with ``stale=True``. On scrape failure the old cache is
  preserved, the query flips to ``stale`` with ``last_error``, and
  ``outcome.refresh_failed=True`` so the UI can flag the degraded
  read. +10 tests including real Redis (fakeredis) lock contention.
  (commit ``ce6bac9``)

- **13.5 Snapshot-versioned enrichment** -- ``src/jobs/enrich.py``
  implements ``scrape → normalize → content_hash → if hash matches
  latest_snapshot: no-op, else insert new immutable JobSnapshot row``.
  Existing snapshots are NEVER mutated; that immutability is what
  makes the ``applications.job_snapshot_id`` audit binding
  load-bearing. ``on_content_changed`` is the decorator-style listener
  hook (Phase 14 will queue follow-up scrapes when must-haves shift;
  Phase 17 will flag related applications for review). Listener
  exceptions are logged and swallowed so a buggy subscriber can't
  break enrichment. ``mark_refresh_failed`` / ``mark_source_404`` are
  the documented transient / 404 transitions. +9 tests covering
  expired→active recovery and listener fault-tolerance.
  (commit ``8f2d0f9``)

- **13.6 Context-aware freshness predicate** --
  ``should_refresh(posting, context, now=)`` in
  ``src/jobs/freshness.py`` returns a
  ``FreshnessVerdict(should_refresh, reason, age_hours, budget_hours)``
  so callers can both gate behaviour and surface "why" to the UI or
  trace store. Three documented contexts: ``search_display=72h``,
  ``generate_materials=24h``, ``before_submit=6h``. ``new`` (no
  snapshot) and ``unknown`` / ``expired`` / ``archived`` (degraded /
  terminal) always refresh. State governs lifecycle; this predicate
  judges time; the two axes compose. +18 tests across each context's
  window boundary and the state overrides. (commit ``6aaf3a4``)

- **13.7 Web UI freshness banner** --
  ``POST /api/jobs/index/freshness`` returns
  ``{known, status, last_run_at, last_success_at, last_error,
  result_count, age_hours, ...}`` (falls back to ``{known:false}``
  when the migration hasn't been applied);
  ``POST /api/jobs/index/refresh`` enqueues a high-priority
  ``kind="search.refresh"`` task that the Phase 14 scheduler will
  consume; ``GET /api/jobs/index/posting/{id}?context=...`` for the
  per-posting verdict. Frontend
  ``frontend/src/components/JobIndexBanner.vue`` renders
  "Last updated 18h ago · N indexed" plus a [Refresh] button.
  ``JobsView.forceRefreshSearch()`` clears ``lastFetchSignature`` so
  the next search() bypasses the canReuseFetchedResults shortcut.
  Application module ``src/application/job_index.py`` owns the
  session lifecycle and degrades gracefully on ``ProgrammingError``.
  +6 FastAPI tests. (commit ``eac302d``)

- **13.8 Legacy file-cache import + removal** --
  ``src/jobs/legacy.import_legacy_file_cache(store, legacy_dir,
  delete_after_import)`` walks ``data/cache/linkedin_search/*.json``
  and replays each file as one ``SearchQuery`` row (status='stale' so
  the next real search re-scrapes -- we don't trust historical disk
  data) plus one ``SearchResult`` link per contained job; idempotent
  across re-runs. ``clear_indexed_searches()`` replaces the legacy
  ``clear_linkedin_search_cache()`` (cascades ``search_results`` via
  the FK). New CLI: ``autoapply jobs import-legacy-cache
  --legacy-dir --delete``. ``src/intake/search_cache.py`` is deleted;
  ``src/intake/search.py`` removes the file-cache short-circuit. The
  ``TestLinkedInSearchCache`` class in ``tests/test_linkedin.py`` is
  removed; equivalent coverage lives in ``test_jobs_normalize.py`` +
  ``test_jobs_search.py``. End-to-end wiring of ``search_linkedin``
  into ``cached_search`` is deferred to Phase 17's daily run loop
  per the in-code comment. +6 tests. (commit ``99e2dea``)

- **fix (codex P2)**:
  ``JobIndexStore.prune_results_not_seen_since(query_id, threshold)``
  deletes ``search_results`` rows whose ``last_seen_at < threshold``.
  ``cached_search()`` captures ``run_started_at`` before ``fetch_fn``
  and prunes immediately after persisting the fresh links, so
  postings missing from the new scrape lose their link instead of
  replaying on the next cache hit. ``outcome.counts`` carries
  ``"removed"`` alongside ``"scraped"`` / ``"new"`` so the UI banner
  can surface "N new · M removed · K updated". +1 regression test.
  (commit ``aacde6d``)

**Phase 13 close**: 1004 passed, 1 skipped on ``feat/phase-13`` after
the codex fix; ``ruff check`` clean; frontend builds clean.

### Phase 12: Cache Infrastructure (Redis)

First introduction of Redis as the L2 cache substrate. Builds the
generic cache + lock + queue primitives that Phases 13, 14, 17, and
18 will consume. Scope is deliberately narrow: LLM and embedding
responses only -- JD content caching ships in Phase 13 because it
needs content versioning, not TTL eviction.

- **12.1+12.2 Cache infrastructure + Redis L2 backend** -- `src/cache/`
  module (``CacheBackend`` ABC, ``LRUBackend`` for L1, ``RedisBackend``
  for L2, ``Cache`` orchestrator with namespace TTLs `llm:7d`,
  `embedding:30d`, `response:5m`, version-stamped keys), Redis
  connection management with graceful degrade (malformed URLs, DNS
  failures, transport errors all degrade to L1-only with a logged
  warning), ``autoapply redis ping/info/flush`` CLI (all
  ``--json``-friendly, exit-non-zero on failure, destructive ops
  gated on ``--yes``, namespace validated against glob injection),
  and a ``docker-compose.yml`` with Redis 7.2 + AOF + maxmemory cap.
  The cache singleton retries L2 attachment every 30s so a
  Redis-down-at-boot deployment recovers without a process restart.
  +109 tests (836 total).

- **12.3 Distributed lock primitive** -- ``cache.lock(key, ttl=600,
  blocking=False)`` in ``src/cache/lock.py`` on Redis ``SET NX PX``
  with WATCH/MULTI/EXEC compare-and-delete release (chosen over
  Lua ``EVAL`` because fakeredis EVAL is unreliable across
  platforms). Tokens are uuid4 + ``secrets.token_hex`` so a stale
  process cannot release a successor's lock. Lock keys live in
  their own ``lock:`` prefix to avoid colliding with cache value
  keys. Process-local ``threading.Lock`` fallback when L2 is
  unavailable OR when Redis raises mid-acquisition. +15 tests.

- **12.4 Opt-in LLM response caching** -- ``generate_text(cache=True)``
  wraps the call with an L1+L2 lookup. Cache key is SHA256 over
  ``provider + model + base_url + system + prompt + output_format``;
  the model + base URL come from the registered provider so an
  API-key model swap or endpoint change invalidates the cache
  automatically. Only the primary provider's successful responses
  are cached -- caching a fallback would keep replaying the
  fallback's answer after the primary recovered. Cache failures
  swallow at debug level so the LLM call never breaks on a Redis
  blip. +12 tests.

- **12.5 Cache-wrapped OpenAI embeddings** -- ``embed_text(text)``
  in ``src/matching/semantic.py``. Default ``cache=True`` (embeddings
  are deterministic given ``model + base_url + text``); 30-day TTL.
  ``ApiKeyProvider.get_api_key`` resolves the API key (credentials
  > ``OPENAI_API_KEY`` env). Graceful degrade to ``None`` on any
  failure (provider missing, HTTP error, malformed JSON shape) so
  callers fall back to keyword matching. +20 tests.

- **12.6 Cache inspector UI** -- New page at ``/settings/cache``
  rendering Redis health, per-namespace entry counts, hit-rate,
  $-saved estimate, and one-click namespace clear behind a modal
  confirmation. New endpoints ``GET /api/cache`` (snapshot) and
  ``DELETE /api/cache/{namespace}`` (requires ``{confirm: true}``).
  Both run their SCAN+DEL paths off the FastAPI event loop via
  ``asyncio.to_thread``. The clear path drives its own SCAN+DEL
  rather than ``RedisBackend.clear_namespace`` so transport
  failures surface as ``clear_failed`` instead of looking like a
  successful 0-key clear. Frontend ``request()`` helper now
  attaches the parsed body to thrown errors so structured FastAPI
  ``detail`` objects don't render as ``[object Object]``. +19 tests.

- **12.7 Cost dashboard upgrade** -- ``AgentStep.cached`` derived
  from ``llm_attempts[0]``. ``AgentResult`` exposes
  ``cached_step_count`` / ``fresh_step_count`` /
  ``total_cost_usd_fresh`` / ``total_cost_saved_usd`` so the trace
  viewer can render "N fresh + M cached" with a ``saved $X.XXXX``
  pill. Legacy traces (pre-Phase-12.7) fold ``step_count`` /
  ``total_cost_usd`` into the fresh totals so the partition
  invariant (cached + fresh = step_count) holds. +12 tests.

**Total**: +187 tests across the phase (727 -> 927, +200 including
trace serialisation coverage). ruff clean. Frontend builds clean.
Codex review ran on every sub-phase; final pass on each was clean.

### Phase 11: Reliability & Cleanup

Tightens the Phase 10 provider layer and ships the upgrade migration
tool. Sub-phases landed independently on `feat/phase-11`; merged to
`dev` as one Phase.

- **11.1 Provider fallback chain** -- `generate_text()` now accepts an
  ordered chain (`fallback_providers: [a, b, c]` in `config/settings.yaml`
  in addition to the legacy scalar `fallback_provider`). Errors are
  classified into a `ProviderErrorKind` enum (`auth`, `quota`, `network`,
  `timeout`, `server`, `bad_request`, `parse`, `unknown`) and only
  transient kinds advance to the next provider -- retrying a malformed
  prompt on a second provider just burns money on the same failure. The
  per-call attempt list (`{provider, ok, kind, error, latency_ms}`) is
  exposed via the `src.utils.llm.last_attempt_chain` ContextVar and
  carried onto each `AgentStep.llm_attempts` so the trace viewer can
  show which provider actually answered. `config/settings.yaml` flips
  `allow_fallback: true` now that the chain actually classifies failures.
  +25 tests (705 total).
- **11.2 `autoapply migrate` CLI** -- one-shot upgrade tool for legacy
  credential and settings artifacts. Detects stale
  `managed_by: codex-cli` breadcrumbs, subprocess providers carrying
  dead stored secrets, credential rows for ids the registry no longer
  knows, and the legacy `llm.provider` / scalar `llm.fallback_provider`
  keys. Default is dry-run; `--apply` performs fixes and writes
  `.bak.YYYYMMDDTHHMMSSZ` snapshots beside the originals. `--json` emits
  a stable envelope for automation. +13 tests (718 total).
- **11.3 Docs sync** -- this changelog entry, plus
  `docs/PROJECT_MANAGEMENT.md` and `docs/AGENT_ARCHITECTURE.md` updated
  to reflect the 11.1 ContextVar plumbing on `AgentStep`. The Phase
  11-18 v2 roadmap was already in the docs after commit `68421bc`;
  no further roadmap edits needed in 11.3.
- **11.4 Provider health monitor** -- background poller calls
  `test_connection()` on every configured provider every 5 minutes and
  caches results in memory (`src/providers/health.py`,
  `ProviderHealthMonitor`). Probes run in a worker thread
  (`asyncio.to_thread`) so subprocess providers' `--version` checks
  don't block the FastAPI event loop. Lifecycle is managed by a
  `@asynccontextmanager` lifespan on the app, with
  `AUTOAPPLY_DISABLE_HEALTH_MONITOR=1` opt-out for TestClient usage.
  New endpoints `GET /api/providers/health` (cached snapshot) and
  `POST /api/providers/health/refresh` (force probe + return fresh
  snapshot). The Settings page's "Last verified ..." line now reflects
  live telemetry rather than the last manual-test breadcrumb, and
  surfaces `health.detail` in the destructive variant when a probe
  failed. +7 tests (725 total).
- **11.5 Writer sync for list+scalar fallback shapes** -- Phase 11.1
  made `fallback_providers` (list) authoritative; `get_llm_settings`
  ignores the legacy `fallback_provider` scalar when both exist. Before
  this sub-phase the writers that mutate `settings.yaml` only updated
  the scalar, so users who had already migrated to the list form never
  saw their fallback selections take effect. Fixed across four codex
  review rounds in `src/core/config.py` (`update_llm_settings`),
  `src/cli/cmd_provider.py` (`use_cmd`), `src/cli/cmd_migrate.py`
  (`detect_settings_issues` / `apply_settings_fixes` now promote the
  orphan `llm.provider` key for pre-Phase-10 configs), and
  `src/application/providers.py` (`disconnect_provider`,
  `use_provider_as_primary`). The new `_coerce_chain` helper accepts
  list / comma-separated string / missing -- the same three shapes
  `get_llm_settings` reads -- and the chain logic now: (a) preserves
  list-only configs through disconnect, (b) keeps deeper fallbacks when
  one chain entry is removed, (c) ignores a stale scalar when the list
  is present, (d) mirrors the new list head onto the scalar after
  pruning, and (e) preserves `allow_fallback: false` through both
  disconnect cleanup and self-heal. +8 tests (727 total). ruff clean.

### Licensing: PolyForm Noncommercial 1.0.0 adopted

The project was previously unlicensed ("Private -- not yet
determined" in the README). Adopted **PolyForm Noncommercial 1.0.0**
as the source-available license.

- Added `LICENSE` at the repo root with the full PolyForm
  Noncommercial 1.0.0 text plus a `Required Notice` and a
  `Commercial Use` section directing commercial users to
  `frostnova986@gmail.com` for a separate license.
- Updated `README.md` License section with a permitted-vs-
  commercial table and the commercial-licensing contact path.
- Updated `pyproject.toml`: `license = { file = "LICENSE" }`,
  `authors`, and a `License :: Other/Proprietary License`
  classifier (PolyForm Noncommercial is not on the OSI/SPDX
  standard list, so we use the "Other" classifier; the canonical
  license name lives in `LICENSE` itself).

**What is permitted without contacting the author**: personal use
to apply for your own jobs, academic / coursework / thesis use,
nonprofit / public-research / educational-institution use, and
noncommercial open-source forks.

**What requires a commercial license**: running AutoApply as a
paid service, bundling it into a commercial product, using it
inside a for-profit company's recruiting workflow, or selling
support / hosting / modifications.

### Phase 10: LLM Provider Abstraction

The "LLM" layer was previously hard-coded to two subprocess
providers (`claude -p` and `codex exec`). Phase 10 breaks that open:
all five call paths now go through a `ProviderRegistry` so users
can plug in any of OpenAI / Anthropic / Gemini (REST) or Claude CLI
/ Codex CLI (subprocess).

- **10.1 Provider abstraction + credential store**
  (`src/providers/base.py`, `src/providers/store.py`):
  `LLMProvider` ABC, `ProviderKind`, `AuthType` (`API_KEY`,
  `SUBPROCESS`), `ProviderTestResult`. Credentials live in
  `data/providers/credentials.json` (mode 0600) with OS-keyring
  fallback when available. Never written to git, never logged.
- **10.2 REST adapters** (`src/providers/openai.py`,
  `src/providers/anthropic.py`, `src/providers/gemini.py`):
  one adapter per vendor using `httpx`. Each implements
  `generate(prompt, system, model)`, `list_models()`, and a deep
  `test_connection()` that does an auth-validating round-trip
  (not just a token presence check).
- **10.3** Originally a "Codex OAuth wrapper" -- removed in 10.7.
  The wrapper conflated "drive Codex CLI as a subprocess" with
  "implement a native OAuth client", and the OAuth half was never
  real (generation always went through `codex exec`). Kept for one
  revision under a back-compat alias before 10.7 cleaned it up.
- **10.4 Claude CLI subprocess provider**
  (`src/providers/claude_cli.py`): `auth_type=SUBPROCESS`. The CLI
  owns its own login -- AutoApply doesn't store a token, doesn't
  manage refresh, doesn't run an OAuth dance. `test_connection`
  is a deep probe (`claude --version` + status check).
- **10.5 Registry bridge into `generate_text`**
  (`src/providers/registry.py`, `src/utils/llm.py`): old call sites
  in `generation/`, `matching/`, `agent/` are unchanged -- the
  dispatch picks the configured primary provider transparently.
  Fallback dispatch (when primary errors) lands in Phase 11.1.
- **10.6 `autoapply provider` CLI subcommands**
  (`src/cli/cmd_provider.py`): `list`, `set-key`, `test`,
  `set-primary`, `set-fallback`, `disconnect`. The
  `provider login` subcommand introduced in 10.3 was removed in
  10.7 -- subprocess providers manage their own auth; users run
  `codex login` / `claude login` directly.
- **10.7 Settings page UI**
  (`frontend/src/views/SettingsView.vue`): connect / disconnect /
  test / set-primary / set-fallback for every provider in one
  place. Distinguishes "API-key provider, configured" from
  "subprocess provider, CLI installed and authenticated" from
  "subprocess provider, CLI installed but NOT logged in" --
  the last case is reported via `codex login status` so the user
  doesn't dispatch generations that will crash at runtime.
  Disconnect button stays visible for subprocess providers when a
  stale credential breadcrumb exists from earlier revisions
  (labelled "Clear stored record" in that mode).

**Architectural pivot recorded here**: this Phase 10 was originally
planned as "cover-letter agent". It was reordered after Phase 9
because the LLM-provider abstraction unblocks every subsequent
agent phase (no point writing a second agent against a hard-coded
`subprocess.run(['claude', ...])`). The roadmap was re-planned again
on 2026-05-12 (v2) around Redis + the commercial path, then tightened
on 2026-05-14 (v3) so Phase 14 explicitly owns task queue / worker
execution and Phase 15 owns resume + cover-letter generation v2. Four
new cross-cutting / infrastructure phases are inserted ahead of agent
work: Phase 11 (reliability), Phase 12 (cache infrastructure with
Redis), Phase 13 (Job Index & Freshness Engine), Phase 14 (task queue
+ scheduled work). Phase 18 (multi-tenancy & auth hardening) closes
the v1 commercial-ready core. See `docs/PROJECT_MANAGEMENT.md` for
the full sub-phase breakdown and `docs/DECISIONS.md` D018-D024 for the
rationale.

Test baseline at Phase 10 close: 669 passed, 1 skipped.
`ruff check src/ tests/` clean. Frontend rebuilds clean.

### Agent Phase 9: Form-Filler Agent (with HITL gate, eval suite, cost telemetry)

The first real business node converted to agent-mode. The deterministic
`form_filler.py` is still the default; `agent_form_filler.py` is the
new path, gated on confidence + the existing approval queue.

- **9.1 Browser tool layer** (`src/agent/tools/browser.py`,
  `src/agent/tools/browser_models.py`): four sync, side-effect-free
  tools the agent can call -- `browser_inspect_page`,
  `browser_find_field`, `browser_propose_fill`, `browser_screenshot`.
  Operate on a `PageSnapshot` extracted by the orchestrator; the agent
  never holds a Playwright handle. Stdlib HTML snapshot builder for
  fixtures + an async `build_snapshot_from_page` for live runs. 38 tests.
- **9.2 Orchestrator** (`src/execution/agent_form_filler.py`): wires
  snapshot → agent loop → proposal review → approval gate →
  deterministic `fill_fields`. Two gate kinds, `form_fill_review`
  (soft, optional based on confidence threshold) and `submit_form`
  (hard, always required). `submit()` raises `PermissionError` if
  the gate hasn't approved -- there is no force flag. Falls back to
  rule-based filling when the agent crashes or proposes nothing.
  Adds `profile_lookup` tool so PII is never pasted into the prompt.
  21 + 15 tests across orchestrator and profile tool.
- **9.3 Eval suite** (`tests/agent_evals/fixtures/form_filler/`):
  five fixtures (basic / Workday-like / Greenhouse-like /
  Lever-like w/ recovery / Ashby-like long select). Two new scorers:
  `field_mapping_match` and `no_proposal_for_label`. Runner emits a
  JSON envelope; CLI gate is `autoapply eval --suite form_filler
  --min-pass-rate 0.85`. Baseline JSON locked in
  `tests/agent_evals/baselines/`. 14 tests.
- **9.4 Cost / latency telemetry**: `AgentStep` now carries
  `prompt_tokens`, `output_tokens`, `cost_usd`; `AgentResult` and
  `TraceRecord` aggregate. Estimated via chars/4 heuristic with rates
  configurable by env var. Surfaces in `autoapply eval`, the web trace
  viewer, and persisted trace JSON. 13 tests.
- **9.5 Docs**: new `docs/AGENT_ARCHITECTURE.md` describing the
  three-layer orchestrator/loop/tool split and the HITL contract;
  README updated with agent-mode notes; this changelog entry.

Verification baseline: 553 passed, 1 skipped. `ruff check` clean.
`autoapply eval --suite form_filler --min-pass-rate 0.85` exits 0
with 5/5 passing at ~$0.23 estimated under default rates.

### Agent Phase 8: Agent Harness (foundational layer)

Foundational primitives that Phase 9 sits on top of. Shipped in
commits ed75568..e6a06ee on `feat/phase-8`.

- **8.1 Tool abstraction layer** (`src/agent/tools/base.py`): `Tool`
  ABC, `ToolSpec`, `ToolRegistry` with allow-list views, `ToolResult`
  with structured payload + error channel. Built-in `fs_read`,
  `text_stats`, `finish`. Hardened `fs_read` truncation to handle
  multi-byte UTF-8 boundary cleanly.
- **8.2 Bounded ReAct agent loop** (`src/agent/core/loop.py`): manual
  `{thought, action}` JSON protocol so both `claude` and `codex` CLIs
  work without provider-native tool-use. Hard `max_steps`,
  `step_timeout`, `allow_tool_errors` controls; `finish` sentinel; tool
  errors surface as observations rather than aborting.
- **8.3 Trace store + viewer** (`src/agent/trace/`, `src/web/routes/agent.py`):
  per-session JSON document under `data/agent_traces/`; FastAPI viewer
  at `/api/agent/viewer` lists recent runs and replays steps.
- **8.4 Fixture-driven eval harness** (`src/agent/eval/`,
  `tests/agent_evals/fixtures/agent_smoke/`): JSON fixtures specify
  `goal`, allowed tools, scripted LLM responses, and scorer
  expectations. New `autoapply eval` CLI command with `--suite`,
  `--list`, `--json`, `--min-pass-rate`.
- **8.5 HITL approval gate** (`src/agent/gate/queue.py`,
  `/api/agent/gate/...`): file-backed approval queue with `propose`,
  `approve`, `reject`, lazy expiry, and a viewer UI for pending
  requests.

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
