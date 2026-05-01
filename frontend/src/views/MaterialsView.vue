<script setup>
import { computed, onMounted, reactive, watch } from "vue"
import { RouterLink, useRoute } from "vue-router"
import {
  AlertCircle,
  Briefcase,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  Info,
  Library,
  Sparkles,
  UserCircle,
  Wand2,
} from "lucide-vue-next"

import AppSelect from "@/components/AppSelect.vue"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import { jobsState } from "@/lib/jobs-state"
import {
  documentTypeLabel,
  loadTemplates,
  materialOptionLabel,
  materialTypeForOutput,
  outputFormatLabel,
  templateRenderer,
  templateSupportedOutputs,
  templatesState,
} from "@/lib/materials-templates"

const route = useRoute()

const targets = [
  {
    id: "resume",
    label: "Resume",
    materialType: "resume_docx",
    templateType: "resume",
    icon: FileText,
  },
  {
    id: "cover_letter",
    label: "Cover Letter",
    materialType: "cover_letter_docx",
    templateType: "cover_letter",
    icon: FileText,
  },
]

const state = reactive({
  loading: true,
  generating: false,
  error: "",
  message: "",
  sourceMode: "job",
  selectedJobId: "",
  jobLocked: false,
  profileId: "",
  profiles: [],
  selectedMaterials: { resume: true, cover_letter: true },
  selectedFormats: {
    resume_docx: true,
    resume_pdf: true,
    resume_tex: false,
    cover_letter_docx: true,
    cover_letter_pdf: true,
    cover_letter_tex: false,
  },
  templateIds: { resume: "", cover_letter: "" },
  expandedMaterial: { resume: false, cover_letter: false },
  customJob: {
    company: "",
    title: "",
    location: "",
    application_url: "",
    description: "",
  },
  activePreviewTab: "resume",
  previewExpanded: {},
  results: {},
})

const allJobs = computed(() => {
  const seen = new Set()
  const jobs = []
  for (const job of [
    ...(jobsState.filteredJobs || []),
    ...(jobsState.resultSets?.shown || []),
    ...(jobsState.resultSets?.fetched || []),
    ...(jobsState.resultSets?.linkedin || []),
    ...(jobsState.resultSets?.ats || []),
  ]) {
    const key = job.id || `${job.company}-${job.title}-${job.application_url}`
    if (seen.has(key)) {
      continue
    }
    seen.add(key)
    jobs.push(job)
  }
  return jobs
})

const jobOptions = computed(() => [
  { value: "", label: allJobs.value.length ? "Select a search result" : "No search results loaded" },
  ...allJobs.value.map((job) => ({
    value: job.id,
    label: `${job.company} · ${job.title}${job.location ? ` · ${job.location}` : ""}`,
  })),
])

const selectedJob = computed(
  () => allJobs.value.find((job) => job.id === state.selectedJobId) || null,
)

const profileOptions = computed(() => [
  { value: "", label: state.profiles.length ? "Select applicant" : "No saved applicants" },
  ...state.profiles.map((profile) => ({ value: profile.id, label: profile.name || profile.id })),
])

const selectedProfile = computed(
  () => state.profiles.find((profile) => profile.id === state.profileId) || null,
)

const resumeTemplateOptions = computed(() => templateOptions("resume"))
const coverLetterTemplateOptions = computed(() => templateOptions("cover_letter"))

const selectedTargets = computed(() =>
  targets.filter((target) => state.selectedMaterials[target.id] && selectedFormatTypes(target.id).length),
)

const canGenerate = computed(
  () =>
    Boolean(state.profileId) &&
    Boolean(currentJobPayload.value) &&
    selectedTargets.value.length > 0,
)

