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
  applyJob(url) {
    return request("/api/jobs/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    })
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
}
