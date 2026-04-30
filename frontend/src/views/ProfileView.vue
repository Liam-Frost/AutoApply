<script setup>
import { computed, reactive, ref, watch } from "vue"
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router"
import {
  AlertCircle,
  ArrowLeft,
  Check,
  CheckCircle2,
  Pencil,
  Plus,
  Save,
  Trash2,
  Upload,
  UserCircle,
  Users,
  X,
} from "lucide-vue-next"

import AppIcon from "@/components/AppIcon.vue"
import TagInput from "@/components/TagInput.vue"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState } from "@/components/ui/empty-state"
import { Skeleton } from "@/components/ui/skeleton"
import { api } from "@/lib/api"

const route = useRoute()
const router = useRouter()
const fileInput = ref(null)

const defaultSkillCategories = ["languages", "frameworks", "databases", "tools", "domains"]
let localId = 0

const state = reactive({
  loading: true,
  ready: false,
  saving: false,
  uploading: false,
  deleting: false,
  renaming: false,
  error: "",
  message: "",
  createMenuOpen: false,
  createMode: "",
  createProfileId: "",
  uploadProfileId: "",
  overwriteUpload: false,
  renameTargetId: "",
  renameValue: "",
  data: {
    has_profile: false,
    profile: null,
    profile_path: "",
    profiles: [],
    active_profile_id: "",
    selected_profile_id: "",
  },
  editor: emptyEditorProfile(),
  loadedFingerprint: "",
  sections: collapsedSections(),
})

const currentRouteProfileId = computed(() => {
  const value = route.params.profileId
  return typeof value === "string" ? value : ""
})
const isEditingView = computed(() => Boolean(currentRouteProfileId.value))
const currentProfileId = computed(
  () => state.data.selected_profile_id || state.data.active_profile_id || currentRouteProfileId.value || "",
)
const profiles = computed(() => state.data.profiles || [])
const isDirty = computed(() => profileFingerprint(state.editor) !== state.loadedFingerprint)

watch(
  () => route.params.profileId,
  async (profileId) => {
    await load(typeof profileId === "string" ? profileId : "")
  },
  { immediate: true },
)

onBeforeRouteLeave(() => {
  if (!isEditingView.value || !isDirty.value) {
    return true
  }

  return confirmDiscardChanges("Leaving the editor")
})

async function load(profileId = "") {
  state.loading = true
  state.error = ""

  try {
    state.data = await api.profile(profileId)
    syncEditorFromProfile(state.data.profile)
    if (profileId && !state.data.has_profile) {
      state.error = `Profile '${profileId}' not found.`
    }
  } catch (error) {
    state.error = error.message
  } finally {
    state.loading = false
    state.ready = true
  }
}

function syncEditorFromProfile(profile) {
  syncEditorState(profile, false)
}

function syncEditorState(profile, preserveUi) {
  const sectionState = preserveUi ? { ...state.sections } : collapsedSections()
  const editorState = preserveUi ? captureEditorUiState(state.editor) : null

  state.editor = toEditorProfile(profile)
  state.sections = sectionState
  if (editorState) {
    applyEditorUiState(state.editor, editorState)
  }
  state.loadedFingerprint = profileFingerprint(state.editor)
  if (!isEditingView.value) {
    state.uploadProfileId = currentProfileId.value || ""
  }
}

function openCreateMenu(mode = "") {
  if (!state.createMenuOpen) {
    state.createMenuOpen = true
    state.createMode = mode || "template"
    return
  }

  state.createMode = mode || state.createMode || "template"
}

function closeCreateMenu() {
  state.createMenuOpen = false
  state.createMode = ""
  state.createProfileId = ""
  state.uploadProfileId = currentProfileId.value || ""
  state.overwriteUpload = false
  if (fileInput.value) {
    fileInput.value.value = ""
  }
}

async function createProfile() {
  if (!state.createProfileId.trim()) {
    state.error = "Profile id is required."
    return
  }

  if (isEditingView.value && !confirmDiscardChanges("Create a new profile")) {
    return
  }

  state.saving = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.createProfile(state.createProfileId.trim(), true)
    state.message = state.data.message || "Created"
    closeCreateMenu()
    await router.push(`/profile/${state.data.selected_profile_id}`)
  } catch (error) {
    state.error = error.message
  } finally {
    state.saving = false
  }
}

async function uploadProfileFromFile() {
  const file = fileInput.value?.files?.[0]
  if (!file) {
    state.error = "Select a file first."
    return
  }

  if (isEditingView.value && !confirmDiscardChanges("Uploading a resume")) {
    return
  }

  state.uploading = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.uploadResume(file, {
      profileId: state.uploadProfileId.trim() || undefined,
      overwrite: state.overwriteUpload,
      setActive: true,
    })
    state.message = state.data.message || "Imported"
    closeCreateMenu()
    await router.push(`/profile/${state.data.selected_profile_id}`)
  } catch (error) {
    state.error = error.message
  } finally {
    state.uploading = false
  }
}

async function activateProfile(profileId) {
  state.saving = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.activateProfile(profileId)
    state.message = state.data.message || "Selected"
    if (isEditingView.value && currentRouteProfileId.value === profileId) {
      syncEditorState(state.data.profile, true)
    }
  } catch (error) {
    state.error = error.message
  } finally {
    state.saving = false
  }
}

