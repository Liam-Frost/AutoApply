<script setup>
// Phase 17.8: user-curated document library.
//
// Companion to /materials (generation) and /materials/templates
// (renderer packages). This page lists the user's own resumes and
// cover letters — the ones they uploaded, the one extracted from
// profile creation, and any generated draft they explicitly
// "Save to library"'d.

import { computed, onMounted, reactive, ref } from "vue"
import {
  AlertCircle,
  CheckCircle2,
  Download,
  FileText,
  Library as LibraryIcon,
  Pencil,
  Plus,
  Trash2,
  Upload,
  X,
} from "lucide-vue-next"

import AppSelect from "@/components/AppSelect.vue"
import MaterialsTabsNav from "@/components/MaterialsTabsNav.vue"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { EmptyState } from "@/components/ui/empty-state"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"

const DOC_TYPE_LABELS = {
  resume: "Resume",
  cover_letter: "Cover Letter",
}

const UPLOAD_TYPE_OPTIONS = [
  { value: "resume", label: "Resume" },
  { value: "cover_letter", label: "Cover Letter" },
]

const ORIGIN_LABELS = {
  uploaded: "Uploaded",
  profile_import: "From profile",
  generated_promoted: "Saved from a draft",
}

const SOURCE_TYPE_LABELS = {
  docx: "DOCX",
  latex: "LaTeX",
  pdf: "PDF",
  txt: "TXT",
}

const ACCEPTS_BY_TYPE = {
  resume: ".docx,.pdf,.tex",
  cover_letter: ".docx,.pdf,.tex,.txt",
}

const state = reactive({
  loading: true,
  error: "",
  message: "",
  documents: [],
  uploading: false,
  uploadType: "resume",
  uploadDisplayName: "",
  uploadFile: null,
  renameTarget: null,
  renameValue: "",
  deleteTarget: null,
})

const fileInputRef = ref(null)

const documentsByType = computed(() => {
  const out = { resume: [], cover_letter: [] }
  for (const doc of state.documents) {
    if (out[doc.document_type]) out[doc.document_type].push(doc)
  }
  return out
})

async function refresh() {
  state.loading = true
  state.error = ""
  try {
    const response = await api.documents()
    state.documents = response.documents || []
  } catch (err) {
    state.error = err?.message || "Couldn't load your library."
  } finally {
    state.loading = false
  }
}

function pickFile() {
  fileInputRef.value?.click()
}

function onFilePicked(event) {
  const file = event.target.files?.[0]
  state.uploadFile = file || null
  if (file && !state.uploadDisplayName) {
    state.uploadDisplayName = file.name.replace(/\.[^/.]+$/, "")
  }
}

function clearUploadForm() {
  state.uploadFile = null
  state.uploadDisplayName = ""
  if (fileInputRef.value) fileInputRef.value.value = ""
}

async function uploadDocument() {
  if (!state.uploadFile) {
    state.error = "Pick a file first."
    return
  }
  state.uploading = true
  state.error = ""
  state.message = ""
  try {
    const result = await api.uploadDocument(state.uploadType, state.uploadFile, {
      displayName: state.uploadDisplayName.trim() || undefined,
    })
    state.message =
      result.status === "exists"
        ? "That file is already in your library."
        : `Added “${result.document?.display_name || state.uploadDisplayName}”.`
    clearUploadForm()
    await refresh()
  } catch (err) {
    state.error = err?.message || "Upload failed."
  } finally {
    state.uploading = false
  }
}

function openRename(doc) {
  state.renameTarget = doc
  state.renameValue = doc.display_name
}

function closeRename() {
  state.renameTarget = null
  state.renameValue = ""
}

async function confirmRename() {
  if (!state.renameTarget) return
  const name = state.renameValue.trim()
  if (!name) {
    state.error = "Name can't be empty."
    return
  }
  try {
    await api.updateDocument(state.renameTarget.id, { displayName: name })
    state.message = `Renamed to “${name}”.`
    closeRename()
    await refresh()
  } catch (err) {
    state.error = err?.message || "Rename failed."
  }
}

