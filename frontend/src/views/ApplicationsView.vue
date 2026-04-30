<script setup>
import { computed, onMounted, reactive } from "vue"
import {
  Activity,
  Building2,
  CheckCircle2,
  Filter,
  Inbox,
  Send,
  TrendingUp,
} from "lucide-vue-next"

import AppSelect from "@/components/AppSelect.vue"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { formatDate, formatPercent } from "@/lib/format"

const statusOptions = [
  { value: "", label: "All" },
  { value: "SUBMITTED", label: "Submitted" },
  { value: "FAILED", label: "Failed" },
  { value: "REVIEW_REQUIRED", label: "Review Required" },
]

const outcomeOptions = [
  { value: "", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "rejected", label: "Rejected" },
  { value: "oa", label: "OA" },
  { value: "interview", label: "Interview" },
  { value: "offer", label: "Offer" },
]

const outcomeEditOptions = outcomeOptions.filter((option) => option.value !== "")

const filters = reactive({
  status: "",
  outcome: "",
  company: "",
  limit: 50,
})

const state = reactive({
  loading: true,
  error: "",
  updatingId: "",
  data: {
    applications: [],
    pipeline: {},
    outcomes: {
      total: 0,
      pending: 0,
      rates: { response_rate: 0, positive_rate: 0 },
    },
  },
})

const cards = computed(() => [
  { label: "Submitted", value: state.data.outcomes.total, icon: Send },
  { label: "Pending", value: state.data.outcomes.pending, icon: Activity },
  {
    label: "Response",
    value: formatPercent(state.data.outcomes.rates.response_rate, "N/A"),
    icon: TrendingUp,
  },
  {
    label: "Positive",
    value: formatPercent(state.data.outcomes.rates.positive_rate, "N/A"),
    icon: CheckCircle2,
  },
])

async function load() {
  state.loading = true
  state.error = ""

  try {
    const response = await api.applications({ ...filters })
    state.data = response
    state.error = response.error || ""
  } catch (error) {
    state.error = error.message
  } finally {
    state.loading = false
  }
}

async function updateOutcome(application, outcome) {
  state.updatingId = application.id

  try {
    await api.updateOutcome(application.id, outcome)
    await load()
  } catch (error) {
    state.error = error.message
  } finally {
    state.updatingId = ""
  }
}

function prettify(status) {
  return status.replaceAll("_", " ")
}

onMounted(load)
</script>

<template>
  <div class="space-y-6">
    <Card>
      <CardContent class="p-5">
        <form class="grid grid-cols-1 gap-4 md:grid-cols-[1fr_1fr_1fr_auto]" @submit.prevent="load">
          <label class="space-y-1.5">
            <span class="text-xs font-medium text-muted-foreground">Status</span>
            <AppSelect v-model="filters.status" :options="statusOptions" aria-label="Status filter" />
          </label>

          <label class="space-y-1.5">
            <span class="text-xs font-medium text-muted-foreground">Outcome</span>
            <AppSelect v-model="filters.outcome" :options="outcomeOptions" aria-label="Outcome filter" />
          </label>

          <label class="space-y-1.5">
            <span class="text-xs font-medium text-muted-foreground">Company</span>
            <Input v-model="filters.company" type="text" placeholder="Stripe, Shopify, ..." />
          </label>

          <div class="flex items-end">
            <Button type="submit" :disabled="state.loading" class="w-full md:w-auto">
              <Filter class="h-4 w-4" />
              Apply
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>

    <section class="grid grid-cols-2 gap-4 md:grid-cols-4">
      <Card v-for="card in cards" :key="card.label">
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

    <section class="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.4fr)]">
      <Card>
        <CardHeader>
          <CardTitle class="flex items-center gap-2 text-sm">
            <Activity class="h-4 w-4 text-muted-foreground" />
            Pipeline
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div v-if="state.loading" class="space-y-2">
            <Skeleton v-for="n in 4" :key="n" class="h-9 w-full" />
          </div>
          <div
            v-else-if="Object.keys(state.data.pipeline || {}).length"
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
          <EmptyState v-else title="No pipeline data">
            <template #icon><Inbox /></template>
          </EmptyState>
        </CardContent>
      </Card>

      <Card>
        <CardHeader class="flex flex-row items-center justify-between space-y-0">
          <CardTitle class="flex items-center gap-2 text-sm">
            <Building2 class="h-4 w-4 text-muted-foreground" />
            Application queue
          </CardTitle>
          <span class="text-xs tabular-nums text-muted-foreground">
            {{ state.data.applications.length }}
          </span>
        </CardHeader>
        <CardContent class="p-0">
          <div v-if="state.loading" class="space-y-2 p-6 pt-0">
            <Skeleton v-for="n in 5" :key="n" class="h-12 w-full" />
          </div>
          <div v-else-if="state.data.applications.length" class="overflow-x-auto">
            <table class="table">
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Score</th>
                  <th>Outcome</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="application in state.data.applications" :key="application.id">
                  <td>
                    <div class="font-medium text-foreground">{{ application.job.company }}</div>
                    <div class="text-xs text-muted-foreground">{{ application.job.title }}</div>
                  </td>
                  <td>
                    <Badge :variant="application.status === 'FAILED' ? 'destructive' : application.status === 'SUBMITTED' ? 'success' : 'secondary'">
                      {{ prettify(application.status) }}
                    </Badge>
                  </td>
                  <td class="tabular-nums">
                    {{ application.match_score === null ? "-" : formatPercent(application.match_score, "0%") }}
                  </td>
                  <td>
                    <AppSelect
                      :model-value="application.outcome"
                      :options="outcomeEditOptions"
                      compact
                      :disabled="state.updatingId === application.id"
                      aria-label="Update outcome"
                      @update:model-value="updateOutcome(application, $event)"
                    />
                  </td>
                  <td class="tabular-nums text-muted-foreground">{{ formatDate(application.created_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="p-6 pt-0">
            <EmptyState title="No applications yet" description="Submit an application from the Jobs view and it will appear here.">
              <template #icon><Send /></template>
            </EmptyState>
          </div>
        </CardContent>
      </Card>
    </section>
  </div>
</template>