async function openProfileEditor(profileId) {
  if (currentRouteProfileId.value === profileId) {
    return
  }

  if (isEditingView.value && !confirmDiscardChanges("Open another profile")) {
    return
  }

  await router.push(`/profile/${profileId}`)
}

async function goToLibrary() {
  if (isEditingView.value && !confirmDiscardChanges("Back to profiles")) {
    return
  }

  await router.push("/profile")
}

function startRename(profile) {
  state.renameTargetId = profile.id
  state.renameValue = profile.id
  state.error = ""
}

function cancelRename() {
  state.renameTargetId = ""
  state.renameValue = ""
}

async function renameProfile(profileId) {
  if (!state.renameValue.trim()) {
    state.error = "New profile id is required."
    return
  }

  state.renaming = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.renameProfile(profileId, state.renameValue.trim())
    const renamedId = state.data.selected_profile_id
    state.message = state.data.message || "Renamed"
    cancelRename()

    if (currentRouteProfileId.value === profileId) {
      await router.replace(`/profile/${renamedId}`)
      return
    }
  } catch (error) {
    state.error = error.message
  } finally {
    state.renaming = false
  }
}

async function saveProfile() {
  if (!currentProfileId.value) {
    state.error = "Select a profile first."
    return
  }

  state.saving = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.saveProfile(currentProfileId.value, serializeEditorProfile(state.editor), false)
    state.message = state.data.message || "Saved"
    syncEditorState(state.data.profile, true)
  } catch (error) {
    state.error = error.message
  } finally {
    state.saving = false
  }
}

async function deleteProfile(profileId) {
  if (!window.confirm(`Delete profile '${profileId}'?`)) {
    return
  }

  state.deleting = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.deleteProfile(profileId)
    state.message = state.data.message || "Deleted"
    if (currentRouteProfileId.value === profileId) {
      await router.push("/profile")
      return
    }
    syncEditorFromProfile(state.data.profile)
  } catch (error) {
    state.error = error.message
  } finally {
    state.deleting = false
  }
}

function toggleSection(section) {
  state.sections[section] = !state.sections[section]
}

function addEducation() {
  const item = emptyEducation()
  item.expanded = true
  state.editor.education.push(item)
  state.sections.education = true
}

function removeEducation(index) {
  state.editor.education.splice(index, 1)
}

function addCourse(educationIndex) {
  state.editor.education[educationIndex].relevant_courses.push(emptyCourse())
}

function removeCourse(educationIndex, courseIndex) {
  state.editor.education[educationIndex].relevant_courses.splice(courseIndex, 1)
}

function addExperience() {
  const item = emptyExperience()
  item.expanded = true
  state.editor.work_experiences.push(item)
  state.sections.experience = true
}

function removeExperience(index) {
  state.editor.work_experiences.splice(index, 1)
}

function addExperienceBullet(experienceIndex) {
  const bullet = emptyBullet()
  bullet.expanded = true
  state.editor.work_experiences[experienceIndex].bullets.push(bullet)
}

function removeExperienceBullet(experienceIndex, bulletIndex) {
  state.editor.work_experiences[experienceIndex].bullets.splice(bulletIndex, 1)
}

function addProject() {
  const item = emptyProject()
  item.expanded = true
  state.editor.projects.push(item)
  state.sections.projects = true
}

function removeProject(index) {
  state.editor.projects.splice(index, 1)
}

function addProjectBullet(projectIndex) {
  const bullet = emptyBullet()
  bullet.expanded = true
  state.editor.projects[projectIndex].bullets.push(bullet)
}

function removeProjectBullet(projectIndex, bulletIndex) {
  state.editor.projects[projectIndex].bullets.splice(bulletIndex, 1)
}

function addSkillCategory() {
  state.editor.skills.push({ id: makeId("skill"), key: "", values: [], expanded: true })
  state.error = ""
  state.sections.skills = true
}

function toggleItem(item) {
  item.expanded = !item.expanded
}

function removeSkillCategory(index) {
  state.editor.skills.splice(index, 1)
}

function toEditorProfile(profile) {
  const normalized = normalizeProfile(profile)
  const skillKeys = [...defaultSkillCategories]
  Object.keys(normalized.skills).forEach((key) => {
    if (!skillKeys.includes(key)) {
      skillKeys.push(key)
    }
  })

  return {
    identity: { ...normalized.identity },
    education: normalized.education.map(toEducationEditor),
    work_experiences: normalized.work_experiences.map(toExperienceEditor),
    projects: normalized.projects.map(toProjectEditor),
    skills: skillKeys.map((key) => ({
      id: makeId("skill"),
      key,
      values: normalizeStringArray(normalized.skills[key]),
      expanded: false,
    })),
  }
}

function serializeEditorProfile(editor) {
  return buildProfilePayload(editor, true)
}

function buildProfilePayload(editor, validateSkillKeys) {
  const identity = Object.fromEntries(
    Object.entries(editor.identity).filter(([, value]) => String(value || "").trim()),
  )

  const skillEntries = editor.skills
    .map((entry) => [slugifyCategory(entry.key), normalizeStringArray(entry.values)])
    .filter(([key, values]) => key && values.length)

  if (validateSkillKeys) {
    const seen = new Set()
    for (const [key] of skillEntries) {
      if (!key) {
        throw new Error("Skill category is required")
      }
      if (seen.has(key)) {
        throw new Error(`Duplicate skill category: ${key}`)
      }
      seen.add(key)
    }
  }

  return {
    identity,
    education: editor.education.map(serializeEducation).filter(hasContent),
    work_experiences: editor.work_experiences.map(serializeExperience).filter(hasContent),
    projects: editor.projects.map(serializeProject).filter(hasContent),
    skills: Object.fromEntries(skillEntries),
  }
}

