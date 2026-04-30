<script setup>
import { computed, onMounted, reactive } from "vue"
import {
  Activity,
  Building2,
  CheckCircle2,
  Inbox,
  Percent,
  RefreshCw,
  Send,
  Target,
  TrendingUp,
} from "lucide-vue-next"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
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
})

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
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function prettify(status) {
  return status.replaceAll("_", " ")
}

onMounted(load)
</script>

<template>
  <div class="space-y-6">
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

    <div v-if="state.error" class="banner is-danger">{{ state.error }}</div>
    <div
      v-else-if="!state.loading && !state.data.db_connected"
      class="banner is-warning"
    >
      Database not connected.
    </div>

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
            <div
              v-for="(count, status) in state.data.pipeline"
              :key="status"
              class="flex items-center justify-between rounded-md border border-border bg-card px-3 py-2 text-sm capitalize transition-colors hover:bg-muted/50"
            >
              <span>{{ prettify(status) }}</span>
              <Badge variant="secondary" class="tabular-nums">{{ count }}</Badge>
            </div>
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
