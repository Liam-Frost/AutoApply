<script setup>
import { computed, onMounted, reactive, watch } from "vue"
import { useRoute } from "vue-router"
import {
  FileText,
  FolderCog,
  Library,
  Sparkles,
  Wand2,
  X,
} from "lucide-vue-next"

import AppSelect from "@/components/AppSelect.vue"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { api } from "@/lib/api"
import { jobsState } from "@/lib/jobs-state"

const route = useRoute()

const targets = [
  { id: "resume", label: "Resume", materialType: "resume_docx", templateType: "resume" },
  {
    id: "cover_letter",
    label: "Cover Letter",
    materialType: "cover_letter_docx",
    templateType: "cover_letter",
  },
]

const outputFormatLabels = {
  docx: "DOCX",
  pdf: "PDF",
  tex: "TEX",
}

const materialLabels = {
  resume_docx: "Resume DOCX",
  resume_pdf: "Resume PDF",
  resume_tex: "Resume TEX",
  cover_letter_docx: "Cover Letter DOCX",
  cover_letter_pdf: "Cover Letter PDF",
  cover_letter_tex: "Cover Letter TEX",
}

const state = reactive({
  loading: true,
  generating: false,
  error: "",
  message: "",
  sourceMode: "job",
  selectedJobId: "",
  profileId: "",
  profiles: [],
  templates: { resume: [], cover_letter: [] },
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
  templateUploads: {
    resume: { file: null, name: "", loading: false, message: "", error: "" },
    cover_letter: { file: null, name: "", loading: false, message: "", error: "" },
  },
  latexCreates: {
    resume: { name: "", loading: false, message: "", error: "" },
    cover_letter: { name: "", loading: false, message: "", error: "" },
  },
  templateEditor: {
    documentType: "",
    templateId: "",
    name: "",
    description: "",
    content: "",
    loading: false,
    saving: false,
    validating: false,
    message: "",
    error: "",
    validation: null,
  },
  templateLibraryOpen: false,
  activePreviewTab: "resume",
  previewExpanded: {},
  customJob: {
    company: "",
    title: "",
    location: "",
    application_url: "",
    description: "",
  },
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

const selectedJob = computed(() => allJobs.value.find((job) => job.id === state.selectedJobId) || null)
const profileOptions = computed(() => [
  { value: "", label: state.profiles.length ? "Select applicant" : "No saved applicants" },
  ...state.profiles.map((profile) => ({ value: profile.id, label: profile.name || profile.id })),
])

const resumeTemplateOptions = computed(() => templateOptions("resume"))
const coverLetterTemplateOptions = computed(() => templateOptions("cover_letter"))
const selectedTargets = computed(() =>
  targets.filter((target) => state.selectedMaterials[target.id] && selectedFormatTypes(target.id).length),
)
const canGenerate = computed(
  () => Boolean(state.profileId) && Boolean(currentJobPayload.value) && selectedTargets.value.length > 0,
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
  () => reviewEntries.value.find((entry) => entry.id === state.activePreviewTab) || reviewEntries.value[0] || null,
)

onMounted(async () => {
  await Promise.all([loadProfiles(), loadTemplates()])
  applyRouteJob()
  state.loading = false
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

async function loadProfiles() {
  const response = await api.profile()
  state.profiles = response.profiles || []
  state.profileId = response.active_profile_id || state.profiles[0]?.id || ""
}

async function loadTemplates() {
  const response = await api.templates()
  state.templates = {
    resume: response.templates?.resume || [],
    cover_letter: response.templates?.cover_letter || [],
  }
  state.templateIds.resume = state.templates.resume[0]?.template_id || ""
  state.templateIds.cover_letter = state.templates.cover_letter[0]?.template_id || ""
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
        .generateJobMaterial(job, primaryMaterialType(target), state.templateIds[target.templateType], state.profileId)
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

function onTemplateFileChange(documentType, event) {
  state.templateUploads[documentType].file = event.target.files?.[0] || null
  state.templateUploads[documentType].message = ""
  state.templateUploads[documentType].error = ""
}

async function uploadTemplate(documentType) {
  const upload = state.templateUploads[documentType]
  if (!upload.file) {
    upload.error = "Choose a .docx or .tex template first."
    return
  }
  upload.loading = true
  upload.error = ""
  upload.message = ""
  try {
    const response = await api.uploadTemplate(documentType, upload.file, upload.name)
    applyTemplateResponse(response)
    state.templateIds[documentType] = response.template?.template_id || state.templateIds[documentType]
    syncSelectedFormats(documentType)
    upload.file = null
    upload.name = ""
    upload.message = "Uploaded template."
  } catch (error) {
    upload.error = error.message
  } finally {
    upload.loading = false
  }
}

async function createLatexTemplate(documentType) {
  const creator = state.latexCreates[documentType]
  creator.loading = true
  creator.error = ""
  creator.message = ""
  try {
    const response = await api.createLatexTemplate(documentType, creator.name)
    applyTemplateResponse(response)
    state.templateIds[documentType] = response.template?.template_id || state.templateIds[documentType]
    creator.name = ""
    creator.message = "Created LaTeX template."
    syncSelectedFormats(documentType)
    if (response.template?.template_id) {
      await editTemplate(documentType, response.template.template_id)
    }
  } catch (error) {
    creator.error = error.message
  } finally {
    creator.loading = false
  }
}

async function editTemplate(documentType, templateId) {
  Object.assign(state.templateEditor, {
    documentType,
    templateId,
    name: "",
    description: "",
    content: "",
    loading: true,
    saving: false,
    validating: false,
    message: "",
    error: "",
    validation: null,
  })
  try {
    const response = await api.templateDetail(documentType, templateId)
    const template = response.template || {}
    Object.assign(state.templateEditor, {
      name: template.name || template.template_id || "",
      description: template.description || "",
      content: template.content || "",
      validation: template.validation || null,
    })
  } catch (error) {
    state.templateEditor.error = error.message
  } finally {
    state.templateEditor.loading = false
  }
}

async function saveTemplateEditor() {
  const editor = state.templateEditor
  if (!editor.documentType || !editor.templateId) {
    return
  }
  editor.saving = true
  editor.error = ""
  editor.message = ""
  try {
    const response = await api.updateTemplate(editor.documentType, editor.templateId, {
      template_name: editor.name,
      description: editor.description,
      content: editor.content,
    })
    applyTemplateResponse(response)
    editor.validation = response.template?.validation || null
    editor.message = "Saved template."
  } catch (error) {
    editor.error = error.message
  } finally {
    editor.saving = false
  }
}

async function validateTemplateEditor() {
  const editor = state.templateEditor
  if (!editor.documentType || !editor.templateId) {
    return
  }
  editor.validating = true
  editor.error = ""
  editor.message = ""
  try {
    const response = await api.validateTemplate(editor.documentType, editor.templateId)
    editor.validation = response.validation || response.template?.validation || null
    applyTemplateResponse(response)
    editor.message = editor.validation?.ok ? "Template validated." : "Template needs review."
  } catch (error) {
    editor.error = error.message
  } finally {
    editor.validating = false
  }
}

function closeTemplateEditor() {
  Object.assign(state.templateEditor, {
    documentType: "",
    templateId: "",
    name: "",
    description: "",
    content: "",
    loading: false,
    saving: false,
    validating: false,
    message: "",
    error: "",
    validation: null,
  })
}

function togglePreview(targetId) {
  state.previewExpanded[targetId] = !state.previewExpanded[targetId]
}

function openTemplateLibrary() {
  state.templateLibraryOpen = true
}

function closeTemplateLibrary() {
  state.templateLibraryOpen = false
}

function selectPreviewTab(targetId) {
  if (!state.results[targetId]?.document) {
    return
  }
  state.activePreviewTab = targetId
}

function selectedTemplate(documentType) {
  return (state.templates[documentType] || []).find(
    (template) => template.template_id === state.templateIds[documentType],
  )
}

function templateDescription(documentType) {
  const template = selectedTemplate(documentType)
  const outputs = templateSupportedOutputs(template).map((output) => outputFormatLabels[output] || output).join("/")
  const renderer = templateRenderer(template) === "latex" ? "LaTeX" : "DOCX"
  return template
    ? `${template.description || "Template capacity is read from manifest.json."} Renderer: ${renderer}. Outputs: ${outputs}.`
    : "Template styles and capacity are read from manifest.json."
}

function jobSummary(job) {
  if (!job) {
    return "Choose a search result or paste a job description."
  }
  return [job.company, job.title, job.location].filter(Boolean).join(" · ")
}

function templateOptions(documentType) {
  const templates = state.templates[documentType] || []
  if (!templates.length) {
    return [{ value: "", label: "Default template" }]
  }
  return templates.map((template) => ({
    value: template.template_id,
    label: `${template.name || template.template_id} · ${templateRenderer(template) === "latex" ? "LaTeX" : "DOCX"}`,
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
  return templateSupportedOutputs(selectedTemplate(target.templateType)).map((output) => ({
    type: materialTypeForOutput(target.templateType, output),
    label: outputFormatLabels[output] || output.toUpperCase(),
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

function templateSupportedOutputs(template) {
  const outputs = template?.supported_outputs || template?.manifest?.supported_outputs
  if (Array.isArray(outputs) && outputs.length) {
    return outputs.filter((output) => ["docx", "pdf", "tex"].includes(output))
  }
  return ["docx", "pdf"]
}

function templateRenderer(template) {
  return template?.renderer || template?.manifest?.renderer || "docx"
}

function isLatexTemplate(template) {
  return templateRenderer(template) === "latex"
}

function materialTypeForOutput(documentType, output) {
  const prefix = documentType === "cover_letter" ? "cover_letter" : "resume"
  return `${prefix}_${output}`
}

function applyTemplateResponse(response) {
  state.templates = {
    resume: response.templates?.resume || state.templates.resume,
    cover_letter: response.templates?.cover_letter || state.templates.cover_letter,
  }
}

function primaryMaterialType(target) {
  return selectedFormatTypes(target.id)[0] || target.materialType
}

function artifactEntries(result, targetId) {
  const selected = new Set(selectedFormatTypes(targetId))
  return Object.entries(result?.artifacts || {})
    .filter(([type, path]) => selected.has(type) && Boolean(path))
    .map(([type, path]) => ({ type, path, label: materialLabels[type] || type }))
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
</script>

<template>
  <div class="materials-page">
    <Card>
      <CardContent class="flex flex-col items-start justify-between gap-3 p-5 md:flex-row md:items-center">
        <div class="space-y-1">
          <p class="text-xs font-medium uppercase tracking-wider text-muted-foreground">AutoApply</p>
          <h2 class="text-lg font-semibold tracking-tight text-foreground">Materials Workspace</h2>
          <p class="text-sm text-muted-foreground">Generate tailored resumes and cover letters from a saved applicant profile and job description.</p>
        </div>
        <Button variant="ghost" size="sm" type="button" @click="openTemplateLibrary">
          <Library class="h-4 w-4" />
          Template Library
        </Button>
      </CardContent>
    </Card>

    <div class="materials-workspace">
      <Card class="materials-setup-panel">
        <CardHeader>
          <CardTitle class="flex items-center gap-2 text-sm">
            <Wand2 class="h-4 w-4 text-muted-foreground" />
            Generate
          </CardTitle>
          <p class="text-xs text-muted-foreground">Configure the job, applicant, materials, and output formats.</p>
        </CardHeader>
        <CardContent class="space-y-4">

        <div class="materials-step">
          <div class="materials-step-title">1. Source</div>
          <div class="materials-mode-row">
            <label class="toggle-pill">
              <input v-model="state.sourceMode" type="radio" value="job" />
              <span>Search Result</span>
            </label>
            <label class="toggle-pill">
              <input v-model="state.sourceMode" type="radio" value="paste" />
              <span>Paste JD</span>
            </label>
          </div>
        </div>

        <div class="materials-step">
          <div class="materials-step-title">2. Job</div>
          <div v-if="state.sourceMode === 'job'" class="materials-selector-stack">
            <AppSelect v-model="state.selectedJobId" :options="jobOptions" aria-label="Select search result" />
            <div class="materials-selected-card">
              <strong>{{ selectedJob?.company || 'No job selected' }}</strong>
              <span>{{ selectedJob?.title || 'Choose a job from the latest search results.' }}</span>
              <small>{{ selectedJob?.location || 'Search results are loaded from the Jobs page.' }}</small>
            </div>
          </div>

          <div v-else class="form-grid materials-jd-grid">
            <label class="field">
              <span>Company</span>
              <input v-model="state.customJob.company" class="input" type="text" placeholder="Company" />
            </label>
            <label class="field">
              <span>Role</span>
              <input v-model="state.customJob.title" class="input" type="text" placeholder="Software Engineer Intern" />
            </label>
            <label class="field">
              <span>Location</span>
              <input v-model="state.customJob.location" class="input" type="text" placeholder="Vancouver, BC" />
            </label>
            <label class="field">
              <span>Apply URL</span>
              <input v-model="state.customJob.application_url" class="input" type="url" placeholder="https://..." />
            </label>
            <label class="field field-span-full">
              <span>Job Description</span>
              <textarea v-model="state.customJob.description" class="input textarea materials-jd-textarea" placeholder="Paste the full JD here."></textarea>
            </label>
          </div>
        </div>

        <div class="materials-step">
          <div class="materials-step-title">3. Applicant</div>
          <AppSelect v-model="state.profileId" :options="profileOptions" aria-label="Select applicant" />
        </div>

        <div class="materials-step">
          <div class="materials-step-title">4. Materials</div>
          <div class="materials-card-stack">
            <article v-for="target in targets" :key="target.id" class="materials-choice-card" :class="{ 'is-disabled': !state.selectedMaterials[target.id] }">
              <div class="materials-choice-head">
                <label class="materials-generate-check">
                  <input v-model="state.selectedMaterials[target.id]" type="checkbox" />
                  <span>{{ target.label }}</span>
                </label>
                <div class="materials-format-row">
                  <label v-for="format in availableFormatOptions(target.id)" :key="format.type" class="materials-format-check">
                    <input v-model="state.selectedFormats[format.type]" type="checkbox" :disabled="!state.selectedMaterials[target.id]" />
                    <span>{{ format.label }}</span>
                  </label>
                </div>
              </div>

              <div class="materials-template-row">
                <div class="field">
                  <span>{{ target.label }} Template</span>
                  <AppSelect
                    v-model="state.templateIds[target.templateType]"
                    :options="target.id === 'resume' ? resumeTemplateOptions : coverLetterTemplateOptions"
                    :aria-label="`${target.label} template`"
                    :disabled="!state.selectedMaterials[target.id]"
                  />
                </div>
                <Button variant="ghost" size="sm" type="button" @click="openTemplateLibrary">
                  <FolderCog class="h-4 w-4" />
                  Manage
                </Button>
              </div>
              <p class="text-xs text-muted-foreground">{{ templateDescription(target.templateType) }}</p>
            </article>
          </div>
        </div>

        <div class="materials-actions">
          <Button type="button" :disabled="state.generating || !canGenerate" @click="generateMaterials">
            <Sparkles class="h-4 w-4" />
            {{ state.generating ? "Generating..." : "Generate Materials" }}
          </Button>
          <span v-if="state.message" class="inline-feedback review">{{ state.message }}</span>
          <span v-if="state.error" class="inline-feedback error">{{ state.error }}</span>
        </div>
        </CardContent>
      </Card>

      <Card class="materials-preview-workbench">
        <CardHeader class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
          <div class="space-y-1">
            <CardTitle class="flex items-center gap-2 text-sm">
              <FileText class="h-4 w-4 text-muted-foreground" />
              Preview
            </CardTitle>
            <p class="text-xs text-muted-foreground">{{ jobSummary(currentJobPayload) }}</p>
          </div>
          <div class="materials-preview-tabs">
            <button
              v-for="tab in previewTabs"
              :key="tab.id"
              class="materials-preview-tab"
              :class="{ 'is-active': state.activePreviewTab === tab.id, 'is-empty': !tab.available }"
              type="button"
              @click="selectPreviewTab(tab.id)"
            >
              {{ tab.label }}
            </button>
          </div>
        </CardHeader>
        <CardContent class="space-y-4">

        <EmptyState
          v-if="!reviewEntries.length"
          title="No materials generated yet"
          description="Choose a job, applicant, templates, and output formats. Your previews, status, and downloads will appear here."
        >
          <template #icon><FileText /></template>
          <template #action>
            <Button type="button" size="sm" :disabled="state.generating || !canGenerate" @click="generateMaterials">
              <Sparkles class="h-4 w-4" />
              Generate Materials
            </Button>
          </template>
        </EmptyState>

        <section v-else-if="activePreviewEntry" class="materials-result-workbench">
          <div class="materials-result-summary">
            <div>
              <div class="muted-inline">{{ activePreviewEntry.result.template?.name || activePreviewEntry.result.template?.template_id || 'Template' }}</div>
              <h3>{{ activePreviewEntry.label }}</h3>
            </div>
            <button class="button ghost compact" type="button" @click="togglePreview(activePreviewEntry.id)">
              {{ state.previewExpanded[activePreviewEntry.id] ? "Collapse Preview" : "Expand Preview" }}
            </button>
          </div>

          <div class="chip-row">
            <span v-if="activePreviewEntry.result.version?.id" class="chip subtle">Version {{ activePreviewEntry.result.version.id.slice(0, 8) }}</span>
            <span v-if="activePreviewEntry.result.validation" class="chip" :class="activePreviewEntry.result.validation.ok ? 'success' : 'danger'">
              {{ activePreviewEntry.result.validation.ok ? 'Validation OK' : 'Needs Review' }}
            </span>
            <span v-if="validationMetrics(activePreviewEntry.result).pdf_page_count" class="chip subtle">
              {{ validationMetrics(activePreviewEntry.result).pdf_page_count }} PDF page(s)
            </span>
            <span v-if="validationMetrics(activePreviewEntry.result).coverage_ratio" class="chip subtle">
              {{ Math.round(validationMetrics(activePreviewEntry.result).coverage_ratio * 100) }}% keyword coverage
            </span>
          </div>

          <div class="materials-downloads-card">
            <strong>Generated files</strong>
            <div v-if="artifactEntries(activePreviewEntry.result, activePreviewEntry.id).length" class="material-download-row">
              <a
                v-for="artifact in artifactEntries(activePreviewEntry.result, activePreviewEntry.id)"
                :key="artifact.type"
                class="button ghost compact"
                :href="artifactDownloadUrl(artifact.path)"
                target="_blank"
                rel="noopener"
              >
                Download {{ artifact.label }}
              </a>
            </div>
            <span v-else class="muted-inline">No selected download format is available for this material.</span>
          </div>

          <div v-if="!state.previewExpanded[activePreviewEntry.id]" class="materials-collapsed-preview">
            Preview is collapsed by default. Expand it when you are ready to review the generated content.
          </div>

          <div v-if="state.previewExpanded[activePreviewEntry.id] && validationIssues(activePreviewEntry.result).length" class="material-review-issues">
            <div v-for="issue in validationIssues(activePreviewEntry.result)" :key="`${activePreviewEntry.id}-${issue.type}-${issue.source_id || issue.message}`" class="material-issue" :class="issue.severity">
              <strong>{{ prettyLabel(issue.type) }}</strong>
              <span>{{ issue.message }}</span>
            </div>
          </div>

          <div v-if="state.previewExpanded[activePreviewEntry.id] && activePreviewEntry.result.document?.document_type === 'resume'" class="material-preview-body materials-document-canvas">
            <div v-if="activePreviewEntry.result.document.summary?.length" class="material-preview-section">
              <strong>Summary</strong>
              <p v-for="line in activePreviewEntry.result.document.summary" :key="line">{{ line }}</p>
            </div>
            <div v-if="activePreviewEntry.result.document.skills" class="material-preview-section">
              <strong>Skills</strong>
              <div class="chip-row">
                <template v-for="(items, category) in activePreviewEntry.result.document.skills" :key="category">
                  <span v-for="skill in items" :key="`${category}-${skill}`" class="chip subtle">{{ skill }}</span>
                </template>
              </div>
            </div>
            <div v-for="item in resumePreviewItems(activePreviewEntry.result.document)" :key="item.source_id" class="material-preview-section">
              <div class="material-preview-item-head">
                <strong>{{ item.section }} · {{ item.name }}</strong>
                <span class="muted">{{ item.title || item.meta }}</span>
              </div>
              <div v-for="bullet in item.bullets" :key="bullet.source_id" class="material-bullet-preview">
                <div>{{ bullet.text }}</div>
                <div class="chip-row material-bullet-meta">
                  <span class="chip subtle">{{ bullet.source_entity }}</span>
                  <span v-if="bullet.score" class="chip subtle">score {{ Number(bullet.score).toFixed(1) }}</span>
                  <span v-for="keyword in bullet.matched_keywords" :key="`${bullet.source_id}-${keyword}`" class="chip">{{ keyword }}</span>
                </div>
              </div>
            </div>
          </div>

          <div v-else-if="state.previewExpanded[activePreviewEntry.id]" class="material-preview-body materials-document-canvas">
            <div v-for="paragraph in coverParagraphs(activePreviewEntry.result.document)" :key="paragraph.text" class="material-preview-section">
              <div class="muted-inline">{{ prettyLabel(paragraph.type) }}</div>
              <p>{{ paragraph.text }}</p>
            </div>
          </div>
        </section>
        </CardContent>
      </Card>
    </div>

    <div v-if="state.templateLibraryOpen" class="material-modal-backdrop" @click.self="closeTemplateLibrary">
      <section class="material-modal materials-library-modal" role="dialog" aria-modal="true" aria-label="Template Library">
        <div class="material-modal-head">
          <div>
            <div class="muted-inline">Template Library</div>
            <h3>Manage Templates</h3>
            <p>Upload DOCX templates or create, edit, and validate single-file LaTeX templates.</p>
          </div>
          <Button variant="ghost" size="icon" type="button" aria-label="Close template library" @click="closeTemplateLibrary">
            <X class="h-4 w-4" />
          </Button>
        </div>

        <div class="materials-library-grid">
          <section v-for="target in targets" :key="target.templateType" class="materials-library-section">
            <div class="section-head">
              <div>
                <h2>{{ target.label }} Templates</h2>
                <p class="muted-inline">Current templates, DOCX upload, and editable LaTeX.</p>
              </div>
            </div>

            <div class="materials-template-list">
              <div v-for="template in state.templates[target.templateType]" :key="template.template_id" class="materials-template-card">
                <div class="materials-template-card-head">
                  <strong>{{ template.name || template.template_id }}</strong>
                  <button
                    v-if="isLatexTemplate(template)"
                    class="button ghost compact"
                    type="button"
                    @click="editTemplate(target.templateType, template.template_id)"
                  >
                    Edit
                  </button>
                </div>
                <div class="materials-template-meta">
                  <span class="chip subtle">{{ templateRenderer(template) === 'latex' ? 'LaTeX' : 'DOCX' }}</span>
                  <span v-for="output in templateSupportedOutputs(template)" :key="`${template.template_id}-${output}`" class="chip subtle">
                    {{ outputFormatLabels[output] || output.toUpperCase() }}
                  </span>
                </div>
                <span>{{ template.description || 'No description provided.' }}</span>
                <small :class="template.validation?.ok ? 'success-text' : 'danger-text'">
                  {{ template.validation?.ok ? 'Validated' : 'Needs validation' }}
                </small>
              </div>
            </div>

            <div class="materials-upload-box">
              <input v-model="state.templateUploads[target.templateType].name" class="input" type="text" placeholder="Template name" />
              <label class="materials-upload-zone">
                <input type="file" accept=".docx,.tex" @change="onTemplateFileChange(target.templateType, $event)" />
                <strong>{{ state.templateUploads[target.templateType].file?.name || 'Drop DOCX or TEX here or browse' }}</strong>
                <span>DOCX styles can be repaired. LaTeX marker validation reports issues without rewriting your file.</span>
              </label>
              <button class="button compact" type="button" :disabled="state.templateUploads[target.templateType].loading" @click="uploadTemplate(target.templateType)">
                {{ state.templateUploads[target.templateType].loading ? 'Uploading...' : `Upload ${target.label} Template` }}
              </button>
              <span v-if="state.templateUploads[target.templateType].message" class="inline-feedback review">{{ state.templateUploads[target.templateType].message }}</span>
              <span v-if="state.templateUploads[target.templateType].error" class="inline-feedback error">{{ state.templateUploads[target.templateType].error }}</span>
            </div>

            <div class="materials-latex-create">
              <input v-model="state.latexCreates[target.templateType].name" class="input" type="text" :placeholder="`New ${target.label} LaTeX template name`" />
              <button class="button ghost compact" type="button" :disabled="state.latexCreates[target.templateType].loading" @click="createLatexTemplate(target.templateType)">
                {{ state.latexCreates[target.templateType].loading ? 'Creating...' : 'Create LaTeX Template' }}
              </button>
              <span v-if="state.latexCreates[target.templateType].message" class="inline-feedback review">{{ state.latexCreates[target.templateType].message }}</span>
              <span v-if="state.latexCreates[target.templateType].error" class="inline-feedback error">{{ state.latexCreates[target.templateType].error }}</span>
            </div>
          </section>
        </div>

        <section v-if="state.templateEditor.templateId" class="materials-template-editor">
          <div class="section-head">
            <div>
              <h2>Edit LaTeX Template</h2>
              <p class="muted-inline">{{ state.templateEditor.documentType === 'resume' ? 'Resume' : 'Cover Letter' }} · {{ state.templateEditor.templateId }}</p>
            </div>
            <button class="button ghost compact" type="button" @click="closeTemplateEditor">Close</button>
          </div>

          <div v-if="state.templateEditor.loading" class="muted-inline">Loading template...</div>
          <template v-else>
            <div class="form-grid materials-editor-grid">
              <label class="field">
                <span>Name</span>
                <input v-model="state.templateEditor.name" class="input" type="text" />
              </label>
              <label class="field">
                <span>Description</span>
                <input v-model="state.templateEditor.description" class="input" type="text" />
              </label>
              <label class="field field-span-full">
                <span>template.tex</span>
                <textarea v-model="state.templateEditor.content" class="input textarea code-textarea materials-code-editor" spellcheck="false"></textarea>
              </label>
            </div>

            <div class="materials-editor-actions">
              <button class="button compact" type="button" :disabled="state.templateEditor.saving" @click="saveTemplateEditor">
                {{ state.templateEditor.saving ? 'Saving...' : 'Save Template' }}
              </button>
              <button class="button ghost compact" type="button" :disabled="state.templateEditor.validating" @click="validateTemplateEditor">
                {{ state.templateEditor.validating ? 'Validating...' : 'Validate' }}
              </button>
              <span v-if="state.templateEditor.message" class="inline-feedback review">{{ state.templateEditor.message }}</span>
              <span v-if="state.templateEditor.error" class="inline-feedback error">{{ state.templateEditor.error }}</span>
            </div>

            <div v-if="state.templateEditor.validation" class="materials-validation-list">
              <span :class="state.templateEditor.validation.ok ? 'success-text' : 'danger-text'">
                {{ state.templateEditor.validation.ok ? 'Validation OK' : 'Validation Issues' }}
              </span>
              <div v-for="issue in state.templateEditor.validation.issues" :key="`${issue.type}-${issue.message}`" class="material-issue" :class="issue.severity || 'warning'">
                <strong>{{ prettyLabel(issue.type) }}</strong>
                <span>{{ issue.message }}</span>
              </div>
            </div>
          </template>
        </section>
      </section>
    </div>
  </div>
</template>
