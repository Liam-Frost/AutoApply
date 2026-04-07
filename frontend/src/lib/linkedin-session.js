import { reactive } from "vue"

import { api } from "./api"

export const linkedinSessionState = reactive({
  checked: false,
  loading: false,
  connecting: false,
  clearing: false,
  authenticated: false,
  has_session_data: false,
  ok: true,
  message: "",
  error: "",
})

export async function ensureLinkedInSessionLoaded() {
  if (linkedinSessionState.checked || linkedinSessionState.loading) {
    return
  }
  await refreshLinkedInSession()
}

export async function refreshLinkedInSession() {
  if (linkedinSessionState.loading) {
    return
  }

  linkedinSessionState.loading = true
  linkedinSessionState.error = ""

  try {
    syncLinkedInSession(await api.linkedinSession())
  } catch (error) {
    linkedinSessionState.checked = true
    linkedinSessionState.authenticated = false
    linkedinSessionState.ok = false
    linkedinSessionState.error = error.message
    linkedinSessionState.message = ""
  } finally {
    linkedinSessionState.loading = false
  }
}

export async function connectLinkedInSession() {
  linkedinSessionState.connecting = true
  linkedinSessionState.error = ""
  linkedinSessionState.message = "Finish LinkedIn sign-in in the opened browser window."

  try {
    syncLinkedInSession(await api.connectLinkedIn())
  } catch (error) {
    linkedinSessionState.error = error.message
  } finally {
    linkedinSessionState.connecting = false
  }
}

export async function clearLinkedInSessionStore() {
  linkedinSessionState.clearing = true
  linkedinSessionState.error = ""

  try {
    syncLinkedInSession(await api.clearLinkedInSession())
  } catch (error) {
    linkedinSessionState.error = error.message
  } finally {
    linkedinSessionState.clearing = false
  }
}

export function syncLinkedInSession(payload) {
  linkedinSessionState.checked = true
  linkedinSessionState.authenticated = Boolean(payload.authenticated)
  linkedinSessionState.has_session_data = Boolean(payload.has_session_data)
  linkedinSessionState.ok = payload.ok !== false
  linkedinSessionState.message = payload.message || ""
  linkedinSessionState.error = payload.ok === false ? payload.message || payload.error || "" : ""
}
