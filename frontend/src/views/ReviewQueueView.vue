<script setup>
// Phase 17.3 + 17.4: nightly_run review queue kanban.
//
// Four columns: Pending | Approved | Submitted | Rejected.
// 'Stale' lives inline in the Pending column with a refresh button
// (it's the same conceptual queue from the operator's POV: needs
// attention).
//
// Single-item ops: per-card Approve / Reject / Refresh buttons.
// Bulk ops (17.4): multi-select checkboxes + bulk approve / reject
// at the top of the page.
//
// Source of truth is /api/review; we re-fetch on every state change
// rather than mutating client-side optimistically -- the cohort is
// small (a typical nightly run is N=10) and consistency matters more
// than latency here.

import { computed, onMounted, reactive } from "vue"
import {
  Check,
  CircleCheck,
  CircleX,
  Inbox,
  RefreshCw,
  Send,
} from "lucide-vue-next"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { api } from "@/lib/api"
import { formatPercent } from "@/lib/format"

const COLUMNS = [
  { id: "pending", label: "Pending", showStale: true },
  { id: "approved", label: "Approved" },
  { id: "submitted", label: "Submitted" },
  { id: "rejected", label: "Rejected" },
]

const state = reactive({
  loading: false,
  error: "",
  entries: [],
  selected: new Set(),
  pendingAction: false,
  message: "",
  filterCompany: "",
  filterTitle: "",
})

function statusBucket(entry) {
  // Stale rows live in the Pending column with a refresh affordance.
  if (entry.status === "stale") return "pending"
  return entry.status
}

const entriesByColumn = computed(() => {
  const out = Object.fromEntries(COLUMNS.map((c) => [c.id, []]))
  for (const entry of state.entries) {
    const bucket = statusBucket(entry)
    if (out[bucket]) out[bucket].push(entry)
  }
  return out
})

const counts = computed(() => {
  const out = {}
  for (const col of COLUMNS) {
    out[col.id] = entriesByColumn.value[col.id].length
  }
  out.selected = state.selected.size
  return out
})

const selectableEntries = computed(() =>
  state.entries.filter((e) => e.status === "pending" || e.status === "stale"),
)

async function refresh() {
  state.loading = true
  state.error = ""
  try {
    const response = await api.reviewList()
    state.entries = response.entries || []
    // Drop selections for entries that disappeared.
    const present = new Set(state.entries.map((e) => e.id))
    state.selected = new Set([...state.selected].filter((id) => present.has(id)))
  } catch (err) {
    state.error = err?.message || "Failed to load review queue"
  } finally {
    state.loading = false
  }
}

function toggleSelected(entry) {
  const next = new Set(state.selected)
  if (next.has(entry.id)) next.delete(entry.id)
  else next.add(entry.id)
  state.selected = next
}

function clearSelection() {
  state.selected = new Set()
}

function selectAllPending() {
  state.selected = new Set(selectableEntries.value.map((e) => e.id))
}

async function approveOne(entry) {
  await runAction(() => api.reviewApprove(entry.id, { reviewer: "operator" }))
}

async function rejectOne(entry) {
  await runAction(() => api.reviewReject(entry.id, { reviewer: "operator" }))
}

async function refreshOne(entry) {
  await runAction(() => api.reviewRefresh(entry.id, { reviewer: "operator" }))
}

async function submitOne(entry) {
  // Phase 17.5: approve-and-submit. The server runs the pre-submit
  // hard gate; if blocked we surface the gate's verdict inline so the
  // operator sees "refresh required" / "posting expired" without a
  // page reload.
  state.pendingAction = true
  state.message = ""
  try {
    const result = await api.reviewSubmit(entry.id, { reviewer: "operator" })
    if (result.ok) {
      state.message = `Submitted (task ${result.submit_task_id || "queued"}).`
    } else {
      const action = result.gate?.action || "blocked"
      state.message = `Submit blocked: ${action}. ${result.gate?.reason || ""}`
    }
    await refresh()
  } catch (err) {
    state.message = err?.message || "Submit failed"
  } finally {
    state.pendingAction = false
  }
}

