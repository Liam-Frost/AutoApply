<script setup>
import { computed, onMounted, reactive } from "vue"
import {
  AlertCircle,
  CalendarClock,
  CheckCircle2,
  ChevronDown,
  Clock3,
  ListChecks,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Trash2,
  XCircle,
} from "lucide-vue-next"

import AppSelect from "@/components/AppSelect.vue"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"

const state = reactive({
  loading: true,
  error: "",
  tasks: [],
  schedule: [],
  filterProfiles: [],
  profiles: [],
  templates: { resume: [], cover_letter: [] },
  documents: { resume: [], cover_letter: [] },
  busy: {},
  statusFilter: "",
  editingPlanId: "",
  planFormOpen: false,
  advancedOpen: false,
  materialsOverrideOpen: false,
  message: "",
  planForm: defaultPlanForm(),
})

const STATUS_OPTIONS = [
  { value: "", label: "All" },
  { value: "queued", label: "Waiting" },
  { value: "running", label: "Running" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
]

const STATUS_LABEL = {
  queued: "Waiting",
  running: "Running",
  succeeded: "Succeeded",
  failed: "Failed",
  cancelled: "Cancelled",
  waiting_human: "Awaiting review",
  expired: "Expired",
}

const CADENCE_OPTIONS = [
  { value: "interval", label: "Every few hours" },
  { value: "daily", label: "Every day" },
  { value: "weekly", label: "Every week" },
  { value: "monthly", label: "Every month" },
]

const INTERVAL_UNIT_OPTIONS = [
  { value: "minutes", label: "minutes" },
  { value: "hours", label: "hours" },
]

const APPLY_MODE_OPTIONS = [
  { value: "review_queue", label: "Hold them for me to review" },
  { value: "auto_apply", label: "Submit automatically" },
]

const DAY_OF_WEEK_OPTIONS = [
  { value: 0, label: "Sunday" },
  { value: 1, label: "Monday" },
  { value: 2, label: "Tuesday" },
  { value: 3, label: "Wednesday" },
  { value: 4, label: "Thursday" },
  { value: 5, label: "Friday" },
  { value: 6, label: "Saturday" },
]

const APPLY_MODE_LABEL = {
  review_queue: "Holds for review",
  auto_apply: "Submits automatically",
}

const PLAN_STRATEGY_OPTIONS = [
  { value: "", label: "Use my default" },
  { value: "regenerate", label: "Regenerate from a template" },
  { value: "patch_existing", label: "Patch a library document" },
]

function planTemplateOptions(docType) {
  return [
    { value: "", label: "Use my default" },
    ...((state.templates[docType] || []).map((tpl) => ({
      value: tpl.template_id,
      label: tpl.name || tpl.template_id,
    }))),
  ]
}

function planDocumentOptions(docType) {
  const docs = state.documents[docType] || []
  return [
    {
      value: "",
      label: docs.length ? "Use my default" : "No editable documents in your library",
    },
    ...docs.map((doc) => ({
      value: doc.id,
      label: `${doc.display_name} · ${doc.source_type.toUpperCase()}`,
    })),
  ]
}

function planDocTypeLabel(docType) {
  return docType === "resume" ? "Resume" : "Cover Letter"
}

const localTimezone = (() => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "your local time"
  } catch {
    return "your local time"
  }
})()

function defaultPlanForm() {
  return {
    name: "",
    enabled: true,
    search_profile_id: "",
    profile_id: "default",
    cadence: "interval",
    interval_every: 1,
    interval_unit: "hours",
    hour: 9,
    minute: 0,
    day_of_week: 1,
    day_of_month: 1,
    scrape_enabled: true,
    apply_mode: "review_queue",
    skip_previously_applied: true,
    top_n: 10,
    dry_run: false,
    // Phase 17.8: per-plan material overrides. Empty strings mean
    // "inherit Settings → Default material strategy".
    resume_strategy: "",
    resume_template_id: "",
    resume_source_document_id: "",
    cover_letter_strategy: "",
    cover_letter_template_id: "",
    cover_letter_source_document_id: "",
  }
}