function openDelete(doc) {
  state.deleteTarget = doc
}

function closeDelete() {
  state.deleteTarget = null
}

async function confirmDelete() {
  if (!state.deleteTarget) return
  const target = state.deleteTarget
  try {
    const result = await api.deleteDocument(target.id)
    state.message = result.message || `Removed “${target.display_name}”.`
    closeDelete()
    await refresh()
  } catch (err) {
    state.error = err?.message || "Delete failed."
  }
}

function formatSize(bytes) {
  if (!bytes) return ""
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso) {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
}

onMounted(refresh)
</script>

<template>
  <div class="space-y-6">
    <MaterialsTabsNav />

    <div class="space-y-1">
      <h2 class="flex items-center gap-2 text-xl font-semibold">
        <LibraryIcon class="h-5 w-5 text-muted-foreground" />
        Document Library
      </h2>
      <p class="max-w-2xl text-sm text-muted-foreground">
        Resumes and cover letters AutoApply can use as a starting point. Upload your own, pick a base in Settings, or save any generated draft you like.
      </p>
    </div>

    <Alert v-if="state.error" variant="destructive">
      <AlertCircle class="h-4 w-4" />
      <AlertDescription>{{ state.error }}</AlertDescription>
    </Alert>
    <Alert v-if="state.message" class="border-primary/40 bg-primary/5">
      <CheckCircle2 class="h-4 w-4" />
      <AlertDescription>{{ state.message }}</AlertDescription>
    </Alert>

    <Card>
      <CardHeader class="pb-2">
        <CardTitle class="flex items-center gap-2 text-sm">
          <Upload class="h-4 w-4 text-muted-foreground" />
          Add a Document
        </CardTitle>
      </CardHeader>
      <CardContent class="space-y-3">
        <div class="grid gap-3 md:grid-cols-[160px_1fr_auto]">
          <label class="space-y-1.5">
            <span class="text-xs font-medium text-muted-foreground">Type</span>
            <AppSelect
              v-model="state.uploadType"
              :options="UPLOAD_TYPE_OPTIONS"
              aria-label="Document type"
            />
          </label>
          <label class="space-y-1.5">
            <span class="text-xs font-medium text-muted-foreground">Name (optional)</span>
            <Input
              v-model="state.uploadDisplayName"
              type="text"
              placeholder="e.g. Frontend resume v3"
            />
          </label>
          <div class="flex items-end gap-2">
            <input
              ref="fileInputRef"
              type="file"
              :accept="ACCEPTS_BY_TYPE[state.uploadType]"
              class="hidden"
              @change="onFilePicked"
            />
            <Button variant="outline" type="button" @click="pickFile">
              <Plus class="h-4 w-4" />
              Pick file
            </Button>
            <Button
              type="button"
              :disabled="!state.uploadFile || state.uploading"
              @click="uploadDocument"
            >
              <Upload class="h-4 w-4" />
              {{ state.uploading ? "Uploading…" : "Upload" }}
            </Button>
          </div>
        </div>
        <p v-if="state.uploadFile" class="text-xs text-muted-foreground">
          Selected: <span class="font-medium text-foreground">{{ state.uploadFile.name }}</span>
          ({{ formatSize(state.uploadFile.size) }})
          <button
            type="button"
            class="ml-2 text-muted-foreground hover:text-destructive"
            @click="clearUploadForm"
          >
            <X class="inline h-3.5 w-3.5" />
          </button>
        </p>
        <p class="text-xs text-muted-foreground">
          Resumes accept .docx / .pdf / .tex. Cover letters also accept .txt. PDFs work as references but can't be patched directly — pick DOCX or LaTeX if you want AutoApply to edit them in place.
        </p>
      </CardContent>
    </Card>

    <section v-for="docType in ['resume', 'cover_letter']" :key="docType" class="space-y-3">
      <div class="flex items-baseline justify-between">
        <h3 class="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
          {{ DOC_TYPE_LABELS[docType] }}
        </h3>
        <span class="text-xs tabular-nums text-muted-foreground">
          {{ documentsByType[docType].length }}
        </span>
      </div>

      <div v-if="state.loading" class="space-y-2">
        <Skeleton v-for="n in 2" :key="n" class="h-20 w-full" />
      </div>

      <Card v-else-if="!documentsByType[docType].length">
        <CardContent class="py-10">
          <EmptyState
            :title="`No ${DOC_TYPE_LABELS[docType].toLowerCase()}s yet`"
            description="Upload one above, or save a draft you like from the Generate tab."
          >
            <template #icon><FileText /></template>
          </EmptyState>
        </CardContent>
      </Card>

      <Card v-else>
        <CardContent class="p-0">
          <ul class="divide-y">
            <li
              v-for="doc in documentsByType[docType]"
              :key="doc.id"
              class="flex flex-col gap-3 p-4 md:flex-row md:items-center md:justify-between"
            >
              <div class="min-w-0 space-y-1">
                <div class="flex flex-wrap items-center gap-2">
                  <span class="font-medium truncate">{{ doc.display_name }}</span>
                  <Badge variant="outline" class="text-xs">
                    {{ SOURCE_TYPE_LABELS[doc.source_type] || doc.source_type }}
                  </Badge>
                  <Badge variant="secondary" class="text-xs">
                    {{ ORIGIN_LABELS[doc.origin] || doc.origin }}
                  </Badge>
                  <Badge v-if="!doc.editable" variant="outline" class="text-xs">
                    Reference only
                  </Badge>
                </div>
                <div class="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span>{{ doc.original_filename }}</span>
                  <span>{{ formatSize(doc.size_bytes) }}</span>
                  <span>Added {{ formatDate(doc.created_at) }}</span>
                </div>
                <p v-if="doc.notes" class="text-xs italic text-muted-foreground">{{ doc.notes }}</p>
              </div>
              <div class="flex flex-wrap items-center gap-2">
                <a
                  :href="api.documentDownloadUrl(doc.id)"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex items-center gap-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm hover:bg-muted/50"
                >
                  <Download class="h-4 w-4" />
                  Download
                </a>
                <Button size="sm" variant="outline" @click="openRename(doc)">
                  <Pencil class="h-4 w-4" />
                  Rename
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  class="text-destructive hover:bg-destructive/10 hover:text-destructive"
                  @click="openDelete(doc)"
                >
                  <Trash2 class="h-4 w-4" />
                  Delete
                </Button>
              </div>
            </li>
          </ul>
        </CardContent>
      </Card>
    </section>

    <Dialog :open="!!state.renameTarget" @update:open="(v) => !v && closeRename()">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Rename document</DialogTitle>
          <DialogDescription>
            Only the display name in your library changes. The file itself isn't modified.
          </DialogDescription>
        </DialogHeader>
        <label class="space-y-1.5 text-sm">
          <span class="text-xs font-medium text-muted-foreground">New name</span>
          <Input v-model="state.renameValue" type="text" @keydown.enter.prevent="confirmRename" />
        </label>
        <DialogFooter>
          <Button variant="outline" @click="closeRename">Cancel</Button>
          <Button @click="confirmRename">Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog :open="!!state.deleteTarget" @update:open="(v) => !v && closeDelete()">
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this document?</DialogTitle>
          <DialogDescription>
            <span v-if="state.deleteTarget">
              <strong>{{ state.deleteTarget.display_name }}</strong> will be removed from your library and its file deleted from disk. Any application that already used it stays intact — only the library entry goes away.
            </span>
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" @click="closeDelete">Cancel</Button>
          <Button variant="destructive" @click="confirmDelete">
            <Trash2 class="h-4 w-4" />
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
