<script setup>
import { computed, onMounted, reactive } from "vue"
import { RouterLink, useRoute } from "vue-router"
import {
  Activity,
  AlertCircle,
  ArrowRight,
  BookMarked,
  CheckCircle2,
  ClipboardCheck,
  Filter,
  Send,
  TrendingUp,
} from "lucide-vue-next"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

import AppSelect from "@/components/AppSelect.vue"
import { Alert, AlertDescription } from "@/components/ui/alert"
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
]

const STATUS_LABEL = {
  SUBMITTED: "Submitted",
  FAILED: "Failed",
}

const outcomeOptions = [
  { value: "", label: "All outcomes" },
  { value: "pending", label: "No reply yet" },
  { value: "rejected", label: "Rejected" },
  { value: "oa", label: "Online assessment" },
  { value: "interview", label: "Interview" },
  { value: "offer", label: "Offer" },
]

const outcomeEditOptions = [
  { value: "pending", label: "No reply yet" },
  { value: "rejected", label: "Rejected" },
  { value: "oa", label: "Online assessment" },
  { value: "interview", label: "Interview" },
  { value: "offer", label: "Offer" },
]

const route = useRoute()

const filters = reactive({
  status: "",
  outcome: "",
  company: "",
  limit: 50,
})

const highlightedApplicationId = computed(() =>
  typeof route.query.application === "string" ? route.query.application : "",
)

