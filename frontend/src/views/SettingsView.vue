<script setup>
import { onMounted, reactive } from "vue"

import AppIcon from "../components/AppIcon.vue"
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
    config_path: "",
  },
  form: {
    primary_provider: "claude-cli",
    fallback_provider: "",
    allow_fallback: false,
  },
})

function syncForm() {
  state.form.primary_provider = state.data.llm.primary_provider
  state.form.fallback_provider = state.data.llm.fallback_provider || ""
  state.form.allow_fallback = Boolean(state.data.llm.allow_fallback)
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
    })
    syncForm()
    state.message = state.data.message || "Saved"
  } catch (error) {
    state.error = error.message
  } finally {
    state.saving = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <div v-if="state.error" class="banner is-danger">{{ state.error }}</div>
    <div v-if="state.message" class="banner is-success">{{ state.message }}</div>

    <section class="content-grid content-grid-wide">
      <article class="surface surface-narrow">
        <div class="section-head">
          <h2>LLM</h2>
        </div>

        <form class="form-grid" @submit.prevent="save">
          <label class="field">
            <span>Primary</span>
            <AppSelect v-model="state.form.primary_provider" :options="providerOptions" aria-label="Primary provider" />
          </label>

          <label class="field">
            <span>Fallback</span>
            <AppSelect v-model="state.form.fallback_provider" :options="fallbackOptions" aria-label="Fallback provider" />
          </label>

          <label class="checkbox-row">
            <input v-model="state.form.allow_fallback" type="checkbox" />
            <span>Auto fallback</span>
          </label>

          <div class="actions-row">
            <button class="icon-button primary" type="submit" :disabled="state.saving || state.loading" aria-label="Save settings" title="Save settings">
              <AppIcon name="save" />
            </button>
          </div>
        </form>
      </article>

      <article class="surface">
        <div class="section-head">
          <h2>CLI</h2>
          <span class="muted">{{ state.loading ? "..." : "ready" }}</span>
        </div>

        <div class="list-stack">
          <div class="list-row">
            <span>Claude Code CLI</span>
            <span class="chip" :class="{ success: state.data.available_providers['claude-cli'] }">
              {{ state.data.available_providers['claude-cli'] ? "Available" : "Missing" }}
            </span>
          </div>
          <div class="list-row">
            <span>Codex CLI</span>
            <span class="chip" :class="{ success: state.data.available_providers['codex-cli'] }">
              {{ state.data.available_providers['codex-cli'] ? "Available" : "Missing" }}
            </span>
          </div>
          <div class="list-row">
            <span>Config</span>
            <code class="path-label">{{ state.data.config_path }}</code>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>
