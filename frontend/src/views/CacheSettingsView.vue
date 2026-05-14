<script setup>
// Phase 12.6 -- Cache inspector view at /settings/cache.
//
// Renders the L1+L2 cache snapshot returned by `/api/cache`:
//   * Redis health bar (PONG / connection detail / latency).
//   * Hit / miss / write counters with $-saved estimate.
//   * Per-namespace card: entry count, TTL, one-click clear (modal-
//     gated). Mirrors `autoapply redis flush --namespace` semantics:
//     no destructive action without an explicit confirmation step.

import { computed, onMounted, reactive, ref } from "vue"
import { AlertCircle, CheckCircle2, Database, Loader2, RefreshCw, Trash2 } from "lucide-vue-next"
import { useRouter } from "vue-router"

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
import { api } from "@/lib/api"

const router = useRouter()

const state = reactive({
  loading: true,
  error: "",
  message: "",
  refreshing: false,
  snapshot: null,
  // Per-namespace mutation state so a click on one card doesn't
  // disable buttons elsewhere.
  clearing: reactive({}),
})

const clearDialog = reactive({
  open: false,
  namespace: "",
  entries: null,
})

const totalRequests = computed(() => {
  if (!state.snapshot) return 0
  const s = state.snapshot.stats
  return (s.hits_l1 || 0) + (s.hits_l2 || 0) + (s.misses || 0)
})

const hitRate = computed(() => {
  if (!state.snapshot) return null
  const s = state.snapshot.stats
  const hits = (s.hits_l1 || 0) + (s.hits_l2 || 0)
  const total = hits + (s.misses || 0)
  if (total === 0) return null
  return hits / total
})

function formatTtl(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return "-"
  if (seconds >= 86400) {
    const days = Math.round(seconds / 86400)
    return `${days}d`
  }
  if (seconds >= 3600) {
    const hours = Math.round(seconds / 3600)
    return `${hours}h`
  }
  if (seconds >= 60) {
    const minutes = Math.round(seconds / 60)
    return `${minutes}m`
  }
  return `${seconds}s`
}

function formatEntries(count) {
  if (count === null || count === undefined) return "-"
  if (count < 0) return "?"  // SCAN failed
  return count.toLocaleString()
}

function formatDollars(usd) {
  if (!Number.isFinite(usd)) return "$0.00"
  return `$${usd.toFixed(2)}`
}

async function loadSnapshot() {
  state.loading = state.snapshot === null
  state.refreshing = true
  state.error = ""
  try {
    state.snapshot = await api.cacheSnapshot()
  } catch (err) {
    // The cache must never be a hard failure for the user; show the
    // error inline and keep whatever stale snapshot we had.
    state.error = err?.message || "Failed to load cache snapshot."
  } finally {
    state.loading = false
    state.refreshing = false
  }
}

function openClearDialog(namespace, entries) {
  clearDialog.namespace = namespace
  clearDialog.entries = entries
  clearDialog.open = true
}

async function confirmClear() {
  const namespace = clearDialog.namespace
  if (!namespace) {
    clearDialog.open = false
    return
  }
  state.clearing[namespace] = true
  state.error = ""
  state.message = ""
  try {
    const result = await api.clearCacheNamespace(namespace)
    state.message = result.message || `Cleared ${namespace}.`
    clearDialog.open = false
    // Re-fetch so the UI shows the post-clear counts and stats.
    await loadSnapshot()
  } catch (err) {
    // Error returned by the API gets shown in the dialog so the
    // operator sees it without losing context.
    const detail = err?.body?.detail
    state.error = detail?.error || err?.message || "Failed to clear namespace."
  } finally {
    state.clearing[namespace] = false
  }
}

onMounted(loadSnapshot)
</script>

