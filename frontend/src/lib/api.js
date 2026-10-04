async function request(path, options = {}) {
  const response = await fetch(path, options)
  const contentType = response.headers.get("content-type") || ""
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text()

  if (!response.ok) {
    // FastAPI returns ``detail`` for HTTPException; some endpoints
    // use plain ``message``. ``detail`` is often a STRUCTURED object
    // (e.g. ``{"error": "invalid_namespace", "message": "..."}``);
    // stringifying it via ``new Error({object})`` would yield
    // "[object Object]" and hide the actual reason. Pick a string for
    // ``message`` but attach the parsed body so callers that care
    // about the structured shape can read it.
    const detail = typeof payload === "object" && payload !== null ? payload.detail : null
    let message
    if (typeof detail === "string") {
      message = detail
    } else if (detail && typeof detail === "object") {
      // Prefer human-readable fields when present.
      message = detail.message || detail.error || JSON.stringify(detail)
    } else if (typeof payload === "object" && payload !== null && payload.message) {
      message = payload.message
    } else if (typeof payload === "string" && payload) {
      message = payload
    } else {
      message = response.statusText || "Request failed"
    }
    const err = new Error(message)
    err.status = response.status
    err.body = payload
    throw err
  }

  return payload
}

function toQuery(params) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== "" && value !== null && value !== undefined) {
      search.set(key, String(value))
    }
  })
  const query = search.toString()
  return query ? `?${query}` : ""
}

function _materialEnvelopeFromTaskRow(row, materialType, extras = {}) {
  // Phase 18.2: rebuild the legacy ``generate_material_for_job``
  // envelope from a settled TaskRecord row so call sites don't have
  // to learn the new shape. ``row.result`` carries the structured
  // task return value (artifact paths, strategy notes, errors).
  //
  // Codex review fix: ``artifacts`` is an OBJECT keyed by document
  // type, not an array. The old length comparison never fired, so
  // a task that returned ``{status: "failed", errors: [...]}``
  // would land here with ``row.status === "succeeded"`` and yield a
  // misleading ``{ok: true, artifact: null}``. We now treat any
  // task whose body-level status is not "ok"/"partial-with-data" as
  // a failure, regardless of the row's Celery-level status.
  const result = row?.result || {}
  const artifacts = result.artifacts || {}
  const docKey = materialType.startsWith("cover_letter")
    ? "cover_letter"
    : "resume"
  const documentArtifact =
    artifacts[materialType] ||
    artifacts[docKey] ||
    artifacts[`${docKey}_docx`] ||
    null
  const errors = result.errors || []
  const bodyStatus = result.status || null
  const noArtifacts = Object.keys(artifacts).length === 0
  const rowFailed = row.status !== "succeeded"
  const bodyFailed =
    bodyStatus && bodyStatus !== "ok" && (bodyStatus !== "partial" || noArtifacts)
  if (rowFailed || bodyFailed || (errors.length > 0 && !documentArtifact)) {
    const err = new Error(
      errors.length
        ? errors.map((e) => e.error).join("; ")
        : result.detail || row.last_error || `Task failed: ${bodyStatus || row.status}`,
    )
    err.row = row
    err.errors = errors
    throw err
  }
  const normalizedArtifact =
    documentArtifact && typeof documentArtifact === "object"
      ? documentArtifact
      : documentArtifact
        ? { path: documentArtifact }
        : null
  const nestedArtifacts =
    normalizedArtifact?.artifacts && typeof normalizedArtifact.artifacts === "object"
      ? normalizedArtifact.artifacts
      : null
  const flatArtifacts = nestedArtifacts
    ? Object.fromEntries(
        Object.entries(nestedArtifacts).map(([k, v]) => [k, v?.path || v]),
      )
    : Object.fromEntries(
        Object.entries(artifacts).map(([k, v]) => [k, v?.path || v]),
      )
  return {
    ok: true,
    task_id: row.id,
    material_type: materialType,
    artifact: normalizedArtifact,
    artifacts: flatArtifacts,
    job: normalizedArtifact?.job || result.job || null,
    document: normalizedArtifact?.document || null,
    validation: normalizedArtifact?.validation || null,
    template: normalizedArtifact?.template || null,
    requirements: normalizedArtifact?.requirements || null,
    version: normalizedArtifact?.version || null,
    strategy: normalizedArtifact?.strategy ?? null,
    strategy_source: normalizedArtifact?.strategy_source ?? null,
    strategy_notes: normalizedArtifact?.strategy_notes ?? [],
    source_document_id: normalizedArtifact?.source_document_id ?? null,
    application_id: result.application_id || extras.applicationId || null,
    application_updates: result.application_updates || {},
    ...extras,
  }
}

