async function request(path, options = {}) {
  const response = await fetch(path, options)
  const contentType = response.headers.get("content-type") || ""
  const payload = contentType.includes("application/json")
    ? await response.json()
    : await response.text()

  if (!response.ok) {
    const message =
      (typeof payload === "object" && payload !== null && (payload.detail || payload.message)) ||
      response.statusText ||
      "Request failed"
    throw new Error(message)
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

export const api = {
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
  linkedinSession() {
    return request("/api/jobs/linkedin/session")
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
  validateTemplate(documentType, templateId) {
    return request(`/api/templates/${encodeURIComponent(documentType)}/${encodeURIComponent(templateId)}/validate`, {
      method: "POST",
    })
  },
  generateJobMaterial(job, materialType, templateId = "", profileId = "") {
    return request("/api/jobs/generate-material", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job,
        material_type: materialType,
        template_id: templateId || null,
        profile_id: profileId || null,
      }),
    })
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
}