function serializeEducation(item) {
  return compactObject({
    institution: item.institution,
    degree: item.degree,
    field: item.field,
    location: item.location,
    start_date: item.start_date,
    end_date: item.end_date,
    gpa: item.gpa,
    relevant_courses: item.relevant_courses
      .map((course) =>
        compactObject({
          name: course.name,
          tags: normalizeStringArray(course.tags),
        }),
      )
      .filter(hasContent),
  })
}

function serializeExperience(item) {
  return compactObject({
    company: item.company,
    title: item.title,
    location: item.location,
    start_date: item.start_date,
    end_date: item.end_date,
    bullets: item.bullets
      .map((bullet) =>
        compactObject({
          text: bullet.text,
          tags: normalizeStringArray(bullet.tags),
        }),
      )
      .filter(hasContent),
  })
}

function serializeProject(item) {
  return compactObject({
    name: item.name,
    role: item.role,
    description: item.description,
    tech_stack: normalizeStringArray(item.tech_stack),
    links: normalizeStringArray(item.links),
    bullets: item.bullets
      .map((bullet) =>
        compactObject({
          text: bullet.text,
          tags: normalizeStringArray(bullet.tags),
        }),
      )
      .filter(hasContent),
  })
}

function normalizeProfile(profile) {
  const base = emptyStructuredProfile()
  if (!profile) {
    return base
  }

  return {
    identity: { ...base.identity, ...(profile.identity || {}) },
    education: Array.isArray(profile.education) ? profile.education : [],
    work_experiences: Array.isArray(profile.work_experiences) ? profile.work_experiences : [],
    projects: Array.isArray(profile.projects) ? profile.projects : [],
    skills: typeof profile.skills === "object" && profile.skills !== null ? profile.skills : {},
  }
}

function emptyEditorProfile() {
  return {
    identity: { ...emptyStructuredProfile().identity },
    education: [],
    work_experiences: [],
    projects: [],
    skills: defaultSkillCategories.map((key) => ({
      id: makeId("skill"),
      key,
      values: [],
    })),
  }
}

function emptyStructuredProfile() {
  return {
    identity: {
      full_name: "",
      email: "",
      phone: "",
      location: "",
      linkedin_url: "",
      github_url: "",
      portfolio_url: "",
    },
    education: [],
    work_experiences: [],
    projects: [],
    skills: {
      languages: [],
      frameworks: [],
      databases: [],
      tools: [],
      domains: [],
    },
  }
}

function emptyEducation() {
  return {
    id: makeId("education"),
    expanded: false,
    institution: "",
    degree: "",
    field: "",
    location: "",
    start_date: "",
    end_date: "",
    gpa: "",
    relevant_courses: [],
  }
}

function emptyCourse() {
  return {
    id: makeId("course"),
    name: "",
    tags: [],
  }
}

function emptyExperience() {
  return {
    id: makeId("experience"),
    expanded: false,
    company: "",
    title: "",
    location: "",
    start_date: "",
    end_date: "",
    bullets: [],
  }
}

function emptyProject() {
  return {
    id: makeId("project"),
    expanded: false,
    name: "",
    role: "",
    description: "",
    tech_stack: [],
    links: [],
    bullets: [],
  }
}

function emptyBullet() {
  return {
    id: makeId("bullet"),
    expanded: false,
    text: "",
    tags: [],
  }
}

function toEducationEditor(item) {
  return {
    id: makeId("education"),
    expanded: false,
    institution: item.institution || "",
    degree: item.degree || "",
    field: item.field || "",
    location: item.location || "",
    start_date: item.start_date || "",
    end_date: item.end_date || "",
    gpa: item.gpa || "",
    relevant_courses: Array.isArray(item.relevant_courses)
      ? item.relevant_courses.map((course) => ({
          id: makeId("course"),
          name: course.name || "",
          tags: normalizeStringArray(course.tags),
        }))
      : [],
  }
}

function toExperienceEditor(item) {
  return {
    id: makeId("experience"),
    expanded: false,
    company: item.company || "",
    title: item.title || "",
    location: item.location || "",
    start_date: item.start_date || "",
    end_date: item.end_date || "",
    bullets: Array.isArray(item.bullets)
      ? item.bullets.map((bullet) => ({
          id: makeId("bullet"),
          expanded: false,
          text: typeof bullet === "string" ? bullet : bullet?.text || "",
          tags: typeof bullet === "object" ? normalizeStringArray(bullet?.tags) : [],
        }))
      : [],
  }
}

function toProjectEditor(item) {
  return {
    id: makeId("project"),
    expanded: false,
    name: item.name || "",
    role: item.role || "",
    description: item.description || "",
    tech_stack: normalizeStringArray(item.tech_stack),
    links: normalizeStringArray(item.links),
    bullets: Array.isArray(item.bullets)
      ? item.bullets.map((bullet) => ({
          id: makeId("bullet"),
          expanded: false,
          text: typeof bullet === "string" ? bullet : bullet?.text || "",
          tags: typeof bullet === "object" ? normalizeStringArray(bullet?.tags) : [],
        }))
      : [],
  }
}