function utcToLocal(utcHour, utcMinute) {
  const d = new Date()
  d.setUTCHours(utcHour ?? 0, utcMinute ?? 0, 0, 0)
  return { hour: d.getHours(), minute: d.getMinutes() }
}

function localToUtc(localHour, localMinute) {
  const d = new Date()
  d.setHours(localHour ?? 0, localMinute ?? 0, 0, 0)
  return { hour: d.getUTCHours(), minute: d.getUTCMinutes() }
}

const timeOfDay = computed({
  get() {
    const h = String(state.planForm.hour ?? 0).padStart(2, "0")
    const m = String(state.planForm.minute ?? 0).padStart(2, "0")
    return `${h}:${m}`
  },
  set(value) {
    if (typeof value !== "string") return
    const [h, m] = value.split(":")
    state.planForm.hour = Number(h) || 0
    state.planForm.minute = Number(m) || 0
  },
})

async function refreshAll() {
  state.loading = true
  state.error = ""
  try {
    const suffix = state.statusFilter
      ? `?limit=75&status=${encodeURIComponent(state.statusFilter)}`
      : "?limit=75"
    const [tasksResp, scheduleResp, filtersResp, profilesResp, templatesResp, docsResp] =
      await Promise.all([
        api.get(`/api/tasks${suffix}`),
        api.automationPlans(),
        api.filterProfiles(),
        api.profile(),
        api.templates().catch(() => ({ templates: {} })),
        api.documents().catch(() => ({ documents: [] })),
      ])
    state.tasks = tasksResp.items || []
    state.schedule = scheduleResp || []
    state.filterProfiles = filtersResp.profiles || []
    state.profiles = profilesResp.profiles || []
    state.templates = {
      resume: templatesResp?.templates?.resume || [],
      cover_letter: templatesResp?.templates?.cover_letter || [],
    }
    const docs = docsResp?.documents || []
    state.documents = {
      resume: docs.filter((d) => d.document_type === "resume" && d.editable),
      cover_letter: docs.filter((d) => d.document_type === "cover_letter" && d.editable),
    }
  } catch (err) {
    state.error = err?.message || "Failed to load plans."
  } finally {
    state.loading = false
  }
}

const activeRuns = computed(() =>
  state.tasks.filter((task) => ["queued", "running", "waiting_human"].includes(task.status)),
)

const failedRuns = computed(() =>
  state.tasks.filter((task) => task.status === "failed"),
)

const nextSchedule = computed(() => {
  return [...state.schedule]
    .filter((entry) => entry.next_run_at)
    .sort((a, b) => new Date(a.next_run_at) - new Date(b.next_run_at))[0]
})

const filterProfileOptions = computed(() => [
  { value: "", label: state.filterProfiles.length ? "Pick a saved search" : "No saved searches yet" },
  ...state.filterProfiles.map((profile) => ({ value: profile.id, label: profile.id })),
])

const applicantProfileOptions = computed(() => [
  { value: "", label: state.profiles.length ? "Pick a profile" : "No saved profiles yet" },
  ...state.profiles.map((profile) => ({ value: profile.id, label: profile.name || profile.id })),
])

function statusVariant(status) {
  if (status === "succeeded") return "default"
  if (status === "failed") return "destructive"
  if (status === "running" || status === "waiting_human") return "secondary"
  return "outline"
}

function statusLabel(status) {
  return STATUS_LABEL[status] || status
}

function applyModeLabel(mode) {
  return APPLY_MODE_LABEL[mode] || mode
}

