<script setup>
import { computed, onMounted, reactive } from "vue"
import { useRouter } from "vue-router"
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Building2,
  CheckCircle2,
  ChevronRight,
  DollarSign,
  Inbox,
  Percent,
  RefreshCw,
  Send,
  Target,
  TrendingUp,
} from "lucide-vue-next"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { EmptyState } from "@/components/ui/empty-state"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { formatPercent } from "@/lib/format"

const MAX_CONNECTION_ATTEMPTS = 3
const CONNECTION_RETRY_DELAY_MS = 350

const state = reactive({
  loading: true,
  error: "",
  data: {
    pipeline: {},
    summary: {
      total_discovered: 0,
      total_applied: 0,
      total_failed: 0,
      total_review: 0,
      avg_match_score: 0,
      avg_fields_filled_pct: 0,
    },
    outcomes: {
      total: 0,
      pending: 0,
      rates: {
        response_rate: 0,
        positive_rate: 0,
      },
    },
    companies: [],
    db_connected: false,
  },
  // Phase 17.6: morning digest banner. Loaded lazily after the
  // dashboard payload arrives so a slow /api/digest call doesn't
  // block the primary numbers.
  digest: null,
  digestError: "",
})

const cost = reactive({
  loading: true,
  error: "",
  bucket: "day", // "day" | "week"
  trend: { buckets: [], totals: { cost_usd: 0, cost_usd_saved: 0, trace_count: 0 } },
  detailsOpen: false,
  detailsLoading: false,
  detailsError: "",
  traces: [],
})

const COST_PERIODS = { day: 14, week: 12 }

const costBars = computed(() => {
  const buckets = cost.trend.buckets || []
  const max = Math.max(0.000001, ...buckets.map((b) => b.cost_usd || 0))
  return buckets.map((b) => ({
    key: b.key,
    cost: b.cost_usd || 0,
    saved: b.cost_usd_saved || 0,
    count: b.trace_count || 0,
    heightPct: ((b.cost_usd || 0) / max) * 100,
  }))
})

function formatUsd(v) {
  const n = Number(v || 0)
  if (n === 0) return "$0"
  if (n < 0.01) return `$${n.toFixed(4)}`
  if (n < 1) return `$${n.toFixed(3)}`
  return `$${n.toFixed(2)}`
}

function formatBucketLabel(key) {
  if (cost.bucket === "day") {
    // "2026-05-16" -> "05/16"
    const [, m, d] = key.split("-")
    return `${m}/${d}`
  }
  // "2026-W20" -> "W20"
  const idx = key.indexOf("-W")
  return idx >= 0 ? key.slice(idx + 1) : key
}

