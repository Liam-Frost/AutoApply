<script setup>
import { onMounted, reactive, watch } from "vue"

import AppSelect from "../components/AppSelect.vue"
import { api } from "../lib/api"
import {
  clearLinkedInSessionStore,
  connectLinkedInSession,
  linkedinSessionState,
  refreshLinkedInSession,
} from "../lib/linkedin-session"

const providerOptions = [
  { value: "claude-cli", label: "Claude Code CLI" },
  { value: "codex-cli", label: "Codex CLI" },
]

const fallbackOptions = [
  { value: "", label: "Disabled" },
  ...providerOptions,
]

const state = reactive({
  loading: true,
  saving: false,
  suspendAutosave: false,
  error: "",
  message: "",
  cache: {
    clearing: false,
  },
  data: {
    llm: {
      primary_provider: "claude-cli",
      fallback_provider: null,
      allow_fallback: false,
    },
    available_providers: {
      "claude-cli": false,
      "codex-cli": false,
    },
    search_cache: {
      enabled: true,
      ttl_hours: 24,
    },
    config_path: "",
  },
  form: {
    primary_provider: "claude-cli",
    fallback_provider: "",
    allow_fallback: false,
    cache_enabled: true,
    cache_ttl_hours: 24,
  },
})

function syncForm() {
  state.form.primary_provider = state.data.llm.primary_provider
  state.form.fallback_provider = state.data.llm.fallback_provider || ""
  state.form.allow_fallback = Boolean(state.data.llm.allow_fallback)
  state.form.cache_enabled = Boolean(state.data.search_cache?.enabled)
  state.form.cache_ttl_hours = state.data.search_cache?.ttl_hours ?? 24
}

async function load() {
  state.loading = true
  state.error = ""
  state.suspendAutosave = true

  try {
    state.data = await api.settings()
    syncForm()
  } catch (error) {
    state.error = error.message
  } finally {
    state.suspendAutosave = false
    state.loading = false
  }
}

async function persistSettings({ keepMessage = false } = {}) {
  if (state.loading || state.suspendAutosave) {
    return
  }

  state.saving = true
  state.error = ""
  if (!keepMessage) {
    state.message = ""
  }

  try {
    state.data = await api.updateSettings({
      primary_provider: state.form.primary_provider,
      fallback_provider: state.form.fallback_provider || null,
      allow_fallback: state.form.allow_fallback,
      cache_enabled: state.form.cache_enabled,
      cache_ttl_hours: Number(state.form.cache_ttl_hours) || 24,
    })
    state.suspendAutosave = true
    syncForm()
    state.message = state.data.message || "Settings updated"
  } catch (error) {
    state.error = error.message
  } finally {
    state.suspendAutosave = false
    state.saving = false
  }
}

async function connectLinkedIn() {
  await connectLinkedInSession()
}

async function clearLinkedInSession() {
  await clearLinkedInSessionStore()
}

async function clearSearchCache() {
  state.cache.clearing = true
  state.error = ""

  try {
    state.data = await api.clearSearchCache()
    syncForm()
    state.message = state.data.message || "Search cache cleared"
  } catch (error) {
    state.error = error.message
  } finally {
    state.cache.clearing = false
  }
}

watch(
  () => [state.form.primary_provider, state.form.fallback_provider, state.form.allow_fallback],
  (_, previous) => {
    if (previous) {
      void persistSettings({ keepMessage: true })
    }
  },
)

