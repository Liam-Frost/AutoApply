<script setup>
import { onMounted, reactive } from "vue"

import AppSelect from "../components/AppSelect.vue"
import { api } from "../lib/api"

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
  error: "",
  message: "",
  linkedin: {
    loading: false,
    connecting: false,
    clearing: false,
    authenticated: false,
    has_session_data: false,
    message: "",
    error: "",
  },
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

  try {
    state.data = await api.settings()
    syncForm()
  } catch (error) {
    state.error = error.message
  } finally {
    state.loading = false
  }

  await loadLinkedInSession()
}

async function save() {
  state.saving = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.updateSettings({
      primary_provider: state.form.primary_provider,
      fallback_provider: state.form.fallback_provider || null,
      allow_fallback: state.form.allow_fallback,
      cache_enabled: state.form.cache_enabled,
      cache_ttl_hours: Number(state.form.cache_ttl_hours) || 24,
    })
    syncForm()
    state.message = state.data.message || "Saved"
  } catch (error) {
    state.error = error.message
  } finally {
    state.saving = false
  }
}

async function loadLinkedInSession() {
  state.linkedin.loading = true
  state.linkedin.error = ""

  try {
    syncLinkedInSession(await api.linkedinSession())
  } catch (error) {
    state.linkedin.error = error.message
    state.linkedin.message = ""
  } finally {
    state.linkedin.loading = false
  }
}

async function connectLinkedIn() {
  state.linkedin.connecting = true
  state.linkedin.error = ""
  state.linkedin.message = "Finish LinkedIn sign-in in the opened browser window."

  try {
    syncLinkedInSession(await api.connectLinkedIn())
  } catch (error) {
    state.linkedin.error = error.message
  } finally {
    state.linkedin.connecting = false
  }
}

async function clearLinkedInSession() {
  state.linkedin.clearing = true
  state.linkedin.error = ""

  try {
    syncLinkedInSession(await api.clearLinkedInSession())
  } catch (error) {
    state.linkedin.error = error.message
  } finally {
    state.linkedin.clearing = false
  }
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

function syncLinkedInSession(payload) {
  state.linkedin.authenticated = Boolean(payload.authenticated)
  state.linkedin.has_session_data = Boolean(payload.has_session_data)
  state.linkedin.message = payload.message || ""
  state.linkedin.error = payload.ok === false ? payload.message || payload.error || "" : ""
}

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
            <div class="muted-inline">Provider routing and local CLI availability</div>
          </div>
          <button class="button compact" type="button" :disabled="state.saving || state.loading" @click="save">
            {{ state.saving ? "Saving..." : "Save" }}
          </button>
        </div>

        <form class="form-grid settings-form" @submit.prevent="save">
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

          <label class="checkbox-row settings-checkbox-row">
            <input v-model="state.form.allow_fallback" type="checkbox" />
            <span>Auto fallback</span>
          </label>
        </form>

        <div class="settings-divider"></div>

        <div class="page-stack settings-subsection">
          <div class="section-head settings-subhead">
            <div>
              <h3>CLI</h3>
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
        </div>

        <div class="settings-divider"></div>

        <div class="page-stack settings-subsection">
          <div class="section-head settings-subhead">
            <div>
              <h3>Search Cache</h3>
              <div class="muted-inline">Reuse recent LinkedIn search results to avoid repeat pulls</div>
            </div>
          </div>

          <div class="settings-grid settings-grid-2">
            <label class="checkbox-row settings-checkbox-row">
              <input v-model="state.form.cache_enabled" type="checkbox" />
              <span>Enable cache</span>
            </label>

            <label class="field">
              <span>TTL Hours</span>
              <input v-model="state.form.cache_ttl_hours" class="input" type="number" min="1" step="1" />
            </label>
          </div>

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
          <span class="chip" :class="{ success: state.linkedin.authenticated }">
            {{ state.linkedin.authenticated ? "Connected" : "Not connected" }}
          </span>
        </div>

        <div class="page-stack settings-subsection">
          <div class="list-row settings-row">
            <span>Saved session</span>
            <span class="chip" :class="{ success: state.linkedin.has_session_data }">
              {{ state.linkedin.has_session_data ? "Present" : "Empty" }}
            </span>
          </div>

          <div class="list-row settings-row settings-row-status">
            <span>Status</span>
            <span class="muted-inline">{{ state.linkedin.message || "Check LinkedIn session status." }}</span>
          </div>

          <div v-if="state.linkedin.error" class="banner is-danger">{{ state.linkedin.error }}</div>

          <div class="actions-row settings-actions-row">
            <button class="button ghost compact" type="button" :disabled="state.linkedin.loading || state.linkedin.connecting || state.linkedin.clearing" @click="loadLinkedInSession">
              {{ state.linkedin.loading ? "Checking..." : "Check Status" }}
            </button>
            <button class="button compact" type="button" :disabled="state.linkedin.connecting || state.linkedin.clearing" @click="connectLinkedIn">
              {{ state.linkedin.connecting ? "Waiting For Login..." : "Connect LinkedIn" }}
            </button>
            <button class="button ghost compact settings-danger-button" type="button" :disabled="state.linkedin.connecting || state.linkedin.clearing" @click="clearLinkedInSession">
              {{ state.linkedin.clearing ? "Clearing..." : "Clear Session" }}
            </button>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>