const currentJobPayload = computed(() => {
  if (state.sourceMode === "job") {
    return selectedJob.value
  }
  const title = state.customJob.title.trim()
  const company = state.customJob.company.trim()
  const description = state.customJob.description.trim()
  if (!title || !company || !description) {
    return null
  }
  return {
    id: `manual-${company}-${title}`,
    source: "company_site",
    source_id: `manual:${company}:${title}`,
    company,
    title,
    location: state.customJob.location.trim(),
    description,
    application_url: state.customJob.application_url.trim(),
    ats_type: "company_site",
    employment_type: "unknown",
    seniority: "unknown",
    raw_data: { manual_jd: true },
  }
})

const reviewEntries = computed(() =>
  targets
    .map((target) => ({ ...target, result: state.results[target.id] }))
    .filter((entry) => entry.result?.document),
)

const previewTabs = computed(() =>
  targets.map((target) => ({
    ...target,
    available: Boolean(state.results[target.id]?.document),
  })),
)

const activePreviewEntry = computed(
  () =>
    reviewEntries.value.find((entry) => entry.id === state.activePreviewTab) ||
    reviewEntries.value[0] ||
    null,
)

const jobReady = computed(() => Boolean(currentJobPayload.value))
const showJobBody = computed(() => !state.jobLocked || !jobReady.value)

onMounted(async () => {
  try {
    await Promise.all([loadProfiles(), loadTemplates()])
    syncTemplateDefaults()
    applyRouteJob()
  } catch (error) {
    state.error = error.message
  } finally {
    state.loading = false
  }
})

watch(
  () => route.query.jobId,
  () => applyRouteJob(),
)

watch(
  () => state.templateIds.resume,
  () => syncSelectedFormats("resume"),
)

watch(
  () => state.templateIds.cover_letter,
  () => syncSelectedFormats("cover_letter"),
)

watch(
  () => templatesState.templates,
  () => syncTemplateDefaults(),
  { deep: true },
)

watch(
  () => [state.sourceMode, state.selectedJobId, state.customJob],
  () => {
    if (!jobReady.value) {
      state.jobLocked = false
    }
  },
  { deep: true },
)

async function loadProfiles() {
  const response = await api.profile()
  state.profiles = response.profiles || []
  state.profileId = response.active_profile_id || state.profiles[0]?.id || ""
}

function syncTemplateDefaults() {
  if (!state.templateIds.resume) {
    state.templateIds.resume = templatesState.templates.resume[0]?.template_id || ""
  }
  if (!state.templateIds.cover_letter) {
    state.templateIds.cover_letter = templatesState.templates.cover_letter[0]?.template_id || ""
  }
  syncSelectedFormats("resume")
  syncSelectedFormats("cover_letter")
}

function applyRouteJob() {
  const jobId = typeof route.query.jobId === "string" ? route.query.jobId : ""
  if (!jobId) {
    if (!state.selectedJobId && allJobs.value.length) {
      state.selectedJobId = allJobs.value[0].id
    }
    return
  }
  const job = allJobs.value.find((item) => item.id === jobId)
  if (job) {
    state.sourceMode = "job"
    state.selectedJobId = job.id
    state.jobLocked = true
  }
}

async function generateMaterials() {
  state.error = ""
  state.message = ""
  state.results = {}

  const job = currentJobPayload.value
  if (!job) {
    state.error = "Select a job or paste a complete JD before generating."
    return
  }
  if (!state.profileId) {
    state.error = "Select a saved applicant profile before generating."
    return
  }

  state.generating = true
  const settled = await Promise.allSettled(
    selectedTargets.value.map((target) =>
      api
        .generateJobMaterial(
          job,
          primaryMaterialType(target),
          state.templateIds[target.templateType],
          state.profileId,
        )
        .then((response) => ({ target, response })),
    ),
  )
  const successes = []
  const failures = []
  settled.forEach((result, index) => {
    const target = selectedTargets.value[index]
    if (result.status === "fulfilled") {
      state.results[target.id] = result.value.response
      state.previewExpanded[target.id] = false
      state.activePreviewTab ||= target.id
      successes.push(target.label)
    } else {
      failures.push(`${target.label}: ${result.reason?.message || "generation failed"}`)
    }
  })
  state.generating = false
  state.activePreviewTab = successes.length
    ? selectedTargets.value.find((target) => state.results[target.id])?.id || state.activePreviewTab
    : state.activePreviewTab
  state.message = successes.length ? `Generated ${successes.join(" and ")}.` : ""
  state.error = failures.join("; ")
}