watch(
  () => [state.form.cache_enabled, state.form.cache_ttl_hours],
  (_, previous) => {
    if (previous) {
      void persistSettings({ keepMessage: true })
    }
  },
)

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <div v-if="state.error" class="banner is-danger">{{ state.error }}</div>
    <div v-if="state.message" class="banner is-success">{{ state.message }}</div>

    <section class="page-stack settings-stack">
      <article class="surface settings-card">
        <div class="section-head">
          <div>
            <h2>LLM</h2>
            <div class="muted-inline">Provider routing</div>
          </div>
          <span class="muted">{{ state.saving ? "Saving..." : "Live" }}</span>
        </div>

        <div class="form-grid settings-form">
          <div class="settings-grid settings-grid-2">
            <label class="field">
              <span>Primary</span>
              <AppSelect v-model="state.form.primary_provider" :options="providerOptions" aria-label="Primary provider" />
            </label>

            <label class="field">
              <span>Fallback</span>
              <AppSelect v-model="state.form.fallback_provider" :options="fallbackOptions" aria-label="Fallback provider" />
            </label>
          </div>

          <label class="checkbox-row settings-checkbox-row settings-checkbox-compact">
            <input v-model="state.form.allow_fallback" type="checkbox" />
            <span>Auto fallback</span>
          </label>
        </div>
      </article>

      <article class="surface settings-card">
        <div class="section-head">
          <div>
            <h2>CLI</h2>
            <div class="muted-inline">Runtime availability and config path</div>
          </div>
          <span class="muted">{{ state.loading ? "..." : "ready" }}</span>
        </div>

        <div class="list-stack settings-list">
          <div class="list-row settings-row">
            <span>Claude Code CLI</span>
            <span class="chip" :class="{ success: state.data.available_providers['claude-cli'] }">
              {{ state.data.available_providers['claude-cli'] ? "Available" : "Missing" }}
            </span>
          </div>
          <div class="list-row settings-row">
            <span>Codex CLI</span>
            <span class="chip" :class="{ success: state.data.available_providers['codex-cli'] }">
              {{ state.data.available_providers['codex-cli'] ? "Available" : "Missing" }}
            </span>
          </div>
          <div class="list-row settings-row settings-row-path">
            <span>Config</span>
            <code class="path-label">{{ state.data.config_path }}</code>
          </div>
        </div>
      </article>

      <article class="surface settings-card">
        <div class="section-head">
          <div>
            <h2>Search Cache</h2>
            <div class="muted-inline">Reuse recent LinkedIn search results to avoid repeat pulls</div>
          </div>
          <span class="muted">{{ state.saving ? "Saving..." : "Live" }}</span>
        </div>

        <div class="page-stack settings-subsection">
          <label class="field">
            <span>TTL Hours</span>
            <input v-model="state.form.cache_ttl_hours" class="input" type="number" min="1" step="1" />
          </label>

          <label class="checkbox-row settings-checkbox-row settings-checkbox-compact">
            <input v-model="state.form.cache_enabled" type="checkbox" />
            <span>Enable cache</span>
          </label>

          <div class="actions-row settings-actions-row">
            <button class="button ghost compact settings-danger-button" type="button" :disabled="state.cache.clearing" @click="clearSearchCache">
              {{ state.cache.clearing ? "Clearing..." : "Clear Search Cache" }}
            </button>
          </div>
        </div>
      </article>

      <article class="surface settings-card">
        <div class="section-head">
          <div>
            <h2>LinkedIn</h2>
            <div class="muted-inline">Manage the saved browser session used for authenticated search</div>
          </div>
          <span class="chip" :class="{ success: linkedinSessionState.authenticated }">
            {{ linkedinSessionState.authenticated ? "Connected" : "Not connected" }}
          </span>
        </div>

        <div class="page-stack settings-subsection">
          <div class="list-row settings-row">
            <span>Saved session</span>
            <span class="chip" :class="{ success: linkedinSessionState.has_session_data }">
              {{ linkedinSessionState.has_session_data ? "Present" : "Empty" }}
            </span>
          </div>

          <div class="list-row settings-row settings-row-status">
            <span>Status</span>
            <span class="muted-inline">{{ linkedinSessionState.message || "Check LinkedIn session status." }}</span>
          </div>

          <div v-if="linkedinSessionState.error" class="banner is-danger">{{ linkedinSessionState.error }}</div>

          <div class="actions-row settings-actions-row">
            <button class="button ghost compact" type="button" :disabled="linkedinSessionState.loading || linkedinSessionState.connecting || linkedinSessionState.clearing" @click="refreshLinkedInSession">
              {{ linkedinSessionState.loading ? "Checking..." : "Check Status" }}
            </button>
            <button class="button compact" type="button" :disabled="linkedinSessionState.connecting || linkedinSessionState.clearing" @click="connectLinkedIn">
              {{ linkedinSessionState.connecting ? "Waiting For Login..." : "Connect LinkedIn" }}
            </button>
            <button class="button ghost compact settings-danger-button" type="button" :disabled="linkedinSessionState.connecting || linkedinSessionState.clearing" @click="clearLinkedInSession">
              {{ linkedinSessionState.clearing ? "Clearing..." : "Clear Session" }}
            </button>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>
