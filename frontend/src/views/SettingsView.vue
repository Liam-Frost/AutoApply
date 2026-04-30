<script setup>
import { onMounted, reactive, watch } from "vue"
import {
  AlertCircle,
  CheckCircle2,
  Cpu,
  Database,
  Linkedin,
  RefreshCw,
  Sparkles,
  Trash2,
} from "lucide-vue-next"

import AppSelect from "@/components/AppSelect.vue"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import {
  clearLinkedInSessionStore,
  connectLinkedInSession,
  linkedinSessionState,
  refreshLinkedInSession,
} from "@/lib/linkedin-session"

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
          LLM
        </CardTitle>
        <Badge variant="secondary" class="tabular-nums">
          {{ state.saving ? "Saving..." : "Live" }}
        </Badge>
      </CardHeader>
      <CardContent class="space-y-4">
        <p class="text-xs text-muted-foreground">Provider routing for resume tailoring and form filling.</p>

        <div class="grid gap-4 md:grid-cols-2">
          <label class="space-y-1.5">
            <span class="text-xs font-medium text-muted-foreground">Primary</span>
            <AppSelect v-model="state.form.primary_provider" :options="providerOptions" aria-label="Primary provider" />
          </label>

          <label class="space-y-1.5">
            <span class="text-xs font-medium text-muted-foreground">Fallback</span>
            <AppSelect v-model="state.form.fallback_provider" :options="fallbackOptions" aria-label="Fallback provider" />
          </label>
        </div>

        <label class="flex items-center gap-2 text-sm text-foreground">
          <input v-model="state.form.allow_fallback" type="checkbox" class="h-4 w-4 rounded border-input accent-primary" />
          <span>Auto fallback when the primary provider fails</span>
        </label>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="flex flex-row items-center justify-between space-y-0">
        <CardTitle class="flex items-center gap-2 text-sm">
          <Cpu class="h-4 w-4 text-muted-foreground" />
          CLI
        </CardTitle>
        <Badge variant="secondary" class="tabular-nums">
          {{ state.loading ? "..." : "Ready" }}
        </Badge>
      </CardHeader>
      <CardContent>
        <p class="mb-4 text-xs text-muted-foreground">Runtime availability and config path.</p>
        <div class="space-y-2">
          <div class="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50">
            <span>Claude Code CLI</span>
            <Badge :variant="state.data.available_providers['claude-cli'] ? 'success' : 'secondary'">
              {{ state.data.available_providers['claude-cli'] ? "Available" : "Missing" }}
            </Badge>
          </div>
          <div class="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50">
            <span>Codex CLI</span>
            <Badge :variant="state.data.available_providers['codex-cli'] ? 'success' : 'secondary'">
              {{ state.data.available_providers['codex-cli'] ? "Available" : "Missing" }}
            </Badge>
          </div>
          <div class="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50">
            <span>Config</span>
            <code class="break-all rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">{{ state.data.config_path }}</code>
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
          <input v-model="state.form.cache_enabled" type="checkbox" class="h-4 w-4 rounded border-input accent-primary" />
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
          <div class="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50">
            <span>Saved session</span>
            <Badge :variant="linkedinSessionState.has_session_data ? 'success' : 'secondary'">
              {{ linkedinSessionState.has_session_data ? "Present" : "Empty" }}
            </Badge>
          </div>
          <div class="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50">
            <span>Status</span>
            <span class="text-xs text-muted-foreground">{{ linkedinSessionState.message || "Check LinkedIn session status." }}</span>
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
            :disabled="linkedinSessionState.loading || linkedinSessionState.connecting || linkedinSessionState.clearing"
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
  </div>
</template>