function normalizeStringArray(value) {
  const raw = Array.isArray(value)
    ? value.map((item) => String(item).trim()).filter(Boolean)
    : String(value || "")
        .split(/[\r\n,;]+/)
        .map((item) => item.trim())
        .filter(Boolean)

  const seen = new Set()
  return raw.filter((item) => {
    const lookup = item.toLowerCase()
    if (seen.has(lookup)) {
      return false
    }
    seen.add(lookup)
    return true
  })
}

function compactObject(value) {
  if (Array.isArray(value)) {
    return value.filter(hasContent)
  }

  return Object.fromEntries(
    Object.entries(value).filter(([, item]) => {
      if (Array.isArray(item)) {
        return item.length > 0
      }
      return hasContent(item)
    }),
  )
}

function hasContent(value) {
  if (Array.isArray(value)) {
    return value.length > 0
  }
  if (typeof value === "object" && value !== null) {
    return Object.keys(value).length > 0
  }
  return String(value || "").trim().length > 0
}

function slugifyCategory(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
}

function profileFingerprint(editor) {
  return JSON.stringify(buildProfilePayload(editor, false))
}

function confirmDiscardChanges(action) {
  if (!isDirty.value) {
    return true
  }

  return window.confirm(`${action} will discard unsaved changes. Continue?`)
}

function collapsedSections() {
  return {
    identity: false,
    education: false,
    experience: false,
    projects: false,
    skills: false,
  }
}

function sectionLabel(section) {
  if (section === "identity") {
    return state.editor.identity.full_name || state.editor.identity.email || "No identity details"
  }
  if (section === "education") {
    return `${state.editor.education.length} entries`
  }
  if (section === "experience") {
    return `${state.editor.work_experiences.length} entries`
  }
  if (section === "projects") {
    return `${state.editor.projects.length} entries`
  }
  if (section === "skills") {
    return `${state.editor.skills.filter((entry) => entry.values.length).length} categories`
  }
  return ""
}

function educationEntryLabel(item, index) {
  return item.institution || [item.degree, item.field].filter(Boolean).join(" ") || `Education ${index + 1}`
}

function experienceEntryLabel(item, index) {
  return item.company || item.title || `Experience ${index + 1}`
}

function projectEntryLabel(item, index) {
  return item.name || item.role || `Project ${index + 1}`
}

function bulletLabel(bullet, index) {
  return bullet.text?.trim() ? bullet.text.trim().slice(0, 72) : `Bullet ${index + 1}`
}

function skillEntryLabel(entry) {
  return prettifyCategory(entry.key)
}

function summaryLine(parts) {
  return parts.filter(Boolean).join(" / ") || "No details yet"
}