async function bulkApprove() {
  if (!state.selected.size) return
  await runBulk(() =>
    api.reviewBulkApprove([...state.selected], { reviewer: "operator" }),
  )
}

async function bulkReject() {
  if (!state.selected.size) return
  await runBulk(() =>
    api.reviewBulkReject([...state.selected], { reviewer: "operator" }),
  )
}

async function bulkRejectByFilter() {
  const payload = {
    reviewer: "operator",
  }
  if (state.filterCompany) payload.company = state.filterCompany
  if (state.filterTitle) payload.keyword_in_title = state.filterTitle
  if (!payload.company && !payload.keyword_in_title) {
    state.message = "Enter a company or title keyword to bulk-reject by filter."
    return
  }
  await runBulk(() => api.reviewBulkRejectByFilter(payload))
  state.filterCompany = ""
  state.filterTitle = ""
}

async function runAction(fn) {
  state.pendingAction = true
  state.message = ""
  try {
    await fn()
    await refresh()
  } catch (err) {
    state.message = err?.message || "Action failed"
  } finally {
    state.pendingAction = false
  }
}

async function runBulk(fn) {
  state.pendingAction = true
  state.message = ""
  try {
    const result = await fn()
    const ok = (result?.succeeded || []).length
    const failed = (result?.failed || []).length
    if (failed) {
      state.message = `${ok} succeeded, ${failed} failed.`
    } else {
      state.message = `${ok} updated.`
    }
    clearSelection()
    await refresh()
  } catch (err) {
    state.message = err?.message || "Bulk action failed"
  } finally {
    state.pendingAction = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="space-y-4">
    <div class="flex items-center justify-between gap-4 flex-wrap">
      <div>
        <h2 class="text-xl font-semibold">Review Queue</h2>
        <p class="text-sm text-muted-foreground">
          Tonight's nightly_run output. Approve, reject, or refresh
          stale entries.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Button variant="outline" :disabled="state.loading" @click="refresh">
          <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': state.loading }" />
          Reload
        </Button>
      </div>
    </div>

    <Alert v-if="state.error" variant="destructive">
      <AlertDescription>{{ state.error }}</AlertDescription>
    </Alert>

    <Card v-if="counts.selected || selectableEntries.length">
      <CardContent class="py-3 flex flex-wrap items-center gap-2">
        <Badge variant="secondary">
          {{ counts.selected }} selected / {{ selectableEntries.length }} actionable
        </Badge>
        <Button
          size="sm"
          variant="outline"
          :disabled="!selectableEntries.length"
          @click="selectAllPending"
        >
          Select all pending
        </Button>
        <Button
          size="sm"
          variant="outline"
          :disabled="!counts.selected"
          @click="clearSelection"
        >
          Clear
        </Button>
        <Button
          size="sm"
          :disabled="!counts.selected || state.pendingAction"
          @click="bulkApprove"
        >
          <Check class="h-4 w-4" />
          Approve {{ counts.selected }} selected
        </Button>
        <Button
          size="sm"
          variant="outline"
          :disabled="!counts.selected || state.pendingAction"
          @click="bulkReject"
        >
          <CircleX class="h-4 w-4" />
          Reject {{ counts.selected }} selected
        </Button>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="pb-2">
        <CardTitle class="text-sm">Bulk reject by filter (Phase 17.4)</CardTitle>
      </CardHeader>
      <CardContent class="flex flex-wrap items-end gap-3">
        <label class="text-xs space-y-1">
          <span class="text-muted-foreground">Company contains</span>
          <input
            v-model="state.filterCompany"
            class="block rounded border bg-background px-2 py-1 text-sm"
            placeholder="e.g. BlocklistedCo"
          />
        </label>
        <label class="text-xs space-y-1">
          <span class="text-muted-foreground">Title contains</span>
          <input
            v-model="state.filterTitle"
            class="block rounded border bg-background px-2 py-1 text-sm"
            placeholder="e.g. senior"
          />
        </label>
        <Button
          size="sm"
          variant="outline"
          :disabled="state.pendingAction"
          @click="bulkRejectByFilter"
        >
          Reject matching pending
        </Button>
      </CardContent>
    </Card>

    <div v-if="state.message" class="text-sm text-muted-foreground">
      {{ state.message }}
    </div>

    <div class="grid gap-4 lg:grid-cols-4">
      <Card v-for="col in COLUMNS" :key="col.id">
        <CardHeader class="pb-2 flex flex-row items-center justify-between">
          <CardTitle class="text-sm">{{ col.label }}</CardTitle>
          <Badge variant="secondary">{{ counts[col.id] }}</Badge>
        </CardHeader>
        <CardContent class="space-y-2 max-h-[60vh] overflow-y-auto">
          <article
            v-for="entry in entriesByColumn[col.id]"
            :key="entry.id"
            class="rounded border p-3 space-y-2"
            :class="{ 'ring-2 ring-primary/30': state.selected.has(entry.id) }"
          >
            <div class="flex items-start justify-between gap-2">
              <div class="space-y-0.5">
                <div class="text-sm font-semibold">
                  {{ entry.title || "(no title)" }}
                </div>
                <div class="text-xs text-muted-foreground">
                  {{ entry.company || "(no company)" }}
                </div>
              </div>
              <input
                v-if="entry.status === 'pending' || entry.status === 'stale'"
                type="checkbox"
                :checked="state.selected.has(entry.id)"
                aria-label="Select entry"
                @change="toggleSelected(entry)"
              />
            </div>

            <div class="flex flex-wrap items-center gap-1 text-xs">
              <Badge v-if="entry.status === 'stale'" variant="destructive">
                Stale (refresh needed)
              </Badge>
              <Badge
                v-if="entry.score_breakdown?.final_score !== undefined"
                variant="outline"
              >
                Score
                {{ formatPercent(entry.score_breakdown.final_score, "0%") }}
              </Badge>
              <Badge v-if="entry.run_id" variant="outline">
                Run {{ String(entry.run_id).slice(0, 8) }}
              </Badge>
            </div>

            <div
              v-if="entry.reason"
              class="text-xs italic text-muted-foreground"
            >
              {{ entry.reason }}
            </div>

            <div v-if="col.id === 'pending'" class="flex gap-1">
              <Button
                size="sm"
                :disabled="state.pendingAction"
                @click="approveOne(entry)"
              >
                <CircleCheck class="h-4 w-4" />
                Approve
              </Button>
              <Button
                size="sm"
                variant="outline"
                :disabled="state.pendingAction"
                @click="rejectOne(entry)"
              >
                Reject
              </Button>
              <Button
                v-if="entry.status === 'stale'"
                size="sm"
                variant="outline"
                :disabled="state.pendingAction"
                @click="refreshOne(entry)"
              >
                <RefreshCw class="h-4 w-4" />
                Refresh
              </Button>
            </div>
            <div v-else-if="col.id === 'approved'" class="flex flex-wrap gap-1">
              <Button
                size="sm"
                :disabled="state.pendingAction"
                @click="submitOne(entry)"
              >
                <Send class="h-4 w-4" />
                Submit
              </Button>
              <Button
                size="sm"
                variant="outline"
                :disabled="state.pendingAction"
                @click="rejectOne(entry)"
              >
                Reject
              </Button>
              <span class="basis-full text-xs text-muted-foreground">
                Submit runs the Phase 17.5 pre-submit gate first.
              </span>
            </div>
          </article>

          <EmptyState
            v-if="!entriesByColumn[col.id].length"
            class="border-none"
            :title="`No ${col.label.toLowerCase()} entries`"
            description=""
          >
            <template #icon><Inbox /></template>
          </EmptyState>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
