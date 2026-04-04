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
  profile() {
    return request("/api/profile")
  },
  uploadResume(file) {
    const form = new FormData()
    form.append("resume", file)
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
