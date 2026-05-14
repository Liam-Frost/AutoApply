<script setup>
import { computed, onMounted, reactive, ref, watch } from "vue"
import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  Database,
  KeyRound,
  Linkedin,
  Loader2,
  Plug,
  RefreshCw,
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
  await Promise.all([loadSettings(), loadProviders(), loadProviderHealth()])
  state.loading = false
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
          LLM routing
        </CardTitle>
        <Badge variant="secondary" class="tabular-nums">
          {{ state.saving ? "Saving..." : "Live" }}
        </Badge>
      </CardHeader>
      <CardContent class="space-y-4">
        <p class="text-xs text-muted-foreground">
          Choose which provider runs resume tailoring, cover letters, and form filling. Only connected providers can be
          selected.
        </p>

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
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0">
        <CardTitle class="flex items-center gap-2 text-sm">
          <Plug class="h-4 w-4 text-muted-foreground" />
          Providers
        </CardTitle>
        <Badge variant="secondary" class="tabular-nums">
          {{ state.providers.filter((p) => p.configured).length }}/{{ state.providers.length }} connected
        </Badge>
      </CardHeader>
      <CardContent>
        <p class="mb-4 text-xs text-muted-foreground">
          Connect API keys (OpenAI / Anthropic / Gemini), or use the local Claude / Codex CLI. AutoApply only stores the
          key; tokens for the OAuth CLI stay in ~/.codex/.
        </p>

        <div v-if="state.loading && state.providers.length === 0" class="text-sm text-muted-foreground">
          Loading providers...
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
                <!--
                  Phase 11.4: prefer the live health-monitor timestamp
                  over the credential's manual-test breadcrumb. Falls
                  back to credentials.verified_at when the monitor
                  hasn't probed yet (cold start or unconfigured).
                -->
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
                {{ providerOp(provider.id).testing ? "Testing..." : "Test" }}
              </Button>

              <Button
                v-if="provider.configured && !isPrimary(provider)"
                variant="ghost"
                size="sm"
                :disabled="providerOp(provider.id).using"
                @click="useProvider(provider)"
              >
                <CheckCircle2 class="h-4 w-4" />
                {{ providerOp(provider.id).using ? "..." : "Use as primary" }}
              </Button>

              <!--
                API_KEY providers expose a Connect dialog where the
                user pastes their key. Subprocess providers (Claude /
                Codex CLI) deliberately have NO Connect button -- they
                are orchestrated agent CLIs that own their own auth
                (run `claude login` / `codex login` in your shell).
                A future native OAuth provider would reintroduce its
                own Connect affordance here.
              -->
              <Button
                v-if="provider.auth_type === 'api_key'"
                :variant="provider.configured ? 'ghost' : 'default'"
                size="sm"
                @click="openConnectDialog(provider)"
              >
                <KeyRound class="h-4 w-4" />
                {{ provider.configured ? "Update key" : "Connect" }}
              </Button>

              <!--
                Disconnect is shown for:
                  * API-key providers (the normal connect/disconnect flow)
                  * Subprocess providers ONLY when AutoApply has a
                    stored credential record for them. The current
                    subprocess providers never write a record, but
                    users upgrading from the Phase-10 OAuth-wrapper
                    revision may have a stale "managed_by: codex-cli"
                    breadcrumb. Letting them clear it from the UI
                    avoids the misleading "Last verified ..." line
                    sticking around forever.
              -->
              <Button
                v-if="(!isSubprocessProvider(provider) && provider.configured) || hasStoredCredential(provider)"
                variant="ghost"
                size="sm"
                class="text-destructive hover:bg-destructive/10 hover:text-destructive"
                :disabled="providerOp(provider.id).disconnecting"
                @click="disconnectProvider(provider)"
              >
                <Unplug class="h-4 w-4" />
                {{ providerOp(provider.id).disconnecting ? "..." : disconnectLabel(provider) }}
              </Button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0">
        <CardTitle class="flex items-center gap-2 text-sm">
          <Cpu class="h-4 w-4 text-muted-foreground" />
          Local CLI
        </CardTitle>
        <Badge variant="secondary" class="tabular-nums">
          {{ state.loading ? "..." : "Ready" }}
        </Badge>
      </CardHeader>
      <CardContent>
        <p class="mb-4 text-xs text-muted-foreground">Detected CLI binaries and config path.</p>
        <div class="space-y-2">
          <div
            class="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50"
          >
            <span>Claude Code CLI</span>
            <Badge :variant="state.data.available_providers['claude-cli'] ? 'success' : 'secondary'">
              {{ state.data.available_providers["claude-cli"] ? "Available" : "Missing" }}
            </Badge>
          </div>
          <div
            class="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50"
          >
            <span>Codex CLI</span>
            <Badge :variant="state.data.available_providers['codex-cli'] ? 'success' : 'secondary'">
              {{ state.data.available_providers["codex-cli"] ? "Available" : "Missing" }}
            </Badge>
          </div>
          <div
            class="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50"
          >
            <span>Config</span>
            <code class="break-all rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {{ state.data.config_path }}
            </code>
          </div>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0">
        <CardTitle class="flex items-center gap-2 text-sm">
          <Database class="h-4 w-4 text-muted-foreground" />
          Search Cache
        </CardTitle>
        <Badge variant="secondary" class="tabular-nums">
          {{ state.saving ? "Saving..." : "Live" }}
        </Badge>
      </CardHeader>
      <CardContent class="space-y-4">
        <p class="text-xs text-muted-foreground">Reuse recent LinkedIn search results to avoid repeat pulls.</p>

        <label class="grid max-w-xs gap-1.5">
          <span class="text-xs font-medium text-muted-foreground">TTL hours</span>
          <Input v-model="state.form.cache_ttl_hours" type="number" min="1" step="1" />
        </label>

        <label class="flex items-center gap-2 text-sm text-foreground">
          <input
            v-model="state.form.cache_enabled"
            type="checkbox"
            class="h-4 w-4 rounded border-input accent-primary"
          />
          <span>Enable cache</span>
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
            {{ state.cache.clearing ? "Clearing..." : "Clear search cache" }}
          </Button>
        </div>

        <!-- Phase 12.6: pointer to the LLM/embedding cache inspector.
             Search cache is the older, simpler file-backed cache; the
             new Redis-backed L1+L2 cache lives at /settings/cache. -->
        <div class="pt-2 border-t">
          <router-link
            to="/settings/cache"
            class="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
          >
            LLM + embedding cache inspector
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
