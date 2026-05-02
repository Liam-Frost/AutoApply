<script setup>
import { computed, onMounted, reactive, watch } from "vue"
import { RouterLink, useRouter } from "vue-router"
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Code2,
  FileCheck,
  Save,
} from "lucide-vue-next"

import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"
import { applyTemplatesResponse, documentTypeLabel } from "@/lib/materials-templates"

const props = defineProps({
  documentType: { type: String, required: true },
  templateId: { type: String, required: true },
})

const router = useRouter()

const editor = reactive({
  loading: true,
  saving: false,
  validating: false,
  error: "",
  message: "",
  name: "",
  description: "",
  content: "",
  validation: null,
  renderer: "",
})

watch(
  () => [props.documentType, props.templateId],
  () => {
    void loadTemplate()
  },
  { immediate: false },
)

onMounted(loadTemplate)

async function loadTemplate() {
  editor.loading = true
  editor.error = ""
  editor.message = ""

  try {
    const response = await api.templateDetail(props.documentType, props.templateId)
    const template = response.template || {}
    editor.name = template.name || template.template_id || ""
    editor.description = template.description || ""
    editor.content = template.content || ""
    editor.validation = template.validation || null
    editor.renderer = template.renderer || template.manifest?.renderer || ""
  } catch (error) {
    editor.error = error.message
  } finally {
    editor.loading = false
  }
}

async function saveTemplate() {
  editor.saving = true
  editor.error = ""
  editor.message = ""

  try {
    const response = await api.updateTemplate(props.documentType, props.templateId, {
      template_name: editor.name,
      description: editor.description,
      content: editor.content,
    })
    applyTemplatesResponse(response)
    editor.validation = response.template?.validation || null
    editor.message = "Saved template."
  } catch (error) {
    editor.error = error.message
  } finally {
    editor.saving = false
  }
}

async function validateTemplate() {
  editor.validating = true
  editor.error = ""
  editor.message = ""

  try {
    const response = await api.validateTemplate(props.documentType, props.templateId)
    editor.validation = response.validation || response.template?.validation || null
    applyTemplatesResponse(response)
    editor.message = editor.validation?.ok ? "Template validated." : "Template needs review."
  } catch (error) {
    editor.error = error.message
  } finally {
    editor.validating = false
  }
}

function prettyLabel(value) {
  return String(value || "")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

function validationIssueSeverity(issue) {
  return issue?.severity || "warning"
}

function validationIssueBadgeClass(issue) {
  const severity = validationIssueSeverity(issue)
  if (severity === "info") {
    return "border-muted-foreground/40 bg-muted/60 text-foreground"
  }
  return "border-destructive/50 bg-destructive/10 text-destructive hover:bg-destructive/15"
}

const validationIssues = computed(() => editor.validation?.issues || [])
const isLatexEditor = computed(() => editor.renderer === "latex")
</script>

<template>
  <div class="space-y-6">
    <Card>
      <CardContent class="flex flex-col items-start justify-between gap-3 p-5 md:flex-row md:items-center">
        <div class="flex items-center gap-3">
          <RouterLink
            to="/materials/templates"
            class="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Back to Template Library"
            title="Back to Template Library"
          >
            <ArrowLeft class="h-4 w-4" />
          </RouterLink>
          <div class="space-y-1">
            <p class="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              {{ documentTypeLabel(documentType) }} template
            </p>
            <h2 class="flex items-center gap-2 text-lg font-semibold tracking-tight text-foreground">
              <Code2 class="h-4 w-4 text-muted-foreground" />
              {{ editor.name || templateId }}
            </h2>
            <p class="font-mono text-xs text-muted-foreground">{{ templateId }}</p>
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <Badge v-if="editor.renderer" variant="outline">
            {{ isLatexEditor ? "LaTeX" : editor.renderer.toUpperCase() }}
          </Badge>
          <Badge v-if="editor.validation" :variant="editor.validation.ok ? 'success' : 'warning'">
            {{ editor.validation.ok ? "Validated" : "Needs validation" }}
          </Badge>
        </div>
      </CardContent>
    </Card>

    <Alert v-if="editor.error" variant="destructive">
      <AlertCircle class="h-4 w-4" />
      <AlertDescription>{{ editor.error }}</AlertDescription>
    </Alert>
    <Alert v-if="editor.message" variant="success">
      <CheckCircle2 class="h-4 w-4" />
      <AlertDescription>{{ editor.message }}</AlertDescription>
    </Alert>

    <Card v-if="editor.loading">
      <CardContent class="space-y-3 p-6">
        <Skeleton class="h-10 w-full" />
        <Skeleton class="h-10 w-full" />
        <Skeleton class="h-64 w-full" />
      </CardContent>
    </Card>

    <Card v-else>
      <CardHeader>
        <CardTitle class="text-sm">Template metadata</CardTitle>
      </CardHeader>
      <CardContent class="grid gap-4 md:grid-cols-2">
        <label class="space-y-1.5">
          <span class="text-xs font-medium text-muted-foreground">Name</span>
          <Input v-model="editor.name" />
        </label>
        <label class="space-y-1.5">
          <span class="text-xs font-medium text-muted-foreground">Description</span>
          <Input v-model="editor.description" />
        </label>
      </CardContent>
    </Card>

    <Card v-if="!editor.loading">
      <CardHeader class="flex flex-row items-center justify-between space-y-0">
        <CardTitle class="flex items-center gap-2 text-sm">
          <Code2 class="h-4 w-4 text-muted-foreground" />
          template.tex
        </CardTitle>
        <div class="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            type="button"
            :disabled="editor.validating"
            @click="validateTemplate"
          >
            <FileCheck class="h-4 w-4" />
            {{ editor.validating ? "Validating..." : "Validate" }}
          </Button>
          <Button
            size="sm"
            type="button"
            :disabled="editor.saving"
            @click="saveTemplate"
          >
            <Save class="h-4 w-4" />
            {{ editor.saving ? "Saving..." : "Save" }}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <textarea
          v-model="editor.content"
          spellcheck="false"
          class="h-[28rem] w-full rounded-md border border-input bg-background p-3 font-mono text-xs leading-relaxed text-foreground ring-offset-background focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
        ></textarea>
      </CardContent>
    </Card>

    <Card v-if="!editor.loading && validationIssues.length">
      <CardHeader>
        <CardTitle class="flex items-center gap-2 text-sm">
          <FileCheck class="h-4 w-4 text-muted-foreground" />
          Validation issues
        </CardTitle>
      </CardHeader>
      <CardContent class="space-y-2">
        <div
          v-for="issue in validationIssues"
          :key="`${issue.type}-${issue.message}`"
          class="rounded-md border border-border bg-muted/40 p-3"
        >
          <div class="flex items-center gap-2">
            <Badge variant="outline" :class="validationIssueBadgeClass(issue)">
              {{ prettyLabel(validationIssueSeverity(issue)) }}
            </Badge>
            <strong class="text-sm text-foreground">{{ prettyLabel(issue.type) }}</strong>
          </div>
          <p class="mt-1 text-sm text-muted-foreground">{{ issue.message }}</p>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