const state = reactive({
  loading: true,
  error: "",
  updatingId: "",
  message: "",
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

const visibleApplications = computed(() =>
  state.data.applications.filter((app) => app.status !== "REVIEW_REQUIRED"),
)

const awaitingReviewCount = computed(
  () => state.data.pipeline?.REVIEW_REQUIRED || 0,
)

const cards = computed(() => [
  { label: "Total submitted", value: state.data.outcomes.total, icon: Send },
  { label: "No reply yet", value: state.data.outcomes.pending, icon: Activity },
  {
    label: "Response rate",
    value: formatPercent(state.data.outcomes.rates.response_rate, "—"),
    icon: TrendingUp,
  },
  {
    label: "Positive rate",
    value: formatPercent(state.data.outcomes.rates.positive_rate, "—"),
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

function statusLabel(status) {
  return STATUS_LABEL[status] || status
}

function statusVariant(status) {
  if (status === "FAILED") return "destructive"
  if (status === "SUBMITTED") return "success"
  return "secondary"
}

function artifactUrl(path) {
  return api.artifactDownloadUrl(path)
}

function artifactList(application) {
  const items = []
  if (application.resume_version) {
    items.push({ label: "Resume", path: application.resume_version, kind: "resume" })
  }
  if (application.cover_letter_version) {
    items.push({
      label: "Cover Letter",
      path: application.cover_letter_version,
      kind: "cover_letter",
    })
  }
  const shots = application.screenshot_paths || []
  shots.forEach((path, index) => {
    items.push({ label: `Screenshot ${index + 1}`, path, kind: null })
  })
  return items
}

const promoteDialog = reactive({
  open: false,
  application: null,
  artifactPath: "",
  documentType: "resume",
  displayName: "",
  submitting: false,
})

function openPromoteDialog(application, item) {
  if (!item.kind) return
  promoteDialog.application = application
  promoteDialog.artifactPath = item.path
  promoteDialog.documentType = item.kind
  promoteDialog.displayName = `${application.job.company} – ${item.kind === "resume" ? "Resume" : "Cover Letter"}`
  promoteDialog.submitting = false
  promoteDialog.open = true
}

function closePromoteDialog() {
  promoteDialog.open = false
  promoteDialog.application = null
}

async function confirmPromote() {
  if (!promoteDialog.application || !promoteDialog.artifactPath) return
  promoteDialog.submitting = true
  state.error = ""
  state.message = ""
  try {
    const result = await api.promoteArtifactToLibrary({
      artifactPath: promoteDialog.artifactPath,
      documentType: promoteDialog.documentType,
      displayName: promoteDialog.displayName.trim() || "Untitled",
      applicationId: promoteDialog.application.id,
    })
    state.message =
      result.status === "exists"
        ? "That file is already in your library."
        : "Saved to your library."
    closePromoteDialog()
  } catch (err) {
    state.error = err?.message || "Couldn't save to library."
  } finally {
    promoteDialog.submitting = false
  }
}

onMounted(load)
</script>

<template>
  <div class="space-y-6">
    <Alert
      v-if="awaitingReviewCount > 0"
      class="border-primary/40 bg-primary/5"
    >
      <ClipboardCheck class="h-4 w-4" />
      <AlertDescription>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <span class="text-sm">
            <strong>{{ awaitingReviewCount }}</strong>
            {{ awaitingReviewCount === 1 ? "application is" : "applications are" }}
            waiting for you to confirm before submission.
          </span>
          <RouterLink to="/review">
            <Button size="sm" variant="outline">
              Go to Awaiting Review
              <ArrowRight class="h-4 w-4" />
            </Button>
          </RouterLink>
        </div>
      </AlertDescription>
    </Alert>

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

    <Alert v-if="state.error" variant="destructive">
      <AlertCircle class="h-4 w-4" />
      <AlertDescription>{{ state.error }}</AlertDescription>
    </Alert>
    <Alert v-if="state.message" class="border-primary/40 bg-primary/5">
      <CheckCircle2 class="h-4 w-4" />
      <AlertDescription>{{ state.message }}</AlertDescription>
    </Alert>

    <Card>
      <CardHeader>
        <CardTitle class="text-sm">Filter submitted applications</CardTitle>
      </CardHeader>
      <CardContent>
        <form class="grid grid-cols-1 gap-4 md:grid-cols-[1fr_1fr_1fr_auto]" @submit.prevent="load">
          <label class="space-y-1.5">
            <span class="text-xs font-medium text-muted-foreground">Result</span>
            <AppSelect v-model="filters.status" :options="statusOptions" aria-label="Submission result filter" />
          </label>

          <label class="space-y-1.5">
            <span class="text-xs font-medium text-muted-foreground">Outcome</span>
            <AppSelect v-model="filters.outcome" :options="outcomeOptions" aria-label="Outcome filter" />
          </label>

          <label class="space-y-1.5">
            <span class="text-xs font-medium text-muted-foreground">Company</span>
            <Input v-model="filters.company" type="text" placeholder="Stripe, Shopify…" />
          </label>

          <div class="flex items-end">
            <Button type="submit" :disabled="state.loading" class="w-full md:w-auto">
              <Filter class="h-4 w-4" />
              Apply filter
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>

    <Card>
      <CardContent class="p-0">
        <div v-if="state.loading" class="space-y-2 p-6">
          <Skeleton v-for="n in 5" :key="n" class="h-12 w-full" />
        </div>
        <div v-else-if="visibleApplications.length" class="overflow-x-auto">
          <table class="table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Submitted</th>
                <th>Result</th>
                <th>Match</th>
                <th>Outcome</th>
                <th>Materials</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="application in visibleApplications"
                :key="application.id"
                :class="{ 'bg-primary/5': application.id === highlightedApplicationId }"
              >
                <td>
                  <div class="font-medium text-foreground">{{ application.job.company }}</div>
                  <div class="text-xs text-muted-foreground">{{ application.job.title }}</div>
                </td>
                <td class="whitespace-nowrap text-sm text-muted-foreground tabular-nums">
                  {{ formatDate(application.created_at) }}
                </td>
                <td>
                  <Badge :variant="statusVariant(application.status)">
                    {{ statusLabel(application.status) }}
                  </Badge>
                </td>
                <td class="tabular-nums">
                  {{ application.match_score === null ? "—" : formatPercent(application.match_score, "0%") }}
                </td>
                <td>
                  <AppSelect
                    v-if="application.status === 'SUBMITTED'"
                    :model-value="application.outcome || 'pending'"
                    :options="outcomeEditOptions"
                    compact
                    :disabled="state.updatingId === application.id"
                    aria-label="Update outcome"
                    @update:model-value="updateOutcome(application, $event)"
                  />
                  <span v-else class="text-xs text-muted-foreground">—</span>
                </td>
                <td>
                  <div class="flex flex-wrap gap-x-3 gap-y-1 text-xs">
                    <span
                      v-for="item in artifactList(application)"
                      :key="item.path"
                      class="inline-flex items-center gap-1"
                    >
                      <a
                        class="text-primary underline-offset-4 hover:underline"
                        :href="artifactUrl(item.path)"
                        target="_blank"
                        rel="noopener"
                      >{{ item.label }}</a>
                      <button
                        v-if="item.kind"
                        type="button"
                        class="text-muted-foreground hover:text-foreground"
                        :title="`Save this ${item.kind === 'resume' ? 'resume' : 'cover letter'} to my library`"
                        @click="openPromoteDialog(application, item)"
                      >
                        <BookMarked class="h-3 w-3" />
                      </button>
                    </span>
                    <span
                      v-if="!artifactList(application).length"
                      class="text-muted-foreground"
                    >—</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="p-10">
          <EmptyState
            title="No submitted applications yet"
            description="Applications you've submitted will show up here so you can track outcomes."
          >
            <template #icon><Send /></template>
          </EmptyState>
        </div>
      </CardContent>
    </Card>

    <Dialog :open="promoteDialog.open" @update:open="(v) => !v && closePromoteDialog()">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Save to your library</DialogTitle>
          <DialogDescription>
            Copies this file into your document library so AutoApply can use it as a base for future generations.
          </DialogDescription>
        </DialogHeader>
        <label class="space-y-1.5 block text-sm">
          <span class="text-xs font-medium text-muted-foreground">Library name</span>
          <input
            v-model="promoteDialog.displayName"
            type="text"
            class="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
          />
        </label>
        <DialogFooter>
          <Button variant="outline" :disabled="promoteDialog.submitting" @click="closePromoteDialog">
            Cancel
          </Button>
          <Button
            :disabled="promoteDialog.submitting || !promoteDialog.displayName.trim()"
            @click="confirmPromote"
          >
            <BookMarked class="h-4 w-4" />
            {{ promoteDialog.submitting ? "Saving…" : "Save to library" }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