function templateOptions(documentType) {
  const templates = templatesState.templates[documentType] || []
  if (!templates.length) {
    return [{ value: "", label: "Default template" }]
  }
  return templates.map((template) => ({
    value: template.template_id,
    label: `${template.name || template.template_id} · ${
      templateRenderer(template) === "latex" ? "LaTeX" : "DOCX"
    }`,
  }))
}

function selectedFormatTypes(targetId) {
  return availableFormatOptions(targetId)
    .filter((option) => state.selectedFormats[option.type])
    .map((option) => option.type)
}

function availableFormatOptions(targetId) {
  const target = targets.find((item) => item.id === targetId)
  if (!target) {
    return []
  }
  const template = selectedTemplate(target.templateType)
  return templateSupportedOutputs(template).map((output) => ({
    type: materialTypeForOutput(target.templateType, output),
    label: outputFormatLabel(output),
  }))
}

function syncSelectedFormats(documentType) {
  const prefix = documentType === "cover_letter" ? "cover_letter" : "resume"
  for (const output of ["docx", "pdf", "tex"]) {
    state.selectedFormats[`${prefix}_${output}`] = false
  }
  for (const output of templateSupportedOutputs(selectedTemplate(documentType))) {
    state.selectedFormats[materialTypeForOutput(documentType, output)] = true
  }
}

function selectedTemplate(documentType) {
  return (templatesState.templates[documentType] || []).find(
    (template) => template.template_id === state.templateIds[documentType],
  )
}

function selectedTemplateLabel(documentType) {
  const template = selectedTemplate(documentType)
  if (!template) {
    return "Default template"
  }
  return template.name || template.template_id
}

function primaryMaterialType(target) {
  return selectedFormatTypes(target.id)[0] || target.materialType
}

function artifactEntries(result, targetId) {
  const selected = new Set(selectedFormatTypes(targetId))
  return Object.entries(result?.artifacts || {})
    .filter(([type, path]) => selected.has(type) && Boolean(path))
    .map(([type, path]) => ({ type, path, label: materialOptionLabel(type) }))
}

function artifactDownloadUrl(path) {
  return api.artifactDownloadUrl(path)
}

function validationIssues(result) {
  return result?.validation?.issues || []
}

function validationMetrics(result) {
  return result?.validation?.metrics || {}
}

function resumePreviewItems(document) {
  if (!document || document.document_type !== "resume") {
    return []
  }
  return [
    ...(document.experiences || []).map((item) => ({ ...item, section: "Experience" })),
    ...(document.projects || []).map((item) => ({ ...item, section: "Projects" })),
  ]
}

function coverParagraphs(document) {
  return document?.document_type === "cover_letter" ? document.paragraphs || [] : []
}