function formatTimestamp(iso) {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

async function loadCostTrend() {
  cost.loading = true
  cost.error = ""
  try {
    cost.trend = await api.costTrend(cost.bucket, COST_PERIODS[cost.bucket])
  } catch (err) {
    cost.error = err?.message || "Could not load cost trend."
  } finally {
    cost.loading = false
  }
}

async function setCostBucket(bucket) {
  if (cost.bucket === bucket) return
  cost.bucket = bucket
  await loadCostTrend()
}

async function openCostDetails() {
  cost.detailsOpen = true
  cost.detailsLoading = true
  cost.detailsError = ""
  try {
    const payload = await api.recentTraces(50)
    cost.traces = payload?.traces || []
  } catch (err) {
    cost.detailsError = err?.message || "Could not load recent traces."
    cost.traces = []
  } finally {
    cost.detailsLoading = false
  }
}

const cards = computed(() => [
  { label: "Tracked", value: state.data.summary.total_discovered, icon: Inbox },
  { label: "Submitted", value: state.data.summary.total_applied, icon: Send },
  { label: "Pending", value: state.data.outcomes.pending, icon: Activity },
  {
    label: "Response",
    value: formatPercent(state.data.outcomes.rates.response_rate, "N/A"),
    icon: TrendingUp,
  },
])

const signals = computed(() => [
  {
    label: "Positive rate",
    value: formatPercent(state.data.outcomes.rates.positive_rate, "N/A"),
    icon: CheckCircle2,
  },
  {
    label: "Avg match",
    value: formatPercent(state.data.summary.avg_match_score, "0%"),
    icon: Target,
  },
  {
    label: "Form fill",
    value: formatPercent(state.data.summary.avg_fields_filled_pct, "0%"),
    icon: Percent,
  },
])

async function load() {
  state.loading = true
  state.error = ""

  let latestResponse = null
  let latestException = null

  for (let attempt = 1; attempt <= MAX_CONNECTION_ATTEMPTS; attempt += 1) {
    try {
      const response = await api.dashboard()
      latestResponse = response
      latestException = null
      if (response.db_connected) {
        break
      }
    } catch (error) {
      latestResponse = null
      latestException = error
    }

    if (attempt < MAX_CONNECTION_ATTEMPTS) {
      await delay(CONNECTION_RETRY_DELAY_MS)
    }
  }

  try {
    if (latestResponse) {
      state.data = latestResponse
    }

    if (!latestResponse && latestException) {
      state.error = latestException.message
    }
  } finally {
    state.loading = false
  }

  // Phase 17.6: load the digest banner. Independent of the main
  // dashboard request -- a digest error doesn't blank out the cards.
  try {
    const digestResponse = await api.morningDigest()
    state.digest = digestResponse?.digest || null
    state.digestError = ""
  } catch (err) {
    state.digest = null
    state.digestError = err?.message || "Could not load digest."
  }
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

const router = useRouter()

const PIPELINE_LABELS = {
  DISCOVERED: "Discovered",
  QUALIFIED: "Qualified",
  MATERIALS_READY: "Materials ready",
  FORM_OPENED: "Form opened",
  FIELDS_MAPPED: "Fields mapped",
  FILES_UPLOADED: "Files uploaded",
  QUESTIONS_ANSWERED: "Questions answered",
  REVIEW_REQUIRED: "Awaiting your review",
  SUBMITTED: "Submitted",
  FAILED: "Failed",
  NEEDS_RETRY: "Needs retry",
}

function prettify(status) {
  return PIPELINE_LABELS[status] || status.replaceAll("_", " ")
}

function pipelineDestination(status) {
  if (status === "REVIEW_REQUIRED") {
    return { path: "/review" }
  }
  if (status === "SUBMITTED" || status === "FAILED") {
    return { path: "/applications", query: { status } }
  }
  return { path: "/applications" }
}

function goToPipeline(status) {
  router.push(pipelineDestination(status))
}

onMounted(() => {
  load()
  loadCostTrend()
})
</script>

<template>
  <div class="space-y-6">
    <!-- Phase 17.6: morning digest banner. -->
    <Alert v-if="state.digest" class="border-primary/40 bg-primary/5">
      <Activity class="h-4 w-4" />
      <AlertDescription>
        <div class="flex flex-wrap items-center justify-between gap-2">
          <span class="text-sm font-medium">{{ state.digest.headline }}</span>
          <div class="flex flex-wrap items-center gap-1 text-xs">
            <Badge variant="secondary">
              Pending {{ state.digest.review_queue_status?.pending || 0 }}
            </Badge>
            <Badge variant="secondary">
              Approved {{ state.digest.review_queue_status?.approved || 0 }}
            </Badge>
            <Badge variant="secondary">
              Stale {{ state.digest.review_queue_status?.stale || 0 }}
            </Badge>
            <Badge v-if="state.digest.errors" variant="destructive">
              {{ state.digest.errors }} run errors
            </Badge>
          </div>
        </div>
      </AlertDescription>
    </Alert>

    <section class="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Card v-for="card in cards" :key="card.label" class="overflow-hidden">
        <CardContent class="flex items-start justify-between gap-3 p-5">
          <div class="space-y-1.5">
            <p class="text-xs font-medium text-muted-foreground">{{ card.label }}</p>
            <p class="text-2xl font-bold tabular-nums tracking-tight text-foreground">
              <Skeleton v-if="state.loading" class="h-7 w-16" />
              <template v-else>{{ card.value }}</template>
            </p>
          </div>
          <div class="rounded-md bg-primary/10 p-2 text-primary">
            <component :is="card.icon" class="h-4 w-4" />
          </div>
        </CardContent>
      </Card>
    </section>

    <Alert v-if="state.error" variant="destructive">
      <AlertCircle class="h-4 w-4" />
      <AlertDescription>{{ state.error }}</AlertDescription>
    </Alert>
    <Alert
      v-else-if="!state.loading && !state.data.db_connected"
      variant="warning"
    >
      <AlertTriangle class="h-4 w-4" />
      <AlertDescription>Database not connected.</AlertDescription>
    </Alert>

    <Card
      role="button"
      tabindex="0"
      class="cursor-pointer transition-colors hover:bg-muted/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      @click="openCostDetails"
      @keydown.enter.prevent="openCostDetails"
      @keydown.space.prevent="openCostDetails"
    >
      <CardHeader class="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle class="flex items-center gap-2 text-sm">
          <DollarSign class="h-4 w-4 text-muted-foreground" />
          LLM cost trend
        </CardTitle>
        <div class="flex items-center gap-1" @click.stop>
          <Button
            variant="ghost"
            size="sm"
            class="h-7 px-2 text-xs"
            :class="cost.bucket === 'day' ? 'bg-muted text-foreground' : 'text-muted-foreground'"
            @click="setCostBucket('day')"
          >
            Day
          </Button>
          <Button
            variant="ghost"
            size="sm"
            class="h-7 px-2 text-xs"
            :class="cost.bucket === 'week' ? 'bg-muted text-foreground' : 'text-muted-foreground'"
            @click="setCostBucket('week')"
          >
            Week
          </Button>
        </div>
      </CardHeader>
      <CardContent class="space-y-3">
        <div class="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <div class="text-2xl font-bold tabular-nums tracking-tight">
            <Skeleton v-if="cost.loading" class="h-7 w-24" />
            <template v-else>{{ formatUsd(cost.trend.totals?.cost_usd) }}</template>
          </div>
          <span class="text-xs text-muted-foreground">
            spent across {{ cost.trend.totals?.trace_count || 0 }} traces
            <span v-if="Number(cost.trend.totals?.cost_usd_saved || 0) > 0" class="text-emerald-600 dark:text-emerald-400">
              · saved {{ formatUsd(cost.trend.totals?.cost_usd_saved) }} via cache
            </span>
          </span>
        </div>

        <Alert v-if="cost.error" variant="destructive" class="py-2">
          <AlertCircle class="h-4 w-4" />
          <AlertDescription>{{ cost.error }}</AlertDescription>
        </Alert>

        <div v-else-if="cost.loading" class="flex h-20 items-end gap-1">
          <Skeleton
            v-for="n in COST_PERIODS[cost.bucket]"
            :key="n"
            class="h-full flex-1"
            :style="{ height: `${30 + ((n * 13) % 60)}%` }"
          />
        </div>

        <div v-else-if="!costBars.length || cost.trend.totals?.cost_usd === 0" class="flex h-20 items-center justify-center text-xs text-muted-foreground">
          No spend recorded in this window yet.
        </div>

        <div v-else class="flex h-20 items-end gap-1">
          <div
            v-for="bar in costBars"
            :key="bar.key"
            class="group relative flex flex-1 flex-col items-center justify-end"
            :title="`${bar.key} · ${formatUsd(bar.cost)} · ${bar.count} traces`"
          >
            <div
              class="w-full rounded-sm bg-primary/60 transition-colors group-hover:bg-primary"
              :style="{ height: `${Math.max(bar.heightPct, bar.cost > 0 ? 4 : 0)}%` }"
            ></div>
            <span class="mt-1 truncate text-[10px] tabular-nums text-muted-foreground">
              {{ formatBucketLabel(bar.key) }}
            </span>
          </div>
        </div>

        <p class="text-[11px] text-muted-foreground">Click for per-run breakdown.</p>
      </CardContent>
    </Card>

    <Dialog v-model:open="cost.detailsOpen">
      <DialogContent class="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Recent agent runs</DialogTitle>
          <DialogDescription>
            Last 50 agent traces sorted newest first. Cost is a best-effort
            estimate from the provider's token accounting.
          </DialogDescription>
        </DialogHeader>

        <div v-if="cost.detailsLoading" class="space-y-2">
          <Skeleton v-for="n in 5" :key="n" class="h-12 w-full" />
        </div>

        <Alert v-else-if="cost.detailsError" variant="destructive">
          <AlertCircle class="h-4 w-4" />
          <AlertDescription>{{ cost.detailsError }}</AlertDescription>
        </Alert>

        <div v-else-if="!cost.traces.length" class="py-6 text-center text-sm text-muted-foreground">
          No agent traces recorded yet.
        </div>

        <div v-else class="max-h-[60vh] space-y-1 overflow-y-auto pr-1">
          <div
            v-for="trace in cost.traces"
            :key="trace.id"
            class="rounded-md border border-border bg-card px-3 py-2 text-sm"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0 flex-1">
                <div class="truncate font-medium">{{ trace.goal || "(no goal)" }}</div>
                <div class="text-xs text-muted-foreground">
                  {{ formatTimestamp(trace.started_at) }} ·
                  {{ trace.step_count }} steps
                  <span v-if="Number(trace.cached_step_count || 0) > 0">
                    ({{ trace.fresh_step_count }} fresh / {{ trace.cached_step_count }} cached)
                  </span>
                </div>
              </div>
              <div class="flex flex-col items-end gap-1 text-xs tabular-nums">
                <span class="font-medium">{{ formatUsd(trace.total_cost_usd) }}</span>
                <span v-if="Number(trace.total_cost_saved_usd || 0) > 0" class="text-emerald-600 dark:text-emerald-400">
                  saved {{ formatUsd(trace.total_cost_saved_usd) }}
                </span>
              </div>
            </div>
            <div class="mt-1 flex flex-wrap gap-2 text-[11px] text-muted-foreground">
              <Badge variant="secondary" class="px-1.5 py-0">
                {{ trace.total_prompt_tokens || 0 }}+{{ trace.total_output_tokens || 0 }} tok
              </Badge>
              <Badge :variant="trace.finished ? 'secondary' : 'destructive'" class="px-1.5 py-0">
                {{ trace.finished ? "finished" : (trace.stop_reason || "failed") }}
              </Badge>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>

    <section class="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)]">
      <Card>
        <CardHeader class="flex flex-row items-center justify-between space-y-0">
          <CardTitle class="flex items-center gap-2 text-sm">
            <Activity class="h-4 w-4 text-muted-foreground" />
            Pipeline
          </CardTitle>
          <Button
            variant="ghost"
            size="icon"
            :disabled="state.loading"
            aria-label="Refresh dashboard"
            @click="load"
          >
            <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': state.loading }" />
          </Button>
        </CardHeader>
        <CardContent>
          <div v-if="state.loading" class="space-y-2">
            <Skeleton v-for="n in 4" :key="n" class="h-9 w-full" />
          </div>
          <div
            v-else-if="Object.keys(state.data.pipeline).length"
            class="space-y-2"
          >
            <button
              v-for="(count, status) in state.data.pipeline"
              :key="status"
              type="button"
              class="group flex w-full items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-left text-sm transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              @click="goToPipeline(status)"
            >
              <span class="flex items-center gap-2">
                {{ prettify(status) }}
                <span
                  v-if="status === 'REVIEW_REQUIRED' && count > 0"
                  class="text-xs text-primary"
                >· needs you</span>
              </span>
              <span class="flex items-center gap-1">
                <Badge variant="secondary" class="tabular-nums">{{ count }}</Badge>
                <ChevronRight class="h-3.5 w-3.5 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </span>
            </button>
          </div>
          <EmptyState v-else title="No pipeline data" description="Run a search to start tracking jobs.">
            <template #icon><Inbox /></template>
          </EmptyState>
        </CardContent>
      </Card>

      <div class="space-y-4">
        <Card>
          <CardHeader class="flex flex-row items-center justify-between space-y-0">
            <CardTitle class="flex items-center gap-2 text-sm">
              <Building2 class="h-4 w-4 text-muted-foreground" />
              Top companies
            </CardTitle>
            <span class="text-xs tabular-nums text-muted-foreground">
              {{ state.data.companies.length }}
            </span>
          </CardHeader>
          <CardContent>
            <div v-if="state.loading" class="space-y-2">
              <Skeleton v-for="n in 4" :key="n" class="h-11 w-full" />
            </div>
            <div v-else-if="state.data.companies.length" class="space-y-2">
              <div
                v-for="company in state.data.companies.slice(0, 6)"
                :key="company.company"
                class="flex items-center justify-between gap-3 rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50"
              >
                <div class="min-w-0 flex-1">
                  <div class="truncate font-medium text-foreground">{{ company.company }}</div>
                  <div class="text-xs tabular-nums text-muted-foreground">
                    {{ company.applications }} applied · {{ company.submitted }} submitted
                  </div>
                </div>
                <Badge variant="secondary" class="tabular-nums">
                  {{ formatPercent(company.avg_match_score, "0%") }}
                </Badge>
              </div>
            </div>
            <EmptyState
              v-else
              title="No company breakdown yet"
              description="Apply to a few jobs to see top companies here."
            >
              <template #icon><Building2 /></template>
            </EmptyState>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle class="flex items-center gap-2 text-sm">
              <TrendingUp class="h-4 w-4 text-muted-foreground" />
              Signals
            </CardTitle>
          </CardHeader>
          <CardContent class="grid gap-2">
            <div
              v-for="signal in signals"
              :key="signal.label"
              class="flex items-center justify-between gap-3 rounded-md border border-border bg-card px-3 py-2 text-sm transition-colors hover:bg-muted/50"
            >
              <span class="flex items-center gap-2 text-foreground">
                <component :is="signal.icon" class="h-4 w-4 text-muted-foreground" />
                {{ signal.label }}
              </span>
              <Badge variant="secondary" class="tabular-nums">{{ signal.value }}</Badge>
            </div>
          </CardContent>
        </Card>
      </div>
    </section>
  </div>
</template>
