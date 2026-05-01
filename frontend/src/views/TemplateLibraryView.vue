<script setup>
import { computed, onMounted, reactive, ref } from "vue"
import { RouterLink, useRouter } from "vue-router"
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  FileText,
  Library,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-vue-next"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import {
  applyTemplatesResponse,
  documentTypeLabel,
  isLatexTemplate,
  loadTemplates,
  outputFormatLabel,
  templateRenderer,
  templateSupportedOutputs,
  templatesState,
} from "@/lib/materials-templates"

const router = useRouter()

const targets = [
  { id: "resume", label: "Resume", documentType: "resume" },
  { id: "cover_letter", label: "Cover Letter", documentType: "cover_letter" },
]

// reactive() rather than ref({}) so the (el) => fileInputs[type] = el ref
// callback in the template writes directly to the underlying object. With a
// ref<object> you must write fileInputs.value[type] from the script side
// AND fileInputs.value[type] from the template, but the template's auto-
// unwrapping makes that fragile when the ref binding fires. Going through
// a flat reactive proxy avoids the gotcha.
const fileInputs = reactive({ resume: null, cover_letter: null })

const uploadState = reactive({
  resume: { name: "", file: null, loading: false, message: "", error: "" },
  cover_letter: { name: "", file: null, loading: false, message: "", error: "" },
})

const latexState = reactive({
  resume: { name: "", loading: false, message: "", error: "" },
  cover_letter: { name: "", loading: false, message: "", error: "" },
})

const deleteState = reactive({ loadingKey: "" })

const pageError = ref("")
const pageMessage = ref("")

onMounted(async () => {
  try {
    await loadTemplates()
  } catch (error) {
    pageError.value = error.message
  }
})

function templatesFor(documentType) {
  return templatesState.templates[documentType] || []
}

function onFileChange(documentType, event) {
  const file = event.target.files?.[0] || null
  uploadState[documentType].file = file
  uploadState[documentType].error = ""
  uploadState[documentType].message = ""
}

async function uploadTemplate(documentType) {
  const local = uploadState[documentType]
  if (!local.file) {
    local.error = "Choose a .docx or .tex template first."
    return
  }

  local.loading = true
  local.error = ""
  local.message = ""
  pageMessage.value = ""
  pageError.value = ""

  try {
    const response = await api.uploadTemplate(documentType, local.file, local.name)
    applyTemplatesResponse(response)
    local.message = `Uploaded ${documentTypeLabel(documentType)} template.`
    pageMessage.value = local.message
    local.name = ""
    local.file = null
    // fileInputs is a reactive() proxy (not a ref), so the DOM node lives
    // directly under fileInputs[documentType]. Clearing the value resets
    // the <input type="file"> so re-selecting the same filename fires
    // change again.
    if (fileInputs[documentType]) {
      fileInputs[documentType].value = ""
    }
  } catch (error) {
    local.error = error.message
    pageError.value = error.message
  } finally {
    local.loading = false
  }
}

async function createLatexTemplate(documentType) {
  const local = latexState[documentType]
  local.loading = true
  local.error = ""
  local.message = ""
  pageMessage.value = ""
  pageError.value = ""

  try {
    const response = await api.createLatexTemplate(documentType, local.name)
    applyTemplatesResponse(response)
    const newTemplateId = response.template?.template_id
    local.message = `Created ${documentTypeLabel(documentType)} LaTeX template.`
    pageMessage.value = local.message
    local.name = ""

    if (newTemplateId) {
      router.push(`/materials/templates/${documentType}/${newTemplateId}`)
    }
  } catch (error) {
    local.error = error.message
    pageError.value = error.message
  } finally {
    local.loading = false
  }
}

function editTemplate(documentType, templateId) {
  router.push(`/materials/templates/${documentType}/${templateId}`)
}

function templateDeleteKey(documentType, templateId) {
  return `${documentType}:${templateId}`
}

function isDeleting(documentType, templateId) {
  return deleteState.loadingKey === templateDeleteKey(documentType, templateId)
}