function prettyLabel(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function selectPreviewTab(targetId) {
  if (!state.results[targetId]?.document) {
    return
  }
  state.activePreviewTab = targetId
}

function togglePreview(targetId) {
  state.previewExpanded[targetId] = !state.previewExpanded[targetId]
}

function toggleMaterialExpanded(targetId) {
  state.expandedMaterial[targetId] = !state.expandedMaterial[targetId]
}

function toggleMaterialSelected(targetId) {
  const next = !state.selectedMaterials[targetId]
  state.selectedMaterials[targetId] = next
  if (next && !state.expandedMaterial[targetId]) {
    state.expandedMaterial[targetId] = true
  }
}

function unlockJob() {
  state.jobLocked = false
}

function lockJob() {
  if (jobReady.value) {
    state.jobLocked = true
  }
}

function jobSummaryParts(job) {
  if (!job) {
    return []
  }
  return [job.company, job.title, job.location].filter(Boolean)
}
</script>

<template>
  <div class="space-y-6">
    <Card>
      <CardContent class="flex flex-col items-start justify-between gap-3 p-5 md:flex-row md:items-center">
        <div class="space-y-1">
          <p class="text-xs font-medium uppercase tracking-wider text-muted-foreground">AutoApply</p>
          <h2 class="flex items-center gap-2 text-lg font-semibold tracking-tight text-foreground">
            <Wand2 class="h-4 w-4 text-muted-foreground" />
            Materials Workspace
          </h2>
          <p class="text-sm text-muted-foreground">
            Generate tailored resumes and cover letters from a saved profile and a job posting.
          </p>
        </div>
        <RouterLink
          to="/materials/templates"
          class="inline-flex items-center gap-2 rounded-md border border-input bg-background px-3 py-1.5 text-sm font-medium text-foreground ring-offset-background transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <Library class="h-4 w-4" />
          Manage templates
        </RouterLink>
      </CardContent>
    </Card>

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
          Generate
        </CardTitle>
      </CardHeader>
      <CardContent class="space-y-5">
        <!-- Step 1: Source -->
        <section class="space-y-2">
          <header class="flex items-baseline justify-between gap-3">
            <h3 class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              1. Source
            </h3>
          </header>
          <div class="inline-flex rounded-md border border-input bg-muted/40 p-1">
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded-sm px-3 py-1 text-sm font-medium transition-colors"
              :class="
                state.sourceMode === 'job'
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              "
              @click="state.sourceMode = 'job'"
            >
              <Briefcase class="h-4 w-4" />
              Search result
            </button>
            <button
              type="button"
              class="inline-flex items-center gap-1.5 rounded-sm px-3 py-1 text-sm font-medium transition-colors"
              :class="
                state.sourceMode === 'paste'
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              "
              @click="state.sourceMode = 'paste'"
            >
              <FileText class="h-4 w-4" />
              Paste JD
            </button>
          </div>
        </section>

        <!-- Step 2: Job -->
        <section class="space-y-2">
          <header class="flex items-baseline justify-between gap-3">
            <h3 class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              2. Job
            </h3>
            <button
              v-if="state.jobLocked && jobReady"
              type="button"
              class="text-xs font-medium text-primary hover:underline"
              @click="unlockJob"
            >
              Change
            </button>
          </header>

          <div
            v-if="state.jobLocked && jobReady"
            class="flex flex-wrap items-center gap-2 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm"
          >
            <Badge variant="secondary">{{ state.sourceMode === "job" ? "Search result" : "Pasted JD" }}</Badge>
            <span
              v-for="part in jobSummaryParts(currentJobPayload)"
              :key="part"
              class="text-muted-foreground"
            >
              {{ part }}
            </span>
          </div>

          <template v-else>
            <div v-if="state.sourceMode === 'job'" class="space-y-2">
              <AppSelect
                v-model="state.selectedJobId"
                :options="jobOptions"
                aria-label="Select search result"
              />
              <p class="text-xs text-muted-foreground">
                {{
                  selectedJob
                    ? jobSummaryParts(selectedJob).join(" · ")
                    : "Pick a job from the latest search results in the Jobs page."
                }}
              </p>
              <Button
                v-if="jobReady"
                variant="ghost"
                size="sm"
                type="button"
                @click="lockJob"
              >
                Use this job
              </Button>
            </div>

            <div v-else class="grid gap-3 md:grid-cols-2">
              <label class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Company</span>
                <Input v-model="state.customJob.company" placeholder="Company" />
              </label>
              <label class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Role</span>
                <Input v-model="state.customJob.title" placeholder="Software Engineer Intern" />
              </label>
              <label class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Location</span>
                <Input v-model="state.customJob.location" placeholder="Vancouver, BC" />
              </label>
              <label class="space-y-1.5">
                <span class="text-xs font-medium text-muted-foreground">Apply URL</span>
                <Input v-model="state.customJob.application_url" type="url" placeholder="https://..." />
              </label>
              <label class="space-y-1.5 md:col-span-2">
                <span class="text-xs font-medium text-muted-foreground">Job description</span>
                <textarea
                  v-model="state.customJob.description"
                  class="min-h-[8rem] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                  placeholder="Paste the full JD here."
                ></textarea>
              </label>
              <Button
                v-if="jobReady"
                variant="ghost"
                size="sm"
                type="button"
                class="md:col-span-2"
                @click="lockJob"
              >
                Use this job description
              </Button>
            </div>
          </template>
        </section>

        <!-- Step 3: Applicant -->
        <section class="space-y-2">
          <header>
            <h3 class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              3. Applicant
            </h3>
          </header>
          <AppSelect
            v-model="state.profileId"
            :options="profileOptions"
            aria-label="Select applicant"
          />
          <p v-if="selectedProfile" class="flex items-center gap-1.5 text-xs text-muted-foreground">
            <UserCircle class="h-3.5 w-3.5" />
            {{ selectedProfile.name || selectedProfile.id }}
          </p>
        </section>

        <!-- Step 4: Materials -->
        <section class="space-y-2">
          <header class="flex items-baseline justify-between gap-3">
            <h3 class="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              4. Materials
            </h3>
            <p class="text-xs text-muted-foreground">Click to expand template &amp; format settings.</p>
          </header>

          <div class="space-y-2">
            <article
              v-for="target in targets"
              :key="target.id"
              class="rounded-md border border-border bg-card transition-colors"
              :class="state.selectedMaterials[target.id] ? '' : 'opacity-60'"
            >
              <header class="flex items-center gap-3 px-4 py-3">
                <label class="inline-flex items-center gap-2">
                  <input
                    type="checkbox"
                    class="h-4 w-4 rounded border-input accent-primary"
                    :checked="state.selectedMaterials[target.id]"
                    @change="toggleMaterialSelected(target.id)"
                  />
                  <span class="text-sm font-medium text-foreground">{{ target.label }}</span>
                </label>
                <span class="ml-auto text-xs text-muted-foreground">
                  {{ selectedTemplateLabel(target.templateType) }}
                </span>
                <button
                  type="button"
                  class="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  :aria-expanded="state.expandedMaterial[target.id]"
                  :aria-label="`Toggle ${target.label} settings`"
                  @click="toggleMaterialExpanded(target.id)"
                >
                  <component
                    :is="state.expandedMaterial[target.id] ? ChevronDown : ChevronRight"
                    class="h-4 w-4"
                  />
                </button>
              </header>

              <div
                v-if="state.expandedMaterial[target.id]"
                class="space-y-3 border-t border-border px-4 py-3"
              >
                <label class="grid gap-1.5">
                  <span class="text-xs font-medium text-muted-foreground">Template</span>
                  <AppSelect
                    v-model="state.templateIds[target.templateType]"
                    :options="
                      target.id === 'resume' ? resumeTemplateOptions : coverLetterTemplateOptions
                    "
                    :aria-label="`${target.label} template`"
                    :disabled="!state.selectedMaterials[target.id]"
                  />
                </label>

                <fieldset class="grid gap-1.5">
                  <legend class="text-xs font-medium text-muted-foreground">Output formats</legend>
                  <div class="flex flex-wrap gap-3">
                    <label
                      v-for="format in availableFormatOptions(target.id)"
                      :key="format.type"
                      class="inline-flex items-center gap-1.5 text-sm text-foreground"
                    >
                      <input
                        v-model="state.selectedFormats[format.type]"
                        type="checkbox"
                        class="h-4 w-4 rounded border-input accent-primary"
                        :disabled="!state.selectedMaterials[target.id]"
                      />
                      {{ format.label }}
                    </label>
                  </div>
                </fieldset>
              </div>
            </article>
          </div>
        </section>

        <!-- Generate button -->
        <div class="flex flex-wrap items-center gap-3 pt-2">
          <Button type="button" :disabled="state.generating || !canGenerate" @click="generateMaterials">
            <Sparkles class="h-4 w-4" />
            {{ state.generating ? "Generating..." : "Generate materials" }}
          </Button>
          <p v-if="!canGenerate" class="flex items-center gap-1 text-xs text-muted-foreground">
            <Info class="h-3.5 w-3.5" />
            Select a job, applicant, and at least one material with a format.
          </p>
        </div>
      </CardContent>
    </Card>

    <!-- Preview area -->
    <Card>
      <CardHeader class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div class="space-y-1">
          <CardTitle class="flex items-center gap-2 text-sm">
            <FileText class="h-4 w-4 text-muted-foreground" />
            Preview
          </CardTitle>
          <p class="text-xs text-muted-foreground">
            {{
              currentJobPayload
                ? jobSummaryParts(currentJobPayload).join(" · ")
                : "Choose a job or paste a JD above."
            }}
          </p>
        </div>
        <div v-if="reviewEntries.length" class="inline-flex rounded-md border border-input bg-muted/40 p-1">
          <button
            v-for="tab in previewTabs"
            :key="tab.id"
            type="button"
            class="inline-flex items-center gap-1.5 rounded-sm px-3 py-1 text-sm font-medium transition-colors"
            :class="[
              state.activePreviewTab === tab.id
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
              tab.available ? '' : 'opacity-40',
            ]"
            :disabled="!tab.available"
            @click="selectPreviewTab(tab.id)"
          >
            {{ tab.label }}
          </button>
        </div>
      </CardHeader>
      <CardContent>
        <EmptyState
          v-if="!reviewEntries.length"
          title="No materials generated yet"
          description="Pick a job, applicant, and template above. Generated previews and download links will appear here."
        >
          <template #icon><FileText /></template>
          <template #action>
            <Button
              type="button"
              size="sm"
              :disabled="state.generating || !canGenerate"
              @click="generateMaterials"
            >
              <Sparkles class="h-4 w-4" />
              Generate materials
            </Button>
          </template>
        </EmptyState>

        <section v-else-if="activePreviewEntry" class="space-y-4">
          <header class="flex items-start justify-between gap-3">
            <div class="space-y-1">
              <p class="text-xs text-muted-foreground">
                {{
                  activePreviewEntry.result.template?.name ||
                  activePreviewEntry.result.template?.template_id ||
                  "Template"
                }}
              </p>
              <h3 class="text-base font-semibold text-foreground">{{ activePreviewEntry.label }}</h3>
            </div>
            <Button
              variant="ghost"
              size="sm"
              type="button"
              @click="togglePreview(activePreviewEntry.id)"
            >
              {{ state.previewExpanded[activePreviewEntry.id] ? "Collapse preview" : "Expand preview" }}
            </Button>
          </header>

          <div class="flex flex-wrap items-center gap-1.5">
            <Badge v-if="activePreviewEntry.result.version?.id" variant="outline">
              Version {{ activePreviewEntry.result.version.id.slice(0, 8) }}
            </Badge>
            <Badge
              v-if="activePreviewEntry.result.validation"
              :variant="activePreviewEntry.result.validation.ok ? 'success' : 'warning'"
            >
              {{ activePreviewEntry.result.validation.ok ? "Validation OK" : "Needs review" }}
            </Badge>
            <Badge v-if="validationMetrics(activePreviewEntry.result).pdf_page_count" variant="secondary">
              {{ validationMetrics(activePreviewEntry.result).pdf_page_count }} PDF page(s)
            </Badge>
            <Badge v-if="validationMetrics(activePreviewEntry.result).coverage_ratio" variant="secondary">
              {{ Math.round(validationMetrics(activePreviewEntry.result).coverage_ratio * 100) }}% keyword coverage
            </Badge>
          </div>

          <div class="space-y-2 rounded-md border border-border bg-muted/30 p-3">
            <p class="text-xs font-medium text-muted-foreground">Generated files</p>
            <div
              v-if="artifactEntries(activePreviewEntry.result, activePreviewEntry.id).length"
              class="flex flex-wrap gap-2"
            >
              <a
                v-for="artifact in artifactEntries(activePreviewEntry.result, activePreviewEntry.id)"
                :key="artifact.type"
                class="inline-flex items-center gap-1.5 rounded-md border border-input bg-background px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted"
                :href="artifactDownloadUrl(artifact.path)"
                target="_blank"
                rel="noopener"
              >
                Download {{ artifact.label }}
              </a>
            </div>
            <p v-else class="text-xs text-muted-foreground">
              No selected download format is available for this material.
            </p>
          </div>

          <div
            v-if="state.previewExpanded[activePreviewEntry.id] && validationIssues(activePreviewEntry.result).length"
            class="space-y-2"
          >
            <div
              v-for="issue in validationIssues(activePreviewEntry.result)"
              :key="`${activePreviewEntry.id}-${issue.type}-${issue.source_id || issue.message}`"
              class="rounded-md border border-border bg-muted/40 p-3"
            >
              <div class="flex items-center gap-2">
                <Badge :variant="issue.severity === 'error' ? 'destructive' : 'warning'">
                  {{ prettyLabel(issue.severity || "warning") }}
                </Badge>
                <strong class="text-sm text-foreground">{{ prettyLabel(issue.type) }}</strong>
              </div>
              <p class="mt-1 text-sm text-muted-foreground">{{ issue.message }}</p>
            </div>
          </div>

          <div
            v-if="
              state.previewExpanded[activePreviewEntry.id] &&
              activePreviewEntry.result.document?.document_type === 'resume'
            "
            class="space-y-4"
          >
            <div v-if="activePreviewEntry.result.document.summary?.length" class="space-y-1">
              <strong class="text-sm text-foreground">Summary</strong>
              <p
                v-for="line in activePreviewEntry.result.document.summary"
                :key="line"
                class="text-sm text-muted-foreground"
              >
                {{ line }}
              </p>
            </div>

            <div v-if="activePreviewEntry.result.document.skills" class="space-y-1">
              <strong class="text-sm text-foreground">Skills</strong>
              <div class="flex flex-wrap gap-1.5">
                <template
                  v-for="(items, category) in activePreviewEntry.result.document.skills"
                  :key="category"
                >
                  <Badge
                    v-for="skill in items"
                    :key="`${category}-${skill}`"
                    variant="secondary"
                  >
                    {{ skill }}
                  </Badge>
                </template>
              </div>
            </div>

            <div
              v-for="item in resumePreviewItems(activePreviewEntry.result.document)"
              :key="item.source_id"
              class="space-y-2"
            >
              <header class="flex items-baseline justify-between gap-2">
                <strong class="text-sm text-foreground">{{ item.section }} · {{ item.name }}</strong>
                <span class="text-xs text-muted-foreground">{{ item.title || item.meta }}</span>
              </header>
              <div
                v-for="bullet in item.bullets"
                :key="bullet.source_id"
                class="space-y-1 rounded-md border border-border bg-card px-3 py-2"
              >
                <p class="text-sm text-foreground">{{ bullet.text }}</p>
                <div class="flex flex-wrap gap-1.5">
                  <Badge variant="secondary">{{ bullet.source_entity }}</Badge>
                  <Badge v-if="bullet.score" variant="secondary">
                    score {{ Number(bullet.score).toFixed(1) }}
                  </Badge>
                  <Badge
                    v-for="keyword in bullet.matched_keywords"
                    :key="`${bullet.source_id}-${keyword}`"
                  >
                    {{ keyword }}
                  </Badge>
                </div>
              </div>
            </div>
          </div>

          <div
            v-else-if="state.previewExpanded[activePreviewEntry.id]"
            class="space-y-4"
          >
            <div
              v-for="paragraph in coverParagraphs(activePreviewEntry.result.document)"
              :key="paragraph.text"
              class="space-y-1"
            >
              <p class="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                {{ prettyLabel(paragraph.type) }}
              </p>
              <p class="text-sm text-foreground">{{ paragraph.text }}</p>
            </div>
          </div>
        </section>
      </CardContent>
    </Card>
  </div>
</template>