<template>
  <div class="space-y-6 p-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-2xl font-semibold tracking-tight">Runtime Cache</h1>
        <p class="text-sm text-muted-foreground">
          L1 in-process LRU + L2 Redis for LLM, embedding, and short response reuse.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          :disabled="state.refreshing"
          @click="loadSnapshot"
        >
          <Loader2 v-if="state.refreshing" class="h-4 w-4 mr-2 animate-spin" />
          <RefreshCw v-else class="h-4 w-4 mr-2" />
          Refresh
        </Button>
        <Button
          variant="ghost"
          size="sm"
          @click="router.push('/settings')"
        >
          Back to Settings
        </Button>
      </div>
    </div>

    <Alert v-if="state.error" variant="destructive">
      <AlertCircle class="h-4 w-4" />
      <AlertDescription>{{ state.error }}</AlertDescription>
    </Alert>
    <Alert v-if="state.message" variant="default">
      <CheckCircle2 class="h-4 w-4 text-green-600" />
      <AlertDescription>{{ state.message }}</AlertDescription>
    </Alert>

    <!-- Initial load skeleton -->
    <div
      v-if="state.loading"
      class="text-sm text-muted-foreground"
    >
      Loading cache snapshot...
    </div>

    <template v-else-if="state.snapshot">
      <!-- Redis health -->
      <Card>
        <CardHeader>
          <CardTitle class="flex items-center gap-2 text-base">
            <Database class="h-4 w-4" />
            Redis
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div class="flex flex-wrap items-center gap-3">
            <Badge :variant="state.snapshot.redis.ok ? 'success' : 'destructive'">
              {{ state.snapshot.redis.ok ? "PONG" : "Unreachable" }}
            </Badge>
            <span class="text-sm text-muted-foreground font-mono">
              {{ state.snapshot.redis.url }}
            </span>
            <span
              v-if="state.snapshot.redis.latency_ms !== null"
              class="text-sm text-muted-foreground tabular-nums"
            >
              {{ state.snapshot.redis.latency_ms }} ms
            </span>
            <Badge variant="secondary" class="ml-auto">
              cache_version: {{ state.snapshot.cache_version }}
            </Badge>
          </div>
          <p
            v-if="!state.snapshot.redis.ok"
            class="text-sm text-muted-foreground mt-2"
          >
            {{ state.snapshot.redis.detail }}
          </p>
          <p
            v-if="!state.snapshot.l2_available"
            class="text-sm text-muted-foreground mt-2"
          >
            L2 unavailable - running L1-only. The orchestrator retries the L2
            attachment every 30 s.
          </p>
        </CardContent>
      </Card>

      <!-- Hit/miss/$-saved -->
      <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
        <Card>
          <CardHeader class="pb-2">
            <CardTitle class="text-sm text-muted-foreground">L1 hits</CardTitle>
          </CardHeader>
          <CardContent class="pt-0">
            <div class="text-2xl font-semibold tabular-nums">
              {{ state.snapshot.stats.hits_l1.toLocaleString() }}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader class="pb-2">
            <CardTitle class="text-sm text-muted-foreground">L2 hits</CardTitle>
          </CardHeader>
          <CardContent class="pt-0">
            <div class="text-2xl font-semibold tabular-nums">
              {{ state.snapshot.stats.hits_l2.toLocaleString() }}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader class="pb-2">
            <CardTitle class="text-sm text-muted-foreground">Misses</CardTitle>
          </CardHeader>
          <CardContent class="pt-0">
            <div class="text-2xl font-semibold tabular-nums">
              {{ state.snapshot.stats.misses.toLocaleString() }}
            </div>
            <p
              v-if="hitRate !== null"
              class="text-xs text-muted-foreground"
            >
              {{ (hitRate * 100).toFixed(1) }}% hit rate over
              {{ totalRequests.toLocaleString() }} calls
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader class="pb-2">
            <CardTitle class="text-sm text-muted-foreground">Saved</CardTitle>
          </CardHeader>
          <CardContent class="pt-0">
            <div class="text-2xl font-semibold tabular-nums">
              {{ formatDollars(state.snapshot.estimated_dollars_saved) }}
            </div>
            <p class="text-xs text-muted-foreground">
              estimate (Phase 12.7 refines per-provider)
            </p>
          </CardContent>
        </Card>
      </div>

      <!-- Per-namespace cards -->
      <div>
        <h2 class="text-lg font-medium mb-2">Namespaces</h2>
        <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
          <Card
            v-for="ns in state.snapshot.namespaces"
            :key="ns.name"
          >
            <CardHeader class="pb-2 flex flex-row items-center justify-between space-y-0">
              <CardTitle class="text-sm font-mono">{{ ns.name }}</CardTitle>
              <Badge variant="outline" class="tabular-nums text-xs">
                TTL {{ formatTtl(ns.ttl_seconds) }}
              </Badge>
            </CardHeader>
            <CardContent>
              <div class="flex items-baseline gap-2">
                <span class="text-2xl font-semibold tabular-nums">
                  {{ formatEntries(ns.entries) }}
                </span>
                <span class="text-xs text-muted-foreground">entries</span>
              </div>
              <p class="text-xs text-muted-foreground font-mono mt-1">
                prefix {{ ns.prefix }}
              </p>
              <!-- The clear endpoint always invalidates BOTH L1 and L2.
                   Disabling the button just because Redis reports 0
                   would block the operator from clearing stale L1
                   entries (those can outlive a Redis flush done
                   outside the app, or be promoted from an earlier
                   L2 hit before L2 was cleared). Only the in-flight
                   state disables the button. -->
              <Button
                variant="outline"
                size="sm"
                class="mt-3"
                :disabled="state.clearing[ns.name]"
                @click="openClearDialog(ns.name, ns.entries)"
              >
                <Trash2 class="h-3.5 w-3.5 mr-2" />
                Clear
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </template>

    <!-- Confirm clear dialog -->
    <Dialog v-model:open="clearDialog.open">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Clear cache namespace?</DialogTitle>
          <DialogDescription>
            This drops every entry in
            <span class="font-mono">{{ clearDialog.namespace }}</span>
            <template v-if="clearDialog.entries !== null && clearDialog.entries >= 0">
              ({{ formatEntries(clearDialog.entries) }} entries).
            </template>
            Future calls in this namespace will hit the underlying provider
            until the cache repopulates.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            :disabled="state.clearing[clearDialog.namespace]"
            @click="clearDialog.open = false"
          >
            Cancel
          </Button>
          <Button
            variant="destructive"
            :disabled="state.clearing[clearDialog.namespace]"
            @click="confirmClear"
          >
            <Loader2
              v-if="state.clearing[clearDialog.namespace]"
              class="h-4 w-4 mr-2 animate-spin"
            />
            Clear {{ clearDialog.namespace }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