export const api = {
  // Generic escape hatches for views that talk to routes without a
  // dedicated wrapper (e.g. TasksView hitting /api/tasks and
  // /api/schedule). Keep the named methods below for everything that
  // needs param encoding / structured payloads.
  get(path) {
    return request(path)
  },
  post(path, body = {}) {
    return request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  },
  // Phase 18.2 async-task helpers ----------------------------------
  // Long-running routes (generate-material, regenerate-material)
  // return ``{task_id, poll_url}``; views call ``pollTask`` to wait
  // for the structured ``result`` payload without writing their own
  // setInterval loop.
  getTask(taskId) {
    return request(`/api/tasks/${encodeURIComponent(taskId)}`)
  },
  createMaterialsApplication(job, profileId = "") {
    return request("/api/jobs/materials-application", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job,
        profile_id: profileId || null,
      }),
    })
  },
  /**
   * Poll ``/api/tasks/{taskId}`` until the row reaches a terminal
   * state (``succeeded``, ``failed``, ``cancelled``,
   * ``dead_lettered``, or ``waiting_human``) or ``timeoutMs``
   * elapses.
   *
   * Optional ``onTick(row)`` callback fires after every poll so the
   * view can render an "in progress" indicator without subscribing
   * separately.
   */
  async pollTask(
    taskId,
    {
      intervalMs = 1500,
      timeoutMs = 15 * 60 * 1000,
      onTick = null,
    } = {},
  ) {
    const terminal = new Set([
      "succeeded",
      "failed",
      "cancelled",
      "dead_lettered",
      "waiting_human",
    ])
    const deadline = Date.now() + timeoutMs
    let row = await api.getTask(taskId)
    if (onTick) onTick(row)
    while (!terminal.has(row.status)) {
      if (Date.now() > deadline) {
        const err = new Error(`pollTask timed out after ${timeoutMs}ms`)
        err.row = row
        throw err
      }
      await new Promise((resolve) => setTimeout(resolve, intervalMs))
      row = await api.getTask(taskId)
      if (onTick) onTick(row)
    }
    return row
  },
  dashboard() {
    return request("/api/dashboard")
  },
  searchJobs(payload) {
    return request("/api/jobs/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  filterProfiles() {
    return request("/api/jobs/filter-profiles")
  },
  jobIndexFreshness(payload) {
    return request("/api/jobs/index/freshness", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  jobIndexRefresh(payload) {
    return request("/api/jobs/index/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  saveFilterProfile(profileId, payload) {
    return request(`/api/jobs/filter-profiles/${encodeURIComponent(profileId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  deleteFilterProfile(profileId) {
    return request(`/api/jobs/filter-profiles/${encodeURIComponent(profileId)}`, {
      method: "DELETE",
    })
  },
  linkedinSession({ forceRefresh = false } = {}) {
    // Default path is cache-served on the backend (5-min TTL) so opening the
    // UI doesn't spin up a headless Chromium every time. Pass forceRefresh to
    // run a real probe — e.g. from an explicit "Check status" click.
    const suffix = forceRefresh ? "?refresh=true" : ""
    return request(`/api/jobs/linkedin/session${suffix}`)
  },
  connectLinkedIn() {
    return request("/api/jobs/linkedin/session/connect", {
      method: "POST",
    })
  },
  clearLinkedInSession() {
    return request("/api/jobs/linkedin/session", {
      method: "DELETE",
    })
  },
  manualApplyTarget(url) {
    return request("/api/jobs/manual-apply-target", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    })
  },
  applyJob(url) {
    return request("/api/jobs/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    })
  },
  templates() {
    return request("/api/templates")
  },
  documents(documentType = "") {
    const suffix = documentType ? `?document_type=${encodeURIComponent(documentType)}` : ""
    return request(`/api/documents${suffix}`)
  },
  uploadDocument(documentType, file, { displayName = "", notes = "" } = {}) {
    const form = new FormData()
    form.append("document", file)
    form.append("document_type", documentType)
    if (displayName) form.append("display_name", displayName)
    if (notes) form.append("notes", notes)
    return request("/api/documents/upload", { method: "POST", body: form })
  },
  updateDocument(documentId, { displayName, notes } = {}) {
    const body = {}
    if (displayName !== undefined) body.display_name = displayName
    if (notes !== undefined) body.notes = notes
    return request(`/api/documents/${encodeURIComponent(documentId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  },
  deleteDocument(documentId) {
    return request(`/api/documents/${encodeURIComponent(documentId)}`, {
      method: "DELETE",
    })
  },
  documentDownloadUrl(documentId) {
    return `/api/documents/${encodeURIComponent(documentId)}/download`
  },
  promoteArtifactToLibrary({ artifactPath, documentType, displayName, applicationId = "", jobSnapshotId = "", notes = "" } = {}) {
    return request("/api/documents/promote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        artifact_path: artifactPath,
        document_type: documentType,
        display_name: displayName,
        application_id: applicationId || null,
        job_snapshot_id: jobSnapshotId || null,
        notes: notes || null,
      }),
    })
  },
  createProfileFromLibrary({ documentId, profileId = "", overwrite = false, setActive = true } = {}) {
    return request("/api/profile/from-library", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_id: documentId,
        profile_id: profileId || null,
        overwrite,
        set_active: setActive,
      }),
    })
  },
  materialDefaults() {
    return request("/api/settings/material-defaults")
  },
  updateMaterialDefaults(payload) {
    return request("/api/settings/material-defaults", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  uploadTemplate(documentType, file, templateName = "") {
    const form = new FormData()
    form.append("document_type", documentType)
    form.append("template", file)
    if (templateName) {
      form.append("template_name", templateName)
    }
    return request("/api/templates/upload", {
      method: "POST",
      body: form,
    })
  },
  createLatexTemplate(documentType, templateName = "", description = "") {
    return request("/api/templates/latex", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document_type: documentType,
        template_name: templateName,
        description,
      }),
    })
  },
  templateDetail(documentType, templateId) {
    return request(`/api/templates/${encodeURIComponent(documentType)}/${encodeURIComponent(templateId)}`)
  },
  updateTemplate(documentType, templateId, payload) {
    return request(`/api/templates/${encodeURIComponent(documentType)}/${encodeURIComponent(templateId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  updateTemplateStyles(documentType, templateId, payload) {
    return request(`/api/templates/${encodeURIComponent(documentType)}/${encodeURIComponent(templateId)}/styles`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  validateTemplate(documentType, templateId) {
    return request(`/api/templates/${encodeURIComponent(documentType)}/${encodeURIComponent(templateId)}/validate`, {
      method: "POST",
    })
  },
  deleteTemplate(documentType, templateId) {
    return request(`/api/templates/${encodeURIComponent(documentType)}/${encodeURIComponent(templateId)}`, {
      method: "DELETE",
    })
  },
  /**
   * Phase 18.2: defaults to enqueue + poll for the produced
   * artifact map. The route now returns ``{status: "queued",
   * task_id, poll_url}``; this wrapper waits on ``pollTask`` and
   * returns the legacy sync-style envelope (``{ok, artifact,
   * artifacts, strategy_notes, ...}``) so existing call sites need
   * no changes.
   *
   * Pass ``{ async: false }`` to skip the poll and hand the raw
   * task envelope back (useful for views that want their own
   * progress UX).
   */
  async generateJobMaterial(
    job,
    materialType,
    templateId = "",
    profileId = "",
    options = {},
  ) {
    const {
      strategy = null,
      sourceDocumentId = null,
      applicationId = null,
      patchAggressiveness = null,
      patchAllowReorderSections = null,
      patchAllowAddRemoveBullets = null,
      onProgress = null,
      pollIntervalMs = 1500,
      pollTimeoutMs,
      sync = false,
    } = options
    const queued = await request("/api/jobs/generate-material", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job,
        material_type: materialType,
        template_id: templateId || null,
        profile_id: profileId || null,
        application_id: applicationId || null,
        strategy,
        source_document_id: sourceDocumentId,
        patch_aggressiveness: patchAggressiveness,
        patch_allow_reorder_sections: patchAllowReorderSections,
        patch_allow_add_remove_bullets: patchAllowAddRemoveBullets,
      }),
    })
    if (sync || queued.status !== "queued") {
      // Either AUTOAPPLY_SYNC_MATERIALS=1 brought back the
      // synchronous path or the caller opted out of polling.
      return queued
    }
    const row = await api.pollTask(queued.task_id, {
      intervalMs: pollIntervalMs,
      timeoutMs: pollTimeoutMs,
      onTick: onProgress,
    })
    return _materialEnvelopeFromTaskRow(row, materialType)
  },
  artifactDownloadUrl(path) {
    return `/api/artifacts/download?path=${encodeURIComponent(path)}`
  },
  applications(filters) {
    return request(`/api/applications${toQuery(filters)}`)
  },
  updateOutcome(applicationId, outcome) {
    return request(`/api/applications/${applicationId}/outcome`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ outcome }),
    })
  },
  submitApplication(applicationId) {
    return request(`/api/applications/${applicationId}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
  },
  discardApplication(applicationId, reason = "") {
    return request(`/api/applications/${applicationId}/discard`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason || null }),
    })
  },
  /**
   * Delete an application from the tracker.
   *
   * ``cascade=true`` (default) moves the linked resume / cover letter
   * artifacts and screenshots into the cleanup quarantine immediately
   * so the user does not have to wait for the retention window. The
   * database row itself is still soft-deleted via ``deleted_at`` so
   * audit history survives until the cleanup task purges it.
   */
  deleteApplication(applicationId, { cascade = true } = {}) {
    const query = cascade ? "?cascade=true" : ""
    return request(`/api/applications/${applicationId}${query}`, {
      method: "DELETE",
    })
  },
  /**
   * Phase 18.2 mirror of :func:`generateJobMaterial`: enqueue +
   * poll. Existing callers that just ``await`` the call still see
   * the legacy ``{ok, artifact, ...}`` envelope; pass ``sync: true``
   * to skip the poll and inspect the queued task envelope directly.
   */
  async regenerateApplicationMaterial(
    applicationId,
    {
      materialType,
      strategy = null,
      templateId = null,
      sourceDocumentId = null,
      patchAggressiveness = null,
      patchAllowReorderSections = null,
      patchAllowAddRemoveBullets = null,
      onProgress = null,
      pollIntervalMs = 1500,
      pollTimeoutMs,
      sync = false,
    } = {},
  ) {
    const queued = await request(
      `/api/applications/${applicationId}/regenerate-material`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          material_type: materialType,
          strategy,
          template_id: templateId,
          source_document_id: sourceDocumentId,
          patch_aggressiveness: patchAggressiveness,
          patch_allow_reorder_sections: patchAllowReorderSections,
          patch_allow_add_remove_bullets: patchAllowAddRemoveBullets,
        }),
      },
    )
    if (sync || queued.status !== "queued") {
      return queued
    }
    const row = await api.pollTask(queued.task_id, {
      intervalMs: pollIntervalMs,
      timeoutMs: pollTimeoutMs,
      onTick: onProgress,
    })
    return _materialEnvelopeFromTaskRow(row, materialType, {
      applicationId,
    })
  },
  profile(profileId = "") {
    const suffix = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : ""
    return request(`/api/profile${suffix}`)
  },
  createProfile(profileId, setActive = true) {
    return request("/api/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: profileId, set_active: setActive }),
    })
  },
  saveProfile(profileId, profile, setActive = false) {
    return request(`/api/profile/${profileId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile_id: profileId, profile, set_active: setActive }),
    })
  },
  deleteProfile(profileId) {
    return request(`/api/profile/${profileId}`, {
      method: "DELETE",
    })
  },
  renameProfile(profileId, newProfileId) {
    return request(`/api/profile/${profileId}/rename`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_profile_id: newProfileId }),
    })
  },
  activateProfile(profileId) {
    return request(`/api/profile/${profileId}/activate`, {
      method: "POST",
    })
  },
  uploadResume(file, options = {}) {
    const form = new FormData()
    form.append("resume", file)
    if (options.profileId) {
      form.append("profile_id", options.profileId)
    }
    form.append("overwrite", String(Boolean(options.overwrite)))
    form.append("set_active", String(options.setActive !== false))
    return request("/api/profile/upload-resume", {
      method: "POST",
      body: form,
    })
  },
  settings() {
    return request("/api/settings/llm")
  },
  updateSettings(payload) {
    return request("/api/settings/llm", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  clearSearchCache() {
    return request("/api/settings/search-cache", {
      method: "DELETE",
    })
  },
  providers() {
    return request("/api/providers")
  },
  providerModels(providerId) {
    return request(
      `/api/providers/${encodeURIComponent(providerId)}/models`,
    )
  },
  setProviderModel(providerId, model) {
    return request(
      `/api/providers/${encodeURIComponent(providerId)}/model`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: model || null }),
      },
    )
  },
  providersHealth() {
    return request("/api/providers/health")
  },
  refreshProvidersHealth() {
    return request("/api/providers/health/refresh", { method: "POST" })
  },
  testProvider(providerId) {
    return request(`/api/providers/${encodeURIComponent(providerId)}/test`, {
      method: "POST",
    })
  },
  connectApiKeyProvider(providerId, payload) {
    return request(`/api/providers/${encodeURIComponent(providerId)}/set-key`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  disconnectProvider(providerId) {
    return request(`/api/providers/${encodeURIComponent(providerId)}`, {
      method: "DELETE",
    })
  },
  useProvider(providerId, fallbackProvider = null) {
    return request(`/api/providers/${encodeURIComponent(providerId)}/use`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fallback_provider: fallbackProvider }),
    })
  },
  cacheSnapshot() {
    // Phase 12.6 inspector. Server-side SCAN can take a moment under
    // a large keyspace, so callers should drive a loading state.
    return request("/api/cache")
  },
  costTrend(bucket = "day", periods = 14) {
    // Phase 17 dashboard card -- aggregated LLM spend per day/week.
    return request(
      `/api/agent/costs/trend?bucket=${encodeURIComponent(bucket)}&periods=${encodeURIComponent(periods)}`,
    )
  },
  recentTraces(limit = 20) {
    return request(`/api/agent/traces?limit=${encodeURIComponent(limit)}`)
  },
  automationPlans() {
    return request("/api/automation-plans")
  },
  automationPlanRuns(params = {}) {
    const query = new URLSearchParams()
    if (params.limit) query.set("limit", String(params.limit))
    if (params.status) query.set("status", params.status)
    const suffix = query.toString() ? `?${query.toString()}` : ""
    return request(`/api/automation-plans/runs${suffix}`)
  },
  createAutomationPlan(payload) {
    return request("/api/automation-plans", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  updateAutomationPlan(planId, payload) {
    return request(`/api/automation-plans/${encodeURIComponent(planId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  deleteAutomationPlan(planId) {
    return request(`/api/automation-plans/${encodeURIComponent(planId)}`, {
      method: "DELETE",
    })
  },
  runAutomationPlan(planId) {
    return request(`/api/automation-plans/${encodeURIComponent(planId)}/run-now`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    })
  },
  morningDigest(windowHours = 24) {
    // Phase 17.6: dashboard banner payload.
    return request(`/api/digest?window_hours=${encodeURIComponent(windowHours)}`)
  },
  // Phase 17.3 + 17.4: review queue.
  reviewList(status = null) {
    const suffix = status ? `?status=${encodeURIComponent(status)}` : ""
    return request(`/api/review${suffix}`)
  },
  reviewDetail(entryId) {
    return request(`/api/review/${encodeURIComponent(entryId)}`)
  },
  reviewApprove(entryId, payload = {}) {
    return request(`/api/review/${encodeURIComponent(entryId)}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  reviewReject(entryId, payload = {}) {
    return request(`/api/review/${encodeURIComponent(entryId)}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  reviewRefresh(entryId, payload = {}) {
    return request(`/api/review/${encodeURIComponent(entryId)}/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  reviewSubmit(entryId, payload = {}) {
    // Phase 17.5: approve-and-submit via the pre-submit hard gate.
    // The server runs the gate; if blocked, the response body has
    // ok=false + a structured gate verdict the UI renders inline.
    return request(`/api/review/${encodeURIComponent(entryId)}/submit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  reviewBulkApprove(entryIds, payload = {}) {
    return request("/api/review/bulk/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry_ids: entryIds, ...payload }),
    })
  },
  reviewBulkReject(entryIds, payload = {}) {
    return request("/api/review/bulk/reject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry_ids: entryIds, ...payload }),
    })
  },
  reviewBulkRejectByFilter(payload) {
    return request("/api/review/bulk/reject-by-filter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  },
  matchingExplain(job) {
    // Phase 16.3: "Why was this filtered?" explainability endpoint.
    // Re-scores the job server-side against the active profile and
    // returns the structured ScoreBreakdown.to_dict() shape.
    return request("/api/matching/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job }),
    })
  },
  clearCacheNamespace(namespace) {
    // Mirrors `autoapply redis flush --namespace`: requires the
    // operator to have confirmed via the UI. The body's `confirm: true`
    // is what the API endpoint checks; without it the server refuses.
    return request(`/api/cache/${encodeURIComponent(namespace)}`, {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirm: true }),
    })
  },
}