function formatTimestamp(iso) {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function relativeFromNow(iso) {
  if (!iso) return ""
  const d = new Date(iso).getTime()
  if (Number.isNaN(d)) return ""
  const diffMs = d - Date.now()
  const abs = Math.abs(diffMs)
  const minutes = Math.round(abs / 60000)
  if (minutes < 1) return diffMs >= 0 ? "now" : "just now"
  if (minutes < 60) return diffMs >= 0 ? `in ${minutes}m` : `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return diffMs >= 0 ? `in ${hours}h` : `${hours}h ago`
  const days = Math.round(hours / 24)
  return diffMs >= 0 ? `in ${days}d` : `${days}d ago`
}

async function setStatusFilter(value) {
  if (state.statusFilter === value) return
  state.statusFilter = value
  await refreshAll()
}

async function runScheduleNow(name) {
  state.busy[name] = "run-now"
  try {
    const entry = state.schedule.find((item) => item.name === name)
    await api.runAutomationPlan(entry.plan_id)
    await refreshAll()
  } catch (err) {
    state.error = err?.message || "Couldn't start that plan right now."
  } finally {
    delete state.busy[name]
  }
}

function openCreatePlan() {
  state.editingPlanId = ""
  state.planForm = defaultPlanForm()
  state.advancedOpen = false
  state.materialsOverrideOpen = false
  state.planFormOpen = true
  state.message = ""
}

function openEditPlan(entry) {
  if (entry.read_only) return
  state.editingPlanId = entry.plan_id
  const local = utcToLocal(entry.hour ?? 9, entry.minute ?? 0)
  state.planForm = {
    ...defaultPlanForm(),
    name: entry.display_name,
    enabled: entry.enabled,
    search_profile_id: entry.search_profile_id || "",
    profile_id: entry.profile_id || "default",
    cadence: entry.cadence || "interval",
    interval_every: entry.interval_every || 1,
    interval_unit: entry.interval_unit || "hours",
    hour: local.hour,
    minute: local.minute,
    day_of_week: entry.day_of_week ?? 1,
    day_of_month: entry.day_of_month ?? 1,
    scrape_enabled: entry.scrape_enabled,
    apply_mode: entry.apply_mode || "review_queue",
    skip_previously_applied: entry.skip_previously_applied,
    top_n: entry.top_n || 10,
    dry_run: entry.dry_run,
    resume_strategy: entry.resume_strategy || "",
    resume_template_id: entry.resume_template_id || "",
    resume_source_document_id: entry.resume_source_document_id || "",
    cover_letter_strategy: entry.cover_letter_strategy || "",
    cover_letter_template_id: entry.cover_letter_template_id || "",
    cover_letter_source_document_id: entry.cover_letter_source_document_id || "",
  }
  state.advancedOpen = Boolean(
    entry.dry_run || entry.scrape_enabled === false,
  )
  state.materialsOverrideOpen = Boolean(
    entry.resume_strategy ||
      entry.resume_template_id ||
      entry.resume_source_document_id ||
      entry.cover_letter_strategy ||
      entry.cover_letter_template_id ||
      entry.cover_letter_source_document_id,
  )
  state.planFormOpen = true
  state.message = ""
}

function closePlanForm() {
  state.planFormOpen = false
  state.editingPlanId = ""
  state.planForm = defaultPlanForm()
  state.advancedOpen = false
}

function planPayload() {
  const utc = localToUtc(
    Number(state.planForm.hour),
    Number(state.planForm.minute),
  )
  return {
    ...state.planForm,
    hour: utc.hour,
    minute: utc.minute,
    interval_every: Number(state.planForm.interval_every),
    day_of_week: Number(state.planForm.day_of_week),
    day_of_month: Number(state.planForm.day_of_month),
    top_n: Number(state.planForm.top_n),
  }
}

async function savePlan() {
  const payload = planPayload()
  if (!payload.name.trim()) {
    state.error = "Give this plan a name."
    return
  }
  if (!payload.search_profile_id) {
    state.error = "Pick a saved search filter."
    return
  }
  if (!payload.profile_id) {
    state.error = "Pick which profile to apply with."
    return
  }
  const key = state.editingPlanId || payload.name
  state.busy.planForm = "save"
  state.error = ""
  try {
    if (state.editingPlanId) {
      await api.updateAutomationPlan(state.editingPlanId, payload)
    } else {
      await api.createAutomationPlan(payload)
    }
    state.message = `Saved “${payload.name}”.`
    closePlanForm()
    await refreshAll()
  } catch (err) {
    state.error = err?.message || "Couldn't save that plan."
  } finally {
    delete state.busy.planForm
    delete state.busy[key]
  }
}

async function deletePlan(entry) {
  if (entry.read_only || !entry.plan_id) return
  state.busy[entry.name] = "delete"
  state.error = ""
  try {
    await api.deleteAutomationPlan(entry.plan_id)
    state.message = `Deleted “${entry.display_name}”.`
    await refreshAll()
  } catch (err) {
    state.error = err?.message || "Couldn't delete that plan."
  } finally {
    delete state.busy[entry.name]
  }
}

async function retryTask(id) {
  state.busy[id] = "retry"
  try {
    await api.post(`/api/tasks/${id}/retry`, {})
    await refreshAll()
  } catch (err) {
    state.error = err?.message || "Couldn't retry that run."
  } finally {
    delete state.busy[id]
  }
}

async function cancelTask(id) {
  state.busy[id] = "cancel"
  try {
    await api.post(`/api/tasks/${id}/cancel`, {})
    await refreshAll()
  } catch (err) {
    state.error = err?.message || "Couldn't cancel that run."
  } finally {
    delete state.busy[id]
  }
}

onMounted(refreshAll)
</script>

<template>
  <div class="space-y-6">
    <div class="flex flex-wrap items-start justify-between gap-4">
      <div class="space-y-1">
        <h2 class="text-xl font-semibold">Plans</h2>
        <p class="max-w-3xl text-sm text-muted-foreground">
          A plan tells AutoApply which jobs to look at, how often to check, and whether to submit on your behalf.
        </p>
      </div>
      <Button variant="outline" :disabled="state.loading" @click="refreshAll">
        <RefreshCw class="size-4" :class="state.loading ? 'animate-spin' : ''" />
        Reload
      </Button>
    </div>

    <Alert v-if="state.error" variant="destructive">
      <AlertCircle class="h-4 w-4" />
      <AlertDescription>{{ state.error }}</AlertDescription>
    </Alert>
    <Alert v-if="state.message" class="border-primary/40 bg-primary/5">
      <CheckCircle2 class="h-4 w-4" />
      <AlertDescription>{{ state.message }}</AlertDescription>
    </Alert>

    <section class="grid gap-4 md:grid-cols-4">
      <Card>
        <CardContent class="flex items-start justify-between gap-3 p-5">
          <div>
            <p class="text-xs font-medium text-muted-foreground">Active plans</p>
            <p class="mt-1 text-2xl font-bold tabular-nums">{{ state.schedule.length }}</p>
          </div>
          <CalendarClock class="h-5 w-5 text-muted-foreground" />
        </CardContent>
      </Card>
      <Card>
        <CardContent class="flex items-start justify-between gap-3 p-5">
          <div>
            <p class="text-xs font-medium text-muted-foreground">Currently running</p>
            <p class="mt-1 text-2xl font-bold tabular-nums">{{ activeRuns.length }}</p>
          </div>
          <Clock3 class="h-5 w-5 text-muted-foreground" />
        </CardContent>
      </Card>
      <Card>
        <CardContent class="flex items-start justify-between gap-3 p-5">
          <div>
            <p class="text-xs font-medium text-muted-foreground">Recent failures</p>
            <p class="mt-1 text-2xl font-bold tabular-nums">{{ failedRuns.length }}</p>
          </div>
          <XCircle class="h-5 w-5 text-muted-foreground" />
        </CardContent>
      </Card>
      <Card>
        <CardContent class="flex items-start justify-between gap-3 p-5">
          <div>
            <p class="text-xs font-medium text-muted-foreground">Next run</p>
            <p class="mt-1 text-sm font-semibold">
              {{ nextSchedule ? relativeFromNow(nextSchedule.next_run_at) : "Nothing scheduled" }}
            </p>
            <p v-if="nextSchedule" class="text-xs text-muted-foreground">
              {{ nextSchedule.display_name }}
            </p>
          </div>
          <ListChecks class="h-5 w-5 text-muted-foreground" />
        </CardContent>
      </Card>
    </section>

    <Card>
      <CardHeader>
        <div class="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>Your plans</CardTitle>
          <Button v-if="!state.planFormOpen" size="sm" @click="openCreatePlan">
            <Plus class="size-4" />
            New plan
          </Button>
        </div>
      </CardHeader>
      <CardContent class="space-y-4">
        <div v-if="state.planFormOpen" class="rounded-lg border bg-muted/20 p-5 space-y-6">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div>
              <div class="font-medium">
                {{ state.editingPlanId ? "Edit plan" : "New plan" }}
              </div>
              <div class="text-xs text-muted-foreground">
                Pick what to look at, how often, and what should happen when AutoApply finds matches.
              </div>
            </div>
            <Button size="sm" variant="ghost" @click="closePlanForm">Cancel</Button>
          </div>

          <div class="grid gap-3 md:grid-cols-[2fr_auto]">
            <label class="space-y-1.5">
              <span class="text-xs font-medium text-muted-foreground">Plan name</span>
              <Input v-model="state.planForm.name" placeholder="e.g. Frontend internships" />
            </label>
            <label class="flex items-end gap-2 pb-2 text-sm">
              <input v-model="state.planForm.enabled" type="checkbox" />
              Enabled
            </label>
          </div>

          <div class="space-y-3">
            <div class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              What to look for
            </div>
            <div class="grid gap-3 md:grid-cols-2">
              <label class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Saved search filter</span>
                <AppSelect v-model="state.planForm.search_profile_id" :options="filterProfileOptions" />
              </label>
              <label class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Apply as</span>
                <AppSelect v-model="state.planForm.profile_id" :options="applicantProfileOptions" />
              </label>
            </div>
          </div>

          <div class="space-y-3">
            <div class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              How often
            </div>
            <div class="grid gap-3 md:grid-cols-3">
              <label class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Cadence</span>
                <AppSelect v-model="state.planForm.cadence" :options="CADENCE_OPTIONS" />
              </label>
              <label v-if="state.planForm.cadence === 'interval'" class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Every</span>
                <Input v-model="state.planForm.interval_every" type="number" min="1" max="24" />
              </label>
              <label v-if="state.planForm.cadence === 'interval'" class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Unit</span>
                <AppSelect v-model="state.planForm.interval_unit" :options="INTERVAL_UNIT_OPTIONS" />
              </label>
              <label v-if="state.planForm.cadence !== 'interval'" class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Time of day</span>
                <input
                  v-model="timeOfDay"
                  type="time"
                  class="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </label>
              <label v-if="state.planForm.cadence === 'weekly'" class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Day of week</span>
                <AppSelect v-model="state.planForm.day_of_week" :options="DAY_OF_WEEK_OPTIONS" />
              </label>
              <label v-if="state.planForm.cadence === 'monthly'" class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Day of month</span>
                <Input v-model="state.planForm.day_of_month" type="number" min="1" max="31" />
              </label>
            </div>
            <p v-if="state.planForm.cadence !== 'interval'" class="text-xs text-muted-foreground">
              Time shown in your local timezone ({{ localTimezone }}).
            </p>
          </div>

          <div class="space-y-3">
            <div class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              When jobs match
            </div>
            <div class="grid gap-3 md:grid-cols-2">
              <label class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">What should AutoApply do?</span>
                <AppSelect v-model="state.planForm.apply_mode" :options="APPLY_MODE_OPTIONS" />
              </label>
              <label class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Cap each run at</span>
                <Input v-model="state.planForm.top_n" type="number" min="1" max="100" />
              </label>
              <label class="flex items-center gap-2 text-sm md:col-span-2">
                <input v-model="state.planForm.skip_previously_applied" type="checkbox" />
                Skip jobs I've already applied to
              </label>
            </div>
          </div>

          <div class="space-y-2">
            <button
              type="button"
              class="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
              @click="state.materialsOverrideOpen = !state.materialsOverrideOpen"
            >
              <ChevronDown
                class="h-3.5 w-3.5 transition-transform"
                :class="state.materialsOverrideOpen ? 'rotate-0' : '-rotate-90'"
              />
              Materials (override Settings defaults)
            </button>
            <div
              v-if="state.materialsOverrideOpen"
              class="space-y-3 rounded-md border bg-background/60 p-3 text-sm"
            >
              <p class="text-xs text-muted-foreground">
                Leave a strategy as “Use my default” to inherit what you set in Settings → Default material strategy.
              </p>
              <div
                v-for="docType in ['resume', 'cover_letter']"
                :key="docType"
                class="space-y-2 rounded border bg-muted/30 p-3"
              >
                <div class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  {{ planDocTypeLabel(docType) }}
                </div>
                <div class="grid gap-2 md:grid-cols-2">
                  <label class="space-y-1.5">
                    <span class="text-xs font-medium text-muted-foreground">Strategy</span>
                    <AppSelect
                      v-model="state.planForm[`${docType}_strategy`]"
                      :options="PLAN_STRATEGY_OPTIONS"
                      :aria-label="`${planDocTypeLabel(docType)} strategy`"
                    />
                  </label>
                  <label
                    v-if="state.planForm[`${docType}_strategy`] !== 'patch_existing'"
                    class="space-y-1.5"
                  >
                    <span class="text-xs font-medium text-muted-foreground">Template (optional)</span>
                    <AppSelect
                      v-model="state.planForm[`${docType}_template_id`]"
                      :options="planTemplateOptions(docType)"
                      :aria-label="`${planDocTypeLabel(docType)} template`"
                    />
                  </label>
                  <label
                    v-else
                    class="space-y-1.5"
                  >
                    <span class="text-xs font-medium text-muted-foreground">Library document</span>
                    <AppSelect
                      v-model="state.planForm[`${docType}_source_document_id`]"
                      :options="planDocumentOptions(docType)"
                      :aria-label="`${planDocTypeLabel(docType)} library document`"
                    />
                  </label>
                </div>
              </div>
            </div>
          </div>

          <div class="space-y-2">
            <button
              type="button"
              class="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
              @click="state.advancedOpen = !state.advancedOpen"
            >
              <ChevronDown
                class="h-3.5 w-3.5 transition-transform"
                :class="state.advancedOpen ? 'rotate-0' : '-rotate-90'"
              />
              Advanced
            </button>
            <div v-if="state.advancedOpen" class="space-y-2 rounded-md border bg-background/60 p-3 text-sm">
              <label class="flex items-center gap-2">
                <input v-model="state.planForm.scrape_enabled" type="checkbox" />
                Refresh job listings before each run
              </label>
              <label class="flex items-center gap-2">
                <input v-model="state.planForm.dry_run" type="checkbox" />
                Test mode — go through the motions but don't submit
              </label>
            </div>
          </div>

          <div class="flex items-center justify-end">
            <Button size="sm" :disabled="!!state.busy.planForm" @click="savePlan">
              <Save class="size-4" />
              Save plan
            </Button>
          </div>
        </div>

        <p v-if="state.schedule.length === 0 && !state.planFormOpen" class="text-sm text-muted-foreground">
          You don't have any plans yet. Create one to start applying on a schedule.
        </p>
        <ul v-else-if="state.schedule.length" class="divide-y">
          <li
            v-for="entry in state.schedule"
            :key="entry.name"
            class="flex flex-col gap-4 py-4 md:flex-row md:items-start md:justify-between"
          >
            <div class="min-w-0 flex-1 space-y-2">
              <div>
                <div class="font-medium">{{ entry.display_name }}</div>
                <div class="text-sm text-muted-foreground">{{ entry.description }}</div>
              </div>
              <div class="flex flex-wrap gap-2">
                <Badge v-if="!entry.enabled" variant="outline">Paused</Badge>
                <Badge variant="outline">Search: {{ entry.search_profile_id }}</Badge>
                <Badge variant="outline">As: {{ entry.profile_id }}</Badge>
                <Badge variant="outline">{{ applyModeLabel(entry.apply_mode) }}</Badge>
                <Badge v-if="entry.skip_previously_applied" variant="outline">Skips dupes</Badge>
                <Badge v-if="entry.dry_run" variant="outline">Test mode</Badge>
              </div>
              <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                <span>Runs: {{ entry.schedule_human }}</span>
                <span v-if="entry.next_run_at">
                  Next: {{ formatTimestamp(entry.next_run_at) }} ({{ relativeFromNow(entry.next_run_at) }})
                </span>
              </div>
            </div>
            <div class="flex flex-wrap gap-2 md:justify-end">
              <Button
                size="sm"
                variant="outline"
                :disabled="!!state.busy[entry.name]"
                @click="runScheduleNow(entry.name)"
              >
                <Play class="size-4" />
                Run now
              </Button>
              <Button
                v-if="!entry.read_only"
                size="sm"
                variant="outline"
                :disabled="!!state.busy[entry.name]"
                @click="openEditPlan(entry)"
              >
                Edit
              </Button>
              <Button
                v-if="!entry.read_only"
                size="sm"
                variant="outline"
                :disabled="!!state.busy[entry.name]"
                @click="deletePlan(entry)"
              >
                <Trash2 class="size-4" />
                Delete
              </Button>
            </div>
          </li>
        </ul>
      </CardContent>
    </Card>

    <Card>
      <CardHeader class="gap-3">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <CardTitle>Recent runs</CardTitle>
          <div class="flex flex-wrap gap-1">
            <Button
              v-for="option in STATUS_OPTIONS"
              :key="option.value || 'all'"
              size="sm"
              variant="ghost"
              class="h-7 px-2 text-xs"
              :class="state.statusFilter === option.value ? 'bg-muted text-foreground' : 'text-muted-foreground'"
              @click="setStatusFilter(option.value)"
            >
              {{ option.label }}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <p v-if="state.tasks.length === 0" class="text-sm text-muted-foreground">
          No runs match this filter yet.
        </p>
        <div v-else class="overflow-x-auto">
          <table class="w-full min-w-[640px] text-sm">
            <thead>
              <tr class="text-left text-muted-foreground">
                <th class="py-2 pr-4">Plan</th>
                <th class="py-2 pr-4">Status</th>
                <th class="py-2 pr-4">Tries</th>
                <th class="py-2 pr-4">Finished</th>
                <th class="py-2 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="task in state.tasks" :key="task.id" class="border-t align-top">
                <td class="py-3 pr-4">
                  <div class="font-medium">{{ task.kind_display }}</div>
                  <div v-if="task.kind_description" class="text-xs text-muted-foreground">
                    {{ task.kind_description }}
                  </div>
                </td>
                <td class="py-3 pr-4">
                  <Badge :variant="statusVariant(task.status)">{{ statusLabel(task.status) }}</Badge>
                  <div
                    v-if="task.last_error"
                    class="mt-1 max-w-[240px] truncate text-xs text-destructive"
                    :title="task.last_error"
                  >
                    {{ task.last_error }}
                  </div>
                </td>
                <td class="py-3 pr-4 tabular-nums">{{ task.attempts }}</td>
                <td class="py-3 pr-4 text-xs text-muted-foreground">
                  {{ formatTimestamp(task.finished_at) }}
                </td>
                <td class="py-3 text-right">
                  <Button
                    v-if="task.status === 'failed' || task.status === 'cancelled'"
                    size="sm"
                    variant="outline"
                    :disabled="!!state.busy[task.id]"
                    @click="retryTask(task.id)"
                  >
                    <RotateCcw class="size-4" />
                    Retry
                  </Button>
                  <Button
                    v-else-if="task.status === 'queued'"
                    size="sm"
                    variant="outline"
                    :disabled="!!state.busy[task.id]"
                    @click="cancelTask(task.id)"
                  >
                    Cancel
                  </Button>
                  <CheckCircle2
                    v-else-if="task.status === 'succeeded'"
                    class="ml-auto h-4 w-4 text-muted-foreground"
                  />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