async function deleteTemplate(documentType, template) {
  if (!template || template.is_default) {
    return
  }

  const templateName = template.name || template.template_id
  const confirmed = window.confirm(
    `Delete ${documentTypeLabel(documentType)} template "${templateName}"? This cannot be undone.`,
  )
  if (!confirmed) {
    return
  }

  deleteState.loadingKey = templateDeleteKey(documentType, template.template_id)
  pageError.value = ""
  pageMessage.value = ""

  try {
    const response = await api.deleteTemplate(documentType, template.template_id)
    applyTemplatesResponse(response)
    pageMessage.value = `Deleted ${documentTypeLabel(documentType)} template "${templateName}".`
  } catch (error) {
    pageError.value = error.message
  } finally {
    deleteState.loadingKey = ""
  }
}

const isLoading = computed(() => templatesState.loading && !templatesState.loaded)
</script>

<template>
  <div class="space-y-6">
    <Card>
      <CardContent class="flex flex-col items-start justify-between gap-3 p-5 md:flex-row md:items-center">
        <div class="flex items-center gap-3">
          <RouterLink
            to="/materials"
            class="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Back to Materials"
            title="Back to Materials"
          >
            <ArrowLeft class="h-4 w-4" />
          </RouterLink>
          <div class="space-y-1">
            <p class="text-xs font-medium uppercase tracking-wider text-muted-foreground">Materials</p>
            <h2 class="flex items-center gap-2 text-lg font-semibold tracking-tight text-foreground">
              <Library class="h-4 w-4 text-muted-foreground" />
              Template Library
            </h2>
            <p class="text-sm text-muted-foreground">
              Manage Resume and Cover Letter templates. Upload DOCX or create editable LaTeX templates.
            </p>
          </div>
        </div>
      </CardContent>
    </Card>

    <Alert v-if="pageError" variant="destructive">
      <AlertCircle class="h-4 w-4" />
      <AlertDescription>{{ pageError }}</AlertDescription>
    </Alert>
    <Alert v-if="pageMessage" variant="success">
      <CheckCircle2 class="h-4 w-4" />
      <AlertDescription>{{ pageMessage }}</AlertDescription>
    </Alert>

    <section v-for="target in targets" :key="target.id" class="space-y-4">
      <Card>
        <CardHeader class="flex flex-row items-start justify-between space-y-0">
          <div class="space-y-1">
            <CardTitle class="flex items-center gap-2 text-sm">
              <FileText class="h-4 w-4 text-muted-foreground" />
              {{ target.label }} templates
            </CardTitle>
            <p class="text-xs text-muted-foreground">
              {{ templatesFor(target.documentType).length }} available
            </p>
          </div>
        </CardHeader>
        <CardContent class="space-y-4">
          <div v-if="isLoading" class="space-y-2">
            <Skeleton v-for="n in 2" :key="n" class="h-20 w-full" />
          </div>
          <div v-else-if="templatesFor(target.documentType).length" class="grid gap-3 md:grid-cols-2">
            <article
              v-for="template in templatesFor(target.documentType)"
              :key="template.template_id"
              class="flex flex-col gap-2 rounded-md border border-border bg-card p-4 transition-colors hover:bg-muted/40"
            >
              <div class="flex items-start justify-between gap-2">
                <div class="min-w-0 space-y-0.5">
                  <h3 class="truncate text-sm font-semibold text-foreground">
                    {{ template.name || template.template_id }}
                  </h3>
                  <p class="text-xs text-muted-foreground">
                    {{ template.description || "No description provided." }}
                  </p>
                </div>
                <div class="flex shrink-0 flex-wrap items-center justify-end gap-1">
                  <Button
                    v-if="isLatexTemplate(template)"
                    variant="ghost"
                    size="sm"
                    type="button"
                    @click="editTemplate(target.documentType, template.template_id)"
                  >
                    <Pencil class="h-4 w-4" />
                    Edit
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    type="button"
                    class="text-destructive hover:text-destructive"
                    :disabled="template.is_default || isDeleting(target.documentType, template.template_id)"
                    :title="template.is_default ? 'Built-in default templates cannot be deleted.' : 'Delete template'"
                    @click="deleteTemplate(target.documentType, template)"
                  >
                    <Trash2 class="h-4 w-4" />
                    {{ isDeleting(target.documentType, template.template_id) ? "Deleting..." : "Delete" }}
                  </Button>
                </div>
              </div>
              <div class="flex flex-wrap items-center gap-1.5">
                <Badge variant="outline">
                  {{ templateRenderer(template) === "latex" ? "LaTeX" : "DOCX" }}
                </Badge>
                <Badge v-if="template.is_default" variant="secondary">Default</Badge>
                <Badge
                  v-for="output in templateSupportedOutputs(template)"
                  :key="`${template.template_id}-${output}`"
                  variant="secondary"
                >
                  {{ outputFormatLabel(output) }}
                </Badge>
                <Badge :variant="template.validation?.ok ? 'success' : 'warning'">
                  {{ template.validation?.ok ? "Validated" : "Needs validation" }}
                </Badge>
              </div>
            </article>
          </div>
          <EmptyState
            v-else
            :title="`No ${target.label.toLowerCase()} templates yet`"
            :description="`Upload a DOCX template or create a LaTeX template below.`"
          >
            <template #icon><FileText /></template>
          </EmptyState>

          <details class="rounded-md border border-border bg-muted/30">
            <summary class="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm font-medium text-foreground">
              <Upload class="h-4 w-4 text-muted-foreground" />
              Upload {{ target.label.toLowerCase() }} template (DOCX / TEX)
            </summary>
            <div class="space-y-3 px-4 pb-4">
              <label class="grid gap-1.5 text-sm">
                <span class="text-xs font-medium text-muted-foreground">Template name (optional)</span>
                <Input v-model="uploadState[target.documentType].name" placeholder="e.g. Two-column ATS resume" />
              </label>
              <label class="block cursor-pointer rounded-md border border-dashed border-border bg-background p-4 text-sm transition-colors hover:bg-muted/40">
                <input
                  :ref="(el) => (fileInputs[target.documentType] = el)"
                  type="file"
                  accept=".docx,.tex"
                  class="sr-only"
                  @change="onFileChange(target.documentType, $event)"
                />
                <div class="flex flex-col items-center gap-1 text-center">
                  <Upload class="h-5 w-5 text-muted-foreground" />
                  <strong class="text-foreground">
                    {{ uploadState[target.documentType].file?.name || "Click to choose a DOCX or TEX file" }}
                  </strong>
                  <span class="text-xs text-muted-foreground">
                    DOCX styles are repaired on upload. LaTeX marker validation reports issues without rewriting your file.
                  </span>
                </div>
              </label>
              <div class="flex flex-wrap items-center gap-3">
                <Button
                  size="sm"
                  type="button"
                  :disabled="uploadState[target.documentType].loading"
                  @click="uploadTemplate(target.documentType)"
                >
                  <Upload class="h-4 w-4" />
                  {{
                    uploadState[target.documentType].loading
                      ? "Uploading..."
                      : `Upload ${target.label} Template`
                  }}
                </Button>
                <span
                  v-if="uploadState[target.documentType].message"
                  class="text-xs text-success"
                >{{ uploadState[target.documentType].message }}</span>
                <span
                  v-if="uploadState[target.documentType].error"
                  class="text-xs text-destructive"
                >{{ uploadState[target.documentType].error }}</span>
              </div>
            </div>
          </details>

          <details class="rounded-md border border-border bg-muted/30">
            <summary class="flex cursor-pointer items-center gap-2 px-4 py-3 text-sm font-medium text-foreground">
              <Sparkles class="h-4 w-4 text-muted-foreground" />
              Create new LaTeX template
            </summary>
            <div class="space-y-3 px-4 pb-4">
              <label class="grid gap-1.5 text-sm">
                <span class="text-xs font-medium text-muted-foreground">Template name</span>
                <Input
                  v-model="latexState[target.documentType].name"
                  :placeholder="`e.g. ${target.label === 'Resume' ? 'Modern single column' : 'Formal letterhead'}`"
                />
              </label>
              <div class="flex flex-wrap items-center gap-3">
                <Button
                  variant="ghost"
                  size="sm"
                  type="button"
                  :disabled="latexState[target.documentType].loading"
                  @click="createLatexTemplate(target.documentType)"
                >
                  <Plus class="h-4 w-4" />
                  {{
                    latexState[target.documentType].loading
                      ? "Creating..."
                      : `Create ${target.label} LaTeX Template`
                  }}
                </Button>
                <span
                  v-if="latexState[target.documentType].message"
                  class="text-xs text-success"
                >{{ latexState[target.documentType].message }}</span>
                <span
                  v-if="latexState[target.documentType].error"
                  class="text-xs text-destructive"
                >{{ latexState[target.documentType].error }}</span>
              </div>
              <p class="text-xs text-muted-foreground">
                A new LaTeX template opens in the editor for you to customize the markup, validate, and save.
              </p>
            </div>
          </details>
        </CardContent>
      </Card>
    </section>
  </div>
</template>