function prettifyCategory(value) {
  return slugifyCategory(value)
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function captureEditorUiState(editor) {
  return {
    education: editor.education.map((item) => ({ expanded: Boolean(item.expanded) })),
    work_experiences: editor.work_experiences.map((item) => ({
      expanded: Boolean(item.expanded),
      bullets: item.bullets.map((bullet) => ({ expanded: Boolean(bullet.expanded) })),
    })),
    projects: editor.projects.map((item) => ({
      expanded: Boolean(item.expanded),
      bullets: item.bullets.map((bullet) => ({ expanded: Boolean(bullet.expanded) })),
    })),
    skills: editor.skills.map((entry) => ({ expanded: Boolean(entry.expanded) })),
  }
}

function applyEditorUiState(editor, snapshot) {
  editor.education.forEach((item, index) => {
    item.expanded = snapshot.education?.[index]?.expanded ?? item.expanded
  })

  editor.work_experiences.forEach((item, index) => {
    item.expanded = snapshot.work_experiences?.[index]?.expanded ?? item.expanded
    item.bullets.forEach((bullet, bulletIndex) => {
      bullet.expanded = snapshot.work_experiences?.[index]?.bullets?.[bulletIndex]?.expanded ?? bullet.expanded
    })
  })

  editor.projects.forEach((item, index) => {
    item.expanded = snapshot.projects?.[index]?.expanded ?? item.expanded
    item.bullets.forEach((bullet, bulletIndex) => {
      bullet.expanded = snapshot.projects?.[index]?.bullets?.[bulletIndex]?.expanded ?? bullet.expanded
    })
  })

  editor.skills.forEach((entry, index) => {
    entry.expanded = snapshot.skills?.[index]?.expanded ?? entry.expanded
  })
}

function formatUpdatedAt(value) {
  return value ? new Date(value).toLocaleDateString("en-CA", { timeZone: "UTC" }) : ""
}

function makeId(prefix) {
  localId += 1
  return `${prefix}-${localId}`
}
</script>

<template>
  <div class="space-y-6">
    <div v-if="state.loading && !state.ready" class="space-y-2">
      <Skeleton class="h-8 w-40" />
      <Skeleton class="h-24 w-full" />
    </div>
    <Alert v-if="state.error" variant="destructive">
      <AlertCircle class="h-4 w-4" />
      <AlertDescription>{{ state.error }}</AlertDescription>
    </Alert>
    <Alert v-if="state.message" variant="success">
      <CheckCircle2 class="h-4 w-4" />
      <AlertDescription>{{ state.message }}</AlertDescription>
    </Alert>

    <template v-if="!state.loading && !isEditingView">
      <Card class="profile-library-shell" :class="{ 'is-loading': state.loading }">
        <CardHeader class="flex flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle class="flex items-center gap-2 text-sm">
              <Users class="h-4 w-4 text-muted-foreground" />
              Profiles
            </CardTitle>
            <p class="mt-1 text-xs text-muted-foreground">{{ profiles.length }} available</p>
          </div>
          <Button variant="ghost" size="icon" type="button" aria-label="Add profile" title="Add profile" @click="openCreateMenu()">
            <Plus class="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent class="space-y-4">

        <div v-if="state.createMenuOpen" class="profile-create-panel">
          <div class="section-head compact-head">
            <h2>Create</h2>
            <button class="icon-button" type="button" aria-label="Close Create Menu" title="Close Create Menu" @click="closeCreateMenu"><AppIcon name="close" /></button>
          </div>

          <div class="chip-row mode-toggle-row">
            <button class="button ghost compact" :class="{ 'is-active': state.createMode === 'template' }" type="button" @click="openCreateMenu('template')">Blank Template</button>
            <button class="button ghost compact" :class="{ 'is-active': state.createMode === 'import' }" type="button" @click="openCreateMenu('import')">Import From File</button>
          </div>

          <div v-if="state.createMode === 'template'" class="form-grid profile-create-grid">
            <label class="field">
              <span>Profile ID</span>
              <input v-model="state.createProfileId" class="input" type="text" placeholder="New Profile Name" />
            </label>

            <div class="actions-row align-end">
              <button class="icon-button primary" type="button" :disabled="state.saving" aria-label="Create Profile" title="Create Profile" @click="createProfile">
                <AppIcon name="plus" />
              </button>
            </div>
          </div>

          <div v-if="state.createMode === 'import'" class="form-grid profile-create-grid">
            <label class="field">
              <span>Target Profile ID</span>
              <input v-model="state.uploadProfileId" class="input" type="text" placeholder="Optional Profile Name" />
            </label>

            <label class="field">
              <span>Resume File</span>
              <input ref="fileInput" class="input file-input" type="file" accept=".pdf,.docx" />
            </label>

            <label class="checkbox-row">
              <input v-model="state.overwriteUpload" type="checkbox" />
              <span>Overwrite If Profile Already Exists</span>
            </label>

            <div class="actions-row align-end">
              <button class="icon-button primary" type="button" :disabled="state.uploading" aria-label="Import Profile" title="Import Profile" @click="uploadProfileFromFile">
                <AppIcon name="upload" />
              </button>
            </div>
          </div>
        </div>

        <div v-if="profiles.length" class="profile-library-grid">
          <article v-for="profile in profiles" :key="profile.id" class="profile-library-card">
            <div class="profile-library-head">
              <div>
                <strong>{{ profile.name }}</strong>
                <div class="muted-inline">{{ profile.path }}</div>
              </div>
              <Badge :variant="profile.is_active ? 'success' : 'secondary'">
                {{ profile.is_active ? 'Selected' : 'Stored' }}
              </Badge>
            </div>

            <div class="muted-inline">Updated {{ formatUpdatedAt(profile.updated_at) }}</div>

            <div v-if="state.renameTargetId === profile.id" class="form-grid">
              <label class="field">
                <span>New id</span>
                <input v-model="state.renameValue" class="input" type="text" />
              </label>

              <div class="actions-row">
                <Button variant="default" size="icon" type="button" :disabled="state.renaming" aria-label="Save Rename" title="Save Rename" @click="renameProfile(profile.id)">
                  <Save class="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" type="button" aria-label="Cancel Rename" title="Cancel Rename" @click="cancelRename">
                  <X class="h-4 w-4" />
                </Button>
              </div>
            </div>

            <div v-else class="actions-row">
              <Button variant="ghost" size="icon" type="button" aria-label="Edit Profile" title="Edit Profile" @click="openProfileEditor(profile.id)">
                <Pencil class="h-4 w-4" />
              </Button>
              <Button :variant="profile.is_active ? 'default' : 'ghost'" size="icon" type="button" aria-label="Select Profile" title="Select Profile" @click="activateProfile(profile.id)">
                <Check class="h-4 w-4" />
              </Button>
              <Button variant="ghost" size="icon" type="button" aria-label="Rename Profile" title="Rename Profile" @click="startRename(profile)">
                <AppIcon name="rename" />
              </Button>
              <Button variant="ghost" size="icon" type="button" class="text-destructive hover:bg-destructive/10 hover:text-destructive" :disabled="state.deleting" aria-label="Delete Profile" title="Delete Profile" @click="deleteProfile(profile.id)">
                <Trash2 class="h-4 w-4" />
              </Button>
            </div>
          </article>
        </div>
        <EmptyState v-else title="No profiles yet" description="Create a blank template or import a resume to get started.">
          <template #icon><UserCircle /></template>
          <template #action>
            <Button type="button" size="sm" @click="openCreateMenu()">
              <Plus class="h-4 w-4" />
              New profile
            </Button>
          </template>
        </EmptyState>
        </CardContent>
      </Card>
    </template>

    <template v-else-if="!state.loading && isEditingView">
      <Card v-if="!state.data.has_profile" class="surface-narrow" :class="{ 'is-loading': state.loading }">
        <CardHeader class="flex flex-row items-center justify-between space-y-0">
          <CardTitle class="text-sm">Profile not found</CardTitle>
          <Button variant="ghost" size="icon" type="button" aria-label="Back To Profiles" title="Back To Profiles" @click="goToLibrary">
            <ArrowLeft class="h-4 w-4" />
          </Button>
        </CardHeader>
        <CardContent>
          <EmptyState title="The selected profile does not exist" description="Return to the library to pick another profile or create a new one.">
            <template #icon><UserCircle /></template>
          </EmptyState>
        </CardContent>
      </Card>

      <Card v-else class="profile-editor-shell" :class="{ 'is-loading': state.loading }">
        <CardHeader class="flex flex-row items-start justify-between space-y-0">
          <div class="space-y-1">
            <CardTitle class="flex items-center gap-2 text-sm">
              <UserCircle class="h-4 w-4 text-muted-foreground" />
              {{ currentProfileId }}
            </CardTitle>
            <p class="text-xs text-muted-foreground">{{ state.data.profile_path }}</p>
          </div>
          <div class="actions-row">
            <Button variant="ghost" size="icon" type="button" aria-label="Back To Profiles" title="Back To Profiles" @click="goToLibrary">
              <ArrowLeft class="h-4 w-4" />
            </Button>
            <Button :variant="state.data.active_profile_id === currentProfileId ? 'default' : 'ghost'" size="icon" type="button" aria-label="Select Profile" title="Select Profile" @click="activateProfile(currentProfileId)">
              <Check class="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" type="button" class="text-destructive hover:bg-destructive/10 hover:text-destructive" :disabled="state.deleting" aria-label="Delete Profile" title="Delete Profile" @click="deleteProfile(currentProfileId)">
              <Trash2 class="h-4 w-4" />
            </Button>
            <Button variant="default" size="icon" type="button" :disabled="state.saving" aria-label="Save Profile" title="Save Profile" @click="saveProfile">
              <Save class="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent>

        <div class="page-stack">
          <section class="editor-section accordion-section">
            <button class="accordion-head" type="button" @click="toggleSection('identity')">
              <div>
                <strong>Identity</strong>
                <div class="muted-inline">{{ sectionLabel('identity') }}</div>
              </div>
              <span class="accordion-icon"><AppIcon :name="state.sections.identity ? 'chevron-down' : 'chevron-right'" /></span>
            </button>

            <div v-if="state.sections.identity" class="accordion-body">
              <div class="form-grid form-grid-4">
                <label class="field"><span>Name</span><input v-model="state.editor.identity.full_name" class="input" type="text" /></label>
                <label class="field"><span>Email</span><input v-model="state.editor.identity.email" class="input" type="email" /></label>
                <label class="field"><span>Phone</span><input v-model="state.editor.identity.phone" class="input" type="text" /></label>
                <label class="field"><span>Location</span><input v-model="state.editor.identity.location" class="input" type="text" /></label>
                <label class="field field-span-2"><span>LinkedIn</span><input v-model="state.editor.identity.linkedin_url" class="input" type="url" /></label>
                <label class="field field-span-2"><span>GitHub</span><input v-model="state.editor.identity.github_url" class="input" type="url" /></label>
                <label class="field field-span-full"><span>Portfolio</span><input v-model="state.editor.identity.portfolio_url" class="input" type="url" /></label>
              </div>
            </div>
          </section>

          <section class="editor-section accordion-section">
            <button class="accordion-head" type="button" @click="toggleSection('education')">
              <div>
                <strong>Education</strong>
                <div class="muted-inline">{{ sectionLabel('education') }}</div>
              </div>
              <span class="accordion-icon"><AppIcon :name="state.sections.education ? 'chevron-down' : 'chevron-right'" /></span>
            </button>

            <div v-if="state.sections.education" class="accordion-body">
              <div class="section-head compact-head">
                <h2>Education Entries</h2>
                <button class="icon-button" type="button" aria-label="Add education" title="Add education" @click="addEducation"><AppIcon name="plus" /></button>
              </div>

              <div v-if="state.editor.education.length" class="editor-stack">
                <article v-for="(item, index) in state.editor.education" :key="item.id" class="editor-card">
                  <div class="editor-card-head">
                    <button class="editor-item-head" type="button" @click="toggleItem(item)">
                      <div>
                        <strong>{{ educationEntryLabel(item, index) }}</strong>
                        <div class="muted-inline">{{ summaryLine([item.degree, item.field, item.start_date || item.end_date ? `${item.start_date || '?'} - ${item.end_date || 'Present'}` : '']) }}</div>
                      </div>
                      <span class="accordion-icon"><AppIcon :name="item.expanded ? 'chevron-down' : 'chevron-right'" /></span>
                    </button>
                    <button class="icon-button danger" type="button" aria-label="Delete education" title="Delete education" @click="removeEducation(index)"><AppIcon name="trash" /></button>
                  </div>

                  <div v-if="item.expanded" class="editor-item-body">
                    <div class="editor-grid editor-grid-2">
                    <label class="field"><span>Institution</span><input v-model="item.institution" class="input" type="text" /></label>
                    <label class="field"><span>Degree</span><input v-model="item.degree" class="input" type="text" /></label>
                    <label class="field"><span>Field</span><input v-model="item.field" class="input" type="text" /></label>
                    <label class="field"><span>Location</span><input v-model="item.location" class="input" type="text" /></label>
                    <label class="field"><span>Start</span><input v-model="item.start_date" class="input" type="text" placeholder="YYYY-MM" /></label>
                    <label class="field"><span>End</span><input v-model="item.end_date" class="input" type="text" placeholder="YYYY-MM Or Present" /></label>
                    <label class="field"><span>GPA</span><input v-model="item.gpa" class="input" type="text" /></label>
                    </div>

                    <div class="editor-subsection">
                      <div class="section-head compact-head">
                        <h2>Relevant Courses</h2>
                        <button class="icon-button" type="button" aria-label="Add course" title="Add course" @click="addCourse(index)"><AppIcon name="plus" /></button>
                      </div>

                      <div v-if="item.relevant_courses.length" class="editor-stack">
                        <div v-for="(course, courseIndex) in item.relevant_courses" :key="course.id" class="editor-mini-card">
                          <div class="editor-grid editor-grid-2">
                            <label class="field"><span>Course</span><input v-model="course.name" class="input" type="text" /></label>
                            <label class="field"><span>Tags</span><TagInput v-model="course.tags" placeholder="Python, Systems" /></label>
                          </div>
                          <div class="actions-row">
                            <button class="icon-button danger" type="button" aria-label="Delete course" title="Delete course" @click="removeCourse(index, courseIndex)"><AppIcon name="trash" /></button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </article>
              </div>
              <div v-else class="empty-state">No Education Entries</div>
            </div>
          </section>

          <section class="editor-section accordion-section">
            <button class="accordion-head" type="button" @click="toggleSection('experience')">
              <div>
                <strong>Experience</strong>
                <div class="muted-inline">{{ sectionLabel('experience') }}</div>
              </div>
              <span class="accordion-icon"><AppIcon :name="state.sections.experience ? 'chevron-down' : 'chevron-right'" /></span>
            </button>

            <div v-if="state.sections.experience" class="accordion-body">
              <div class="section-head compact-head">
                <h2>Work Experiences</h2>
                <button class="icon-button" type="button" aria-label="Add experience" title="Add experience" @click="addExperience"><AppIcon name="plus" /></button>
              </div>

              <div v-if="state.editor.work_experiences.length" class="editor-stack">
                <article v-for="(item, index) in state.editor.work_experiences" :key="item.id" class="editor-card">
                  <div class="editor-card-head">
                    <button class="editor-item-head" type="button" @click="toggleItem(item)">
                      <div>
                        <strong>{{ experienceEntryLabel(item, index) }}</strong>
                        <div class="muted-inline">{{ summaryLine([item.title, item.location, item.start_date || item.end_date ? `${item.start_date || '?'} - ${item.end_date || 'Present'}` : '']) }}</div>
                      </div>
                      <span class="accordion-icon"><AppIcon :name="item.expanded ? 'chevron-down' : 'chevron-right'" /></span>
                    </button>
                    <button class="icon-button danger" type="button" aria-label="Delete experience" title="Delete experience" @click="removeExperience(index)"><AppIcon name="trash" /></button>
                  </div>

                  <div v-if="item.expanded" class="editor-item-body">
                    <div class="editor-grid editor-grid-2">
                    <label class="field"><span>Company</span><input v-model="item.company" class="input" type="text" /></label>
                    <label class="field"><span>Title</span><input v-model="item.title" class="input" type="text" /></label>
                    <label class="field"><span>Location</span><input v-model="item.location" class="input" type="text" /></label>
                    <label class="field"><span>Start</span><input v-model="item.start_date" class="input" type="text" placeholder="YYYY-MM" /></label>
                    <label class="field"><span>End</span><input v-model="item.end_date" class="input" type="text" placeholder="YYYY-MM Or Present" /></label>
                    </div>

                    <div class="editor-subsection">
                      <div class="section-head compact-head">
                        <h2>Bullets</h2>
                        <button class="icon-button" type="button" aria-label="Add bullet" title="Add bullet" @click="addExperienceBullet(index)"><AppIcon name="plus" /></button>
                      </div>

                      <div v-if="item.bullets.length" class="editor-stack">
                        <div v-for="(bullet, bulletIndex) in item.bullets" :key="bullet.id" class="editor-mini-card">
                          <div class="editor-card-head">
                            <button class="editor-item-head" type="button" @click="toggleItem(bullet)">
                              <div>
                                <strong>Bullet {{ bulletIndex + 1 }}</strong>
                                <div class="muted-inline">{{ bulletLabel(bullet, bulletIndex) }}</div>
                              </div>
                              <span class="accordion-icon"><AppIcon :name="bullet.expanded ? 'chevron-down' : 'chevron-right'" /></span>
                            </button>
                            <button class="icon-button danger" type="button" aria-label="Delete bullet" title="Delete bullet" @click="removeExperienceBullet(index, bulletIndex)"><AppIcon name="trash" /></button>
                          </div>

                          <div v-if="bullet.expanded" class="editor-item-body">
                            <label class="field"><span>Bullet</span><textarea v-model="bullet.text" class="input textarea editor-textarea" rows="3"></textarea></label>
                            <label class="field"><span>Tags</span><TagInput v-model="bullet.tags" placeholder="Python, Distributed Systems" /></label>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </article>
              </div>
              <div v-else class="empty-state">No Work Experiences</div>
            </div>
          </section>

          <section class="editor-section accordion-section">
            <button class="accordion-head" type="button" @click="toggleSection('projects')">
              <div>
                <strong>Projects</strong>
                <div class="muted-inline">{{ sectionLabel('projects') }}</div>
              </div>
              <span class="accordion-icon"><AppIcon :name="state.sections.projects ? 'chevron-down' : 'chevron-right'" /></span>
            </button>

            <div v-if="state.sections.projects" class="accordion-body">
              <div class="section-head compact-head">
                <h2>Projects</h2>
                <button class="icon-button" type="button" aria-label="Add project" title="Add project" @click="addProject"><AppIcon name="plus" /></button>
              </div>

              <div v-if="state.editor.projects.length" class="editor-stack">
                <article v-for="(item, index) in state.editor.projects" :key="item.id" class="editor-card">
                  <div class="editor-card-head">
                    <button class="editor-item-head" type="button" @click="toggleItem(item)">
                      <div>
                        <strong>{{ projectEntryLabel(item, index) }}</strong>
                        <div class="muted-inline">{{ summaryLine([item.role, item.tech_stack.length ? `${item.tech_stack.length} tech tags` : '', item.links.length ? `${item.links.length} links` : '']) }}</div>
                      </div>
                      <span class="accordion-icon"><AppIcon :name="item.expanded ? 'chevron-down' : 'chevron-right'" /></span>
                    </button>
                    <button class="icon-button danger" type="button" aria-label="Delete project" title="Delete project" @click="removeProject(index)"><AppIcon name="trash" /></button>
                  </div>

                  <div v-if="item.expanded" class="editor-item-body">
                    <div class="editor-grid editor-grid-2">
                    <label class="field"><span>Name</span><input v-model="item.name" class="input" type="text" /></label>
                    <label class="field"><span>Role</span><input v-model="item.role" class="input" type="text" /></label>
                    <label class="field field-span-full"><span>Description</span><textarea v-model="item.description" class="input textarea editor-textarea" rows="3"></textarea></label>
                    <label class="field field-span-full"><span>Tech Stack</span><TagInput v-model="item.tech_stack" placeholder="Vue, FastAPI, Postgres" /></label>
                    <label class="field field-span-full"><span>Links</span><TagInput v-model="item.links" placeholder="https://github.com/user/repo" /></label>
                    </div>

                    <div class="editor-subsection">
                      <div class="section-head compact-head">
                        <h2>Bullets</h2>
                        <button class="icon-button" type="button" aria-label="Add bullet" title="Add bullet" @click="addProjectBullet(index)"><AppIcon name="plus" /></button>
                      </div>

                      <div v-if="item.bullets.length" class="editor-stack">
                        <div v-for="(bullet, bulletIndex) in item.bullets" :key="bullet.id" class="editor-mini-card">
                          <div class="editor-card-head">
                            <button class="editor-item-head" type="button" @click="toggleItem(bullet)">
                              <div>
                                <strong>Bullet {{ bulletIndex + 1 }}</strong>
                                <div class="muted-inline">{{ bulletLabel(bullet, bulletIndex) }}</div>
                              </div>
                              <span class="accordion-icon"><AppIcon :name="bullet.expanded ? 'chevron-down' : 'chevron-right'" /></span>
                            </button>
                            <button class="icon-button danger" type="button" aria-label="Delete bullet" title="Delete bullet" @click="removeProjectBullet(index, bulletIndex)"><AppIcon name="trash" /></button>
                          </div>

                          <div v-if="bullet.expanded" class="editor-item-body">
                            <label class="field"><span>Bullet</span><textarea v-model="bullet.text" class="input textarea editor-textarea" rows="3"></textarea></label>
                            <label class="field"><span>Tags</span><TagInput v-model="bullet.tags" placeholder="Frontend, Analytics" /></label>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </article>
              </div>
              <div v-else class="empty-state">No Projects</div>
            </div>
          </section>

          <section class="editor-section accordion-section">
            <button class="accordion-head" type="button" @click="toggleSection('skills')">
              <div>
                <strong>Skills</strong>
                <div class="muted-inline">{{ sectionLabel('skills') }}</div>
              </div>
              <span class="accordion-icon"><AppIcon :name="state.sections.skills ? 'chevron-down' : 'chevron-right'" /></span>
            </button>

            <div v-if="state.sections.skills" class="accordion-body">
                <div class="section-head compact-head">
                  <h2>Skill Categories</h2>
                  <button class="icon-button" type="button" aria-label="Add skill category" title="Add skill category" @click="addSkillCategory"><AppIcon name="plus" /></button>
                </div>

                <div class="editor-stack">
                  <div v-for="(entry, index) in state.editor.skills" :key="entry.id" class="editor-mini-card">
                  <div class="editor-card-head">
                    <button class="editor-item-head" type="button" @click="toggleItem(entry)">
                      <div>
                        <strong>{{ skillEntryLabel(entry) }}</strong>
                        <div class="muted-inline">{{ entry.values.length }} tags</div>
                      </div>
                      <span class="accordion-icon"><AppIcon :name="entry.expanded ? 'chevron-down' : 'chevron-right'" /></span>
                    </button>
                    <button v-if="!defaultSkillCategories.includes(slugifyCategory(entry.key))" class="icon-button danger" type="button" aria-label="Delete category" title="Delete category" @click="removeSkillCategory(index)"><AppIcon name="trash" /></button>
                  </div>

                  <div v-if="entry.expanded" class="editor-item-body">
                    <label class="field"><span>Category</span><input v-model="entry.key" class="input" type="text" placeholder="Custom Category" /></label>
                    <label class="field"><span>Values</span><TagInput v-model="entry.values" placeholder="Python, SQL, React" /></label>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
        </CardContent>
      </Card>
    </template>
  </div>
</template>
