<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue"
import {
  AlertCircle,
  CheckCircle2,
  Database,
  FileText,
  KeyRound,
  Linkedin,
  Loader2,
  Plug,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
  Unplug,
} from "lucide-vue-next"

import AppSelect from "@/components/AppSelect.vue"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { api } from "@/lib/api"
import {
  clearLinkedInSessionStore,
  connectLinkedInSession,
  linkedinSessionState,
  refreshLinkedInSession,
} from "@/lib/linkedin-session"

const fallbackOptions = computed(() => [
  { value: "", label: "Disabled" },
  ...primaryOptions.value.filter((option) => option.value !== state.form.primary_provider),
])

const primaryOptions = computed(() => {
  const configured = state.providers.filter((provider) => provider.configured)
  if (configured.length === 0) {
    // While we wait for the registry to load, show whatever the
    // settings file currently points to so the select isn't empty.
    return [{ value: state.form.primary_provider, label: state.form.primary_provider || "..." }]
  }
  return configured.map((provider) => ({
    value: provider.id,
    label: provider.display_name,
  }))
})

const state = reactive({
  loading: true,
  saving: false,
  suspendAutosave: false,
  error: "",
  message: "",
  cache: {
    clearing: false,
  },
  providers: [],
  providerOps: reactive({}), // { [providerId]: { testing, connecting, disconnecting, using } }
  // Phase 11.4: live health snapshot from the background monitor.
  // Map of provider_id -> { ok, detail, latency_ms, checked_at }.
  providerHealth: reactive({}),
  providerHealthMeta: reactive({
    last_run_finished_at: "",
    interval_seconds: 300,
    running: false,
    refreshing: false,
  }),
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
    job_index: {
      known: false,
      search_queries: 0,
      job_postings: 0,
      job_snapshots: 0,
      latest_success_at: null,
      states: {},
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
  // Phase 17.8: per-document-type material strategy defaults.
  materialDefaults: {
    loading: true,
    saving: false,
    error: "",
    message: "",
    templates: { resume: [], cover_letter: [] },
    documents: { resume: [], cover_letter: [] },
    form: {
      resume: { strategy: "regenerate", default_template_id: "", default_document_id: "" },
      cover_letter: { strategy: "regenerate", default_template_id: "", default_document_id: "" },
    },
  },
})

const connectDialog = reactive({
  open: false,
  providerId: "",
  providerLabel: "",
  apiKey: "",
  model: "",
  baseUrl: "",
  submitting: false,
  error: "",
})


function providerOp(providerId) {
  if (!state.providerOps[providerId]) {
    state.providerOps[providerId] = {
      testing: false,
      connecting: false,
      disconnecting: false,
      using: false,
    }
  }
  return state.providerOps[providerId]
}

function authTypeLabel(authType) {
  return (
    {
      api_key: "API key",
      oauth: "OAuth",
      subprocess: "Local CLI",
    }[authType] || authType
  )
}

function syncForm() {
  state.form.primary_provider = state.data.llm.primary_provider
  state.form.fallback_provider = state.data.llm.fallback_provider || ""
  state.form.allow_fallback = Boolean(state.data.llm.allow_fallback)
  state.form.cache_enabled = Boolean(state.data.search_cache?.enabled)
  state.form.cache_ttl_hours = state.data.search_cache?.ttl_hours ?? 24
}

async function loadSettings() {
  state.suspendAutosave = true
  try {
    state.data = await api.settings()
    syncForm()
  } catch (error) {
    state.error = error.message
  } finally {
    state.suspendAutosave = false
  }
}

async function loadProviders() {
  try {
    const payload = await api.providers()
    if (!payload.ok) {
      state.error = payload.error || "Failed to load providers."
      return
    }
    state.providers = payload.providers || []
  } catch (error) {
    state.error = error.message
  }
}

async function loadProviderHealth() {
  // Phase 11.4: pull the cached background-probe snapshot. Failures
  // are swallowed -- the Settings page still works without health data,
  // and the monitor might just not have run a tick yet.
  try {
    const snapshot = await api.providersHealth()
    state.providerHealth = snapshot.records || {}
    state.providerHealthMeta.last_run_finished_at = snapshot.last_run_finished_at || ""
    state.providerHealthMeta.interval_seconds = snapshot.interval_seconds ?? 300
    state.providerHealthMeta.running = Boolean(snapshot.running)
  } catch (_error) {
    // Non-fatal -- the credential timestamp still renders as a fallback.
  }
}

async function refreshProviderHealth() {
  if (state.providerHealthMeta.refreshing) return
  state.providerHealthMeta.refreshing = true
  try {
    const snapshot = await api.refreshProvidersHealth()
    state.providerHealth = snapshot.records || {}
    state.providerHealthMeta.last_run_finished_at = snapshot.last_run_finished_at || ""
    state.providerHealthMeta.running = Boolean(snapshot.running)
  } catch (error) {
    state.error = error.message
  } finally {
    state.providerHealthMeta.refreshing = false
  }
}

function providerHealthFor(provider) {
  return state.providerHealth?.[provider.id] || null
}

async function refreshAll() {
  state.loading = true
  state.error = ""
  await Promise.all([
    loadSettings(),
    loadProviders(),
    loadProviderHealth(),
    loadMaterialDefaults(),
  ])
  state.loading = false
}

const MATERIAL_STRATEGY_OPTIONS = [
  { value: "regenerate", label: "Regenerate from a template" },
  { value: "patch_existing", label: "Patch a document from my library" },
]

function materialTemplateOptions(docType) {
  return [
    { value: "", label: "System default" },
    ...((state.materialDefaults.templates[docType] || []).map((tpl) => ({
      value: tpl.template_id,
      label: tpl.name || tpl.template_id,
    }))),
  ]
}

function materialDocumentOptions(docType) {
  const docs = state.materialDefaults.documents[docType] || []
  return [
    {
      value: "",
      label: docs.length
        ? "Pick a document from your library"
        : "No editable documents in your library",
    },
    ...docs.map((doc) => ({
      value: doc.id,
      label: `${doc.display_name} · ${doc.source_type.toUpperCase()}`,
    })),
  ]
}

function materialDocTypeLabel(docType) {
  return docType === "resume" ? "Resume" : "Cover Letter"
}

async function loadMaterialDefaults() {
  state.materialDefaults.loading = true
  state.materialDefaults.error = ""
  try {
    const [defaults, templates, documents] = await Promise.all([
      api.materialDefaults(),
      api.templates(),
      api.documents(),
    ])
    state.materialDefaults.templates = {
      resume: templates?.templates?.resume || [],
      cover_letter: templates?.templates?.cover_letter || [],
    }
    const docs = documents?.documents || []
    state.materialDefaults.documents = {
      resume: docs.filter((d) => d.document_type === "resume" && d.editable),
      cover_letter: docs.filter((d) => d.document_type === "cover_letter" && d.editable),
    }
    const loaded = defaults?.defaults || {}
    for (const docType of ["resume", "cover_letter"]) {
      const entry = loaded[docType] || {}
      state.materialDefaults.form[docType] = {
        strategy: entry.strategy || "regenerate",
        default_template_id: entry.default_template_id || "",
        default_document_id: entry.default_document_id || "",
      }
    }
  } catch (err) {
    state.materialDefaults.error = err?.message || "Couldn't load material defaults."
  } finally {
    state.materialDefaults.loading = false
  }
}

async function saveMaterialDefaults() {
  state.materialDefaults.saving = true
  state.materialDefaults.error = ""
  state.materialDefaults.message = ""
  try {
    await api.updateMaterialDefaults({
      resume: state.materialDefaults.form.resume,
      cover_letter: state.materialDefaults.form.cover_letter,
    })
    state.materialDefaults.message = "Saved."
  } catch (err) {
    state.materialDefaults.error = err?.message || "Couldn't save material defaults."
  } finally {
    state.materialDefaults.saving = false
  }
}

async function persistSettings({ keepMessage = false } = {}) {
  if (state.loading || state.suspendAutosave) {
    return
  }
  state.saving = true
  state.error = ""
  if (!keepMessage) state.message = ""
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

function openConnectDialog(provider) {
  connectDialog.providerId = provider.id
  connectDialog.providerLabel = provider.display_name
  connectDialog.apiKey = ""
  connectDialog.model = provider.credentials?.metadata?.model || ""
  connectDialog.baseUrl = provider.credentials?.metadata?.base_url || ""
  connectDialog.error = ""
  connectDialog.submitting = false
  connectDialog.open = true
}

async function submitConnect() {
  if (!connectDialog.apiKey.trim()) {
    connectDialog.error = "API key is required."
    return
  }
  connectDialog.submitting = true
  connectDialog.error = ""
  state.error = ""
  try {
    const payload = await api.connectApiKeyProvider(connectDialog.providerId, {
      api_key: connectDialog.apiKey,
      model: connectDialog.model || null,
      base_url: connectDialog.baseUrl || null,
    })
    await loadProviders()
    if (payload.ok) {
      state.message = `${connectDialog.providerLabel} connected and verified.`
      connectDialog.open = false
    } else {
      connectDialog.error =
        payload.error || "Key saved but verification failed. Check the key and try Test again."
    }
  } catch (error) {
    connectDialog.error = error.message
  } finally {
    connectDialog.submitting = false
  }
}

async function testProvider(provider) {
  const op = providerOp(provider.id)
  op.testing = true
  state.error = ""
  state.message = ""
  try {
    const result = await api.testProvider(provider.id)
    await loadProviders()
    if (result.ok) {
      state.message = `${provider.display_name}: ${result.result?.detail || "OK"}`
    } else {
      state.error = `${provider.display_name}: ${result.error || result.result?.detail || "probe failed"}`
    }
  } catch (error) {
    state.error = error.message
  } finally {
    op.testing = false
  }
}

async function disconnectProvider(provider) {
  if (!window.confirm(`Disconnect ${provider.display_name}? The saved credential will be removed.`)) {
    return
  }
  const op = providerOp(provider.id)
  op.disconnecting = true
  state.error = ""
  state.message = ""
  try {
    const result = await api.disconnectProvider(provider.id)
    await loadProviders()
    if (result.ok) {
      state.message = result.message || `Disconnected ${provider.display_name}.`
    } else {
      state.error = result.error
    }
  } catch (error) {
    state.error = error.message
  } finally {
    op.disconnecting = false
  }
}

async function useProvider(provider) {
  const op = providerOp(provider.id)
  op.using = true
  state.error = ""
  state.message = ""
  state.suspendAutosave = true
  try {
    const result = await api.useProvider(provider.id, null)
    if (result.ok) {
      state.message = result.message
      await loadSettings()
    } else {
      state.error = result.error
    }
  } catch (error) {
    state.error = error.message
  } finally {
    op.using = false
    state.suspendAutosave = false
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

async function connectLinkedIn() {
  await connectLinkedInSession()
}

async function clearLinkedInSession() {
  await clearLinkedInSessionStore()
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

onMounted(refreshAll)

function providerStatusVariant(provider) {
  // Subprocess providers (claude / codex CLI) only know "binary on PATH"
  // -- they cannot tell us whether the user has actually run `claude
  // login`. Showing "Connected" for an unauthenticated CLI would mislead
  // users into thinking everything's wired up. We mirror the local-CLI
  // semantics: green = available on PATH; nothing stronger.
  if (provider.auth_type === "subprocess") {
    return provider.installed ? "success" : "secondary"
  }
  return provider.configured ? "success" : "secondary"
}

function providerStatusLabel(provider) {
  if (provider.auth_type === "subprocess") {
    return provider.installed ? "Available" : "Missing"
  }
  return provider.configured ? "Connected" : "Not connected"
}

function isSubprocessProvider(provider) {
  return provider.auth_type === "subprocess"
}

/**
 * Did AutoApply store a credential record for this provider?
 *
 * For API-key providers this is "yes, user pasted a key".
 * For subprocess providers this should normally be "no" -- the CLI
 * owns its own auth and we don't store anything. The exception is
 * users upgrading from the older Phase-10 OAuth-wrapper revision,
 * who may have a "managed_by: codex-cli" breadcrumb left over. We
 * surface that as a stored credential so the Disconnect button is
 * available to clean it up.
 */
function hasStoredCredential(provider) {
  return Boolean(provider.credentials && provider.credentials.has_secret)
}

function formatJobIndexDate(value) {
  return value ? new Date(value).toLocaleString() : "Never"
}

function jobIndexStateCount(stateName) {
  return state.data.job_index?.states?.[stateName] || 0
}

function disconnectLabel(provider) {
  if (isSubprocessProvider(provider) && hasStoredCredential(provider)) {
    return "Clear stored record"
  }
  return "Disconnect"
}

function isPrimary(provider) {
  return state.form.primary_provider === provider.id
}
</script>

<template>
  <div class="space-y-6">
    <Alert v-if="state.error" variant="destructive">
      <AlertCircle class="h-4 w-4" />
      <AlertDescription>{{ state.error }}</AlertDescription>
    </Alert>
    <Alert v-if="state.message" variant="success">
      <CheckCircle2 class="h-4 w-4" />
      <AlertDescription>{{ state.message }}</AlertDescription>
    </Alert>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0">
        <CardTitle class="flex items-center gap-2 text-sm">
          <Sparkles class="h-4 w-4 text-muted-foreground" />
          AI Providers
        </CardTitle>
        <Badge variant="secondary" class="tabular-nums">
          {{ state.providers.filter((p) => p.configured).length }}/{{ state.providers.length }} connected
          <span v-if="state.saving" class="ml-2 text-[10px] uppercase tracking-wide">Saving…</span>
        </Badge>
      </CardHeader>
      <CardContent class="space-y-6">
        <p class="text-xs text-muted-foreground">
          Connect API keys (OpenAI / Anthropic / Gemini) or use the local Claude / Codex CLI, then pick which provider AutoApply uses for resume tailoring, cover letters, and form filling.
        </p>

        <!-- Sub-section: Routing -->
        <section class="space-y-3">
          <h3 class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Routing
          </h3>
          <div class="grid gap-4 md:grid-cols-2">
            <label class="space-y-1.5">
              <span class="text-xs font-medium text-muted-foreground">Primary</span>
              <AppSelect
                v-model="state.form.primary_provider"
                :options="primaryOptions"
                aria-label="Primary provider"
              />
            </label>

            <label class="space-y-1.5">
              <span class="text-xs font-medium text-muted-foreground">Fallback</span>
              <AppSelect
                v-model="state.form.fallback_provider"
                :options="fallbackOptions"
                aria-label="Fallback provider"
              />
            </label>
          </div>

          <label class="flex items-center gap-2 text-sm text-foreground">
            <input
              v-model="state.form.allow_fallback"
              type="checkbox"
              class="h-4 w-4 rounded border-input accent-primary"
            />
            <span>Auto fallback when the primary provider fails</span>
          </label>
        </section>

        <div class="border-t border-border"></div>

        <!-- Sub-section: Connected providers -->
        <section class="space-y-3">
          <h3 class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Connected Providers
          </h3>

          <div v-if="state.loading && state.providers.length === 0" class="text-sm text-muted-foreground">
            Loading providers…
          </div>

          <div v-else class="space-y-2">
            <div
              v-for="provider in state.providers"
              :key="provider.id"
              class="flex flex-col gap-3 rounded-md border border-border bg-card px-3 py-3 text-sm transition-colors hover:bg-muted/30 sm:flex-row sm:items-center sm:justify-between"
            >
              <div class="min-w-0 flex-1 space-y-1">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-medium text-foreground">{{ provider.display_name }}</span>
                  <Badge variant="outline" class="text-[10px] uppercase tracking-wide">
                    {{ authTypeLabel(provider.auth_type) }}
                  </Badge>
                  <Badge v-if="isPrimary(provider)" variant="default" class="text-[10px] uppercase tracking-wide">
                    Primary
                  </Badge>
                  <Badge :variant="providerStatusVariant(provider)" class="text-[10px] uppercase tracking-wide">
                    {{ providerStatusLabel(provider) }}
                  </Badge>
                </div>
                <div class="text-xs text-muted-foreground">
                  <span v-if="provider.credentials?.connected_at">
                    Connected {{ new Date(provider.credentials.connected_at).toLocaleString() }}.
                  </span>
                  <span v-if="providerHealthFor(provider)">
                    Last verified {{ new Date(providerHealthFor(provider).checked_at).toLocaleString() }}
                    ({{ providerHealthFor(provider).ok ? "OK" : "FAIL" }}).
                  </span>
                  <span
                    v-else-if="provider.credentials?.verified_at"
                  >
                    Last verified {{ new Date(provider.credentials.verified_at).toLocaleString() }}.
                  </span>
                  <span v-if="!provider.configured && provider.install_hint">{{ provider.install_hint }}</span>
                  <span
                    v-if="providerHealthFor(provider) && !providerHealthFor(provider).ok"
                    class="text-destructive"
                  >
                    Health: {{ providerHealthFor(provider).detail }}
                  </span>
                  <span
                    v-else-if="provider.credentials?.last_test_error"
                    class="text-destructive"
                  >
                    Last error: {{ provider.credentials.last_test_error }}
                  </span>
                </div>
              </div>

              <div class="flex flex-wrap items-center gap-1.5">
                <Button
                  v-if="provider.configured"
                  variant="ghost"
                  size="sm"
                  :disabled="providerOp(provider.id).testing"
                  @click="testProvider(provider)"
                >
                  <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': providerOp(provider.id).testing }" />
                  {{ providerOp(provider.id).testing ? "Testing…" : "Test" }}
                </Button>

                <Button
                  v-if="provider.configured && !isPrimary(provider)"
                  variant="ghost"
                  size="sm"
                  :disabled="providerOp(provider.id).using"
                  @click="useProvider(provider)"
                >
                  <CheckCircle2 class="h-4 w-4" />
                  {{ providerOp(provider.id).using ? "…" : "Use as primary" }}
                </Button>

                <Button
                  v-if="provider.auth_type === 'api_key'"
                  :variant="provider.configured ? 'ghost' : 'default'"
                  size="sm"
                  @click="openConnectDialog(provider)"
                >
                  <KeyRound class="h-4 w-4" />
                  {{ provider.configured ? "Update key" : "Connect" }}
                </Button>

                <Button
                  v-if="(!isSubprocessProvider(provider) && provider.configured) || hasStoredCredential(provider)"
                  variant="ghost"
                  size="sm"
                  class="text-destructive hover:bg-destructive/10 hover:text-destructive"
                  :disabled="providerOp(provider.id).disconnecting"
                  @click="disconnectProvider(provider)"
                >
                  <Unplug class="h-4 w-4" />
                  {{ providerOp(provider.id).disconnecting ? "…" : disconnectLabel(provider) }}
                </Button>
              </div>
            </div>
          </div>
        </section>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0">
        <CardTitle class="flex items-center gap-2 text-sm">
          <FileText class="h-4 w-4 text-muted-foreground" />
          Default Material Strategy
        </CardTitle>
        <Badge variant="secondary" class="tabular-nums">
          {{ state.materialDefaults.saving ? "Saving…" : "Live" }}
        </Badge>
      </CardHeader>
      <CardContent class="space-y-5">
        <p class="text-xs text-muted-foreground">
          What AutoApply should do every time it builds a resume or cover letter. Per-job picks on the Jobs page and per-plan picks in Plans always win over these defaults.
        </p>

        <Alert v-if="state.materialDefaults.error" variant="destructive">
          <AlertCircle class="h-4 w-4" />
          <AlertDescription>{{ state.materialDefaults.error }}</AlertDescription>
        </Alert>
        <Alert v-if="state.materialDefaults.message" class="border-primary/40 bg-primary/5">
          <CheckCircle2 class="h-4 w-4" />
          <AlertDescription>{{ state.materialDefaults.message }}</AlertDescription>
        </Alert>

        <div v-for="docType in ['resume', 'cover_letter']" :key="docType" class="space-y-3 rounded-md border bg-muted/20 p-3">
          <div class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {{ materialDocTypeLabel(docType) }}
          </div>
          <div class="grid gap-3 md:grid-cols-2">
            <label class="space-y-1.5">
              <span class="text-xs font-medium text-muted-foreground">Strategy</span>
              <AppSelect
                v-model="state.materialDefaults.form[docType].strategy"
                :options="MATERIAL_STRATEGY_OPTIONS"
                :aria-label="`${materialDocTypeLabel(docType)} strategy`"
              />
            </label>
            <label
              v-if="state.materialDefaults.form[docType].strategy === 'regenerate'"
              class="space-y-1.5"
            >
              <span class="text-xs font-medium text-muted-foreground">Default template</span>
              <AppSelect
                v-model="state.materialDefaults.form[docType].default_template_id"
                :options="materialTemplateOptions(docType)"
                :aria-label="`${materialDocTypeLabel(docType)} default template`"
              />
            </label>
            <label
              v-else
              class="space-y-1.5"
            >
              <span class="text-xs font-medium text-muted-foreground">Document to patch</span>
              <AppSelect
                v-model="state.materialDefaults.form[docType].default_document_id"
                :options="materialDocumentOptions(docType)"
                :aria-label="`${materialDocTypeLabel(docType)} library document`"
              />
              <span class="text-xs text-muted-foreground">
                Patching is supported for DOCX resumes today; LaTeX and PDF documents fall back to regenerate with a warning.
              </span>
            </label>
          </div>
        </div>

        <div class="flex items-center justify-end">
          <Button
            size="sm"
            :disabled="state.materialDefaults.loading || state.materialDefaults.saving"
            @click="saveMaterialDefaults"
          >
            <Save class="size-4" />
            {{ state.materialDefaults.saving ? "Saving…" : "Save defaults" }}
          </Button>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0">
        <CardTitle class="flex items-center gap-2 text-sm">
          <Database class="h-4 w-4 text-muted-foreground" />
          LinkedIn Search Index
        </CardTitle>
        <Badge variant="secondary" class="tabular-nums">
          {{ state.saving ? "Saving..." : "Live" }}
        </Badge>
      </CardHeader>
      <CardContent class="space-y-4">
        <p class="text-xs text-muted-foreground">
          Controls whether normal Jobs searches reuse fresh Phase 13 indexed LinkedIn results. Fetch Fresh on the Jobs
          page always bypasses this policy and updates the index.
        </p>

        <div class="grid gap-2 sm:grid-cols-4">
          <div class="rounded-md border border-border bg-muted/30 px-3 py-2">
            <div class="text-[11px] uppercase tracking-wide text-muted-foreground">Searches</div>
            <div class="text-lg font-semibold tabular-nums">
              {{ state.data.job_index?.known ? state.data.job_index.search_queries : "-" }}
            </div>
          </div>
          <div class="rounded-md border border-border bg-muted/30 px-3 py-2">
            <div class="text-[11px] uppercase tracking-wide text-muted-foreground">Postings</div>
            <div class="text-lg font-semibold tabular-nums">
              {{ state.data.job_index?.known ? state.data.job_index.job_postings : "-" }}
            </div>
          </div>
          <div class="rounded-md border border-border bg-muted/30 px-3 py-2">
            <div class="text-[11px] uppercase tracking-wide text-muted-foreground">Snapshots</div>
            <div class="text-lg font-semibold tabular-nums">
              {{ state.data.job_index?.known ? state.data.job_index.job_snapshots : "-" }}
            </div>
          </div>
          <div class="rounded-md border border-border bg-muted/30 px-3 py-2">
            <div class="text-[11px] uppercase tracking-wide text-muted-foreground">Latest refresh</div>
            <div class="text-xs font-medium">
              {{ formatJobIndexDate(state.data.job_index?.latest_success_at) }}
            </div>
          </div>
        </div>

        <div v-if="state.data.job_index?.known" class="flex flex-wrap gap-2 text-xs text-muted-foreground">
          <span class="chip subtle">Fresh {{ jobIndexStateCount("active") }}</span>
          <span class="chip subtle">Stale {{ jobIndexStateCount("stale") }}</span>
          <span class="chip subtle">Unknown {{ jobIndexStateCount("unknown") }}</span>
          <span class="chip subtle">Expired {{ jobIndexStateCount("expired") }}</span>
        </div>
        <Alert v-else variant="warning">
          <AlertCircle class="h-4 w-4" />
          <AlertDescription>{{ state.data.job_index?.warning || "Job Index status is unavailable." }}</AlertDescription>
        </Alert>

        <label class="grid max-w-xs gap-1.5">
          <span class="text-xs font-medium text-muted-foreground">Freshness TTL hours</span>
          <Input v-model="state.form.cache_ttl_hours" type="number" min="1" step="1" />
        </label>

        <label class="flex items-center gap-2 text-sm text-foreground">
          <input
            v-model="state.form.cache_enabled"
            type="checkbox"
            class="h-4 w-4 rounded border-input accent-primary"
          />
          <span>Use indexed results by default</span>
        </label>

        <div>
          <Button
            variant="ghost"
            size="sm"
            type="button"
            class="text-destructive hover:bg-destructive/10 hover:text-destructive"
            :disabled="state.cache.clearing"
            @click="clearSearchCache"
          >
            <Trash2 class="h-4 w-4" />
            {{ state.cache.clearing ? "Clearing..." : "Clear indexed searches" }}
          </Button>
        </div>

        <!-- Phase 12.6: pointer to the runtime cache inspector. -->
        <div class="pt-2 border-t">
          <router-link
            to="/settings/cache"
            class="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
          >
            Open Runtime Cache inspector (LLM / embedding / response)
            <span aria-hidden="true">→</span>
          </router-link>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0">
        <CardTitle class="flex items-center gap-2 text-sm">
          <Linkedin class="h-4 w-4 text-muted-foreground" />
          LinkedIn
        </CardTitle>
        <Badge :variant="linkedinSessionState.authenticated ? 'success' : 'secondary'">
          {{ linkedinSessionState.authenticated ? "Connected" : "Not connected" }}
        </Badge>
      </CardHeader>
      <CardContent class="space-y-4">
        <p class="text-xs text-muted-foreground">Manage the saved browser session used for authenticated search.</p>

        <div class="space-y-2">
          <div
            class="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50"
          >
            <span>Saved session</span>
            <Badge :variant="linkedinSessionState.has_session_data ? 'success' : 'secondary'">
              {{ linkedinSessionState.has_session_data ? "Present" : "Empty" }}
            </Badge>
          </div>
          <div
            class="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50"
          >
            <span>Status</span>
            <span class="text-xs text-muted-foreground">
              {{ linkedinSessionState.message || "Check LinkedIn session status." }}
            </span>
          </div>
        </div>

        <Alert v-if="linkedinSessionState.error" variant="destructive">
          <AlertCircle class="h-4 w-4" />
          <AlertDescription>{{ linkedinSessionState.error }}</AlertDescription>
        </Alert>

        <div class="flex flex-wrap gap-2">
          <Button
            variant="ghost"
            size="sm"
            type="button"
            :disabled="
              linkedinSessionState.loading || linkedinSessionState.connecting || linkedinSessionState.clearing
            "
            @click="refreshLinkedInSession"
          >
            <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': linkedinSessionState.loading }" />
            {{ linkedinSessionState.loading ? "Checking..." : "Check status" }}
          </Button>
          <Button
            size="sm"
            type="button"
            :disabled="linkedinSessionState.connecting || linkedinSessionState.clearing"
            @click="connectLinkedIn"
          >
            <Linkedin class="h-4 w-4" />
            {{ linkedinSessionState.connecting ? "Waiting for login..." : "Connect LinkedIn" }}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            type="button"
            class="text-destructive hover:bg-destructive/10 hover:text-destructive"
            :disabled="linkedinSessionState.connecting || linkedinSessionState.clearing"
            @click="clearLinkedInSession"
          >
            <Trash2 class="h-4 w-4" />
            {{ linkedinSessionState.clearing ? "Clearing..." : "Clear session" }}
          </Button>
        </div>
      </CardContent>
    </Card>

    <!-- Connect (API key) dialog ----------------------------------------- -->
    <Dialog v-model:open="connectDialog.open">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Connect {{ connectDialog.providerLabel }}</DialogTitle>
          <DialogDescription>
            The key is stored locally under data/providers/credentials.json with permission 0600 and is never logged.
          </DialogDescription>
        </DialogHeader>

        <div class="space-y-3 py-2">
          <div class="space-y-1.5">
            <Label for="api-key">API key</Label>
            <Input
              id="api-key"
              v-model="connectDialog.apiKey"
              type="password"
              autocomplete="off"
              spellcheck="false"
              placeholder="sk-..."
            />
          </div>
          <div class="grid gap-3 sm:grid-cols-2">
            <div class="space-y-1.5">
              <Label for="api-model">Model (optional)</Label>
              <Input id="api-model" v-model="connectDialog.model" placeholder="e.g. gpt-4o-mini" />
            </div>
            <div class="space-y-1.5">
              <Label for="api-base-url">Base URL (optional)</Label>
              <Input id="api-base-url" v-model="connectDialog.baseUrl" placeholder="https://api.openai.com/v1" />
            </div>
          </div>

          <Alert v-if="connectDialog.error" variant="destructive">
            <AlertCircle class="h-4 w-4" />
            <AlertDescription>{{ connectDialog.error }}</AlertDescription>
          </Alert>
        </div>

        <DialogFooter>
          <Button variant="ghost" @click="connectDialog.open = false">Cancel</Button>
          <Button :disabled="connectDialog.submitting || !connectDialog.apiKey.trim()" @click="submitConnect">
            <Loader2 v-if="connectDialog.submitting" class="h-4 w-4 animate-spin" />
            {{ connectDialog.submitting ? "Saving and testing..." : "Save and test" }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

  </div>
</template>
