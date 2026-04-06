<script setup>
import { computed, onMounted, reactive, ref } from "vue"

import TagInput from "../components/TagInput.vue"
import { api } from "../lib/api"

const fileInput = ref(null)

const defaultSkillCategories = ["languages", "frameworks", "databases", "tools", "domains"]
let localId = 0

const state = reactive({
  loading: true,
  saving: false,
  uploading: false,
  deleting: false,
  error: "",
  message: "",
  createProfileId: "",
  uploadProfileId: "",
  overwriteUpload: false,
  newSkillCategory: "",
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
})

const currentProfileId = computed(
  () => state.data.selected_profile_id || state.data.active_profile_id || "",
)
const profiles = computed(() => state.data.profiles || [])
const isDirty = computed(() => profileFingerprint(state.editor) !== state.loadedFingerprint)

async function load(profileId = "") {
  state.loading = true
  state.error = ""

  try {
    state.data = await api.profile(profileId)
    syncEditorFromProfile(state.data.profile)
  } catch (error) {
    state.error = error.message
  } finally {
    state.loading = false
  }
}

function syncEditorFromProfile(profile) {
  state.editor = toEditorProfile(profile)
  state.uploadProfileId = currentProfileId.value || ""
  state.loadedFingerprint = profileFingerprint(state.editor)
}

async function createProfile() {
  if (!state.createProfileId.trim()) {
    state.error = "Profile id is required."
    return
  }

  if (!confirmDiscardChanges("Create a new profile")) {
    return
  }

  state.saving = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.createProfile(state.createProfileId.trim(), true)
    state.createProfileId = ""
    state.message = state.data.message || "Created"
    syncEditorFromProfile(state.data.profile)
  } catch (error) {
    state.error = error.message
  } finally {
    state.saving = false
  }
}

async function activateProfile(profileId) {
  if (profileId === currentProfileId.value) {
    return
  }

  if (!confirmDiscardChanges("Switch profiles")) {
    return
  }

  state.saving = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.activateProfile(profileId)
    state.message = state.data.message || "Activated"
    syncEditorFromProfile(state.data.profile)
  } catch (error) {
    state.error = error.message
  } finally {
    state.saving = false
  }
}

async function saveProfile() {
  if (!currentProfileId.value) {
    state.error = "Create or select a profile first."
    return
  }

  state.saving = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.saveProfile(
      currentProfileId.value,
      serializeEditorProfile(state.editor),
      true,
    )
    state.message = state.data.message || "Saved"
    syncEditorFromProfile(state.data.profile)
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
    syncEditorFromProfile(state.data.profile)
  } catch (error) {
    state.error = error.message
  } finally {
    state.deleting = false
  }
}

async function upload() {
  const file = fileInput.value?.files?.[0]
  if (!file) {
    return
  }

  if (!confirmDiscardChanges("Uploading a resume")) {
    return
  }

  state.uploading = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.uploadResume(file, {
      profileId: state.uploadProfileId.trim() || currentProfileId.value,
      overwrite: state.overwriteUpload,
      setActive: true,
    })
    state.message = state.data.message || "Parsed"
    state.overwriteUpload = false
    fileInput.value.value = ""
    syncEditorFromProfile(state.data.profile)
  } catch (error) {
    state.error = error.message
  } finally {
    state.uploading = false
  }
}

function addEducation() {
  state.editor.education.push(emptyEducation())
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
  state.editor.work_experiences.push(emptyExperience())
}

function removeExperience(index) {
  state.editor.work_experiences.splice(index, 1)
}

function addExperienceBullet(experienceIndex) {
  state.editor.work_experiences[experienceIndex].bullets.push(emptyBullet())
}

function removeExperienceBullet(experienceIndex, bulletIndex) {
  state.editor.work_experiences[experienceIndex].bullets.splice(bulletIndex, 1)
}

function addProject() {
  state.editor.projects.push(emptyProject())
}

function removeProject(index) {
  state.editor.projects.splice(index, 1)
}

function addProjectBullet(projectIndex) {
  state.editor.projects[projectIndex].bullets.push(emptyBullet())
}

function removeProjectBullet(projectIndex, bulletIndex) {
  state.editor.projects[projectIndex].bullets.splice(bulletIndex, 1)
}

function addSkillCategory() {
  const key = slugifyCategory(state.newSkillCategory)
  if (!key) {
    state.error = "Skill category name is required."
    return
  }

  if (state.editor.skills.some((entry) => slugifyCategory(entry.key) === key)) {
    state.error = `Skill category '${key}' already exists.`
    return
  }

  state.editor.skills.push({ id: makeId("skill"), key, values: [] })
  state.newSkillCategory = ""
  state.error = ""
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
    name: "",
    role: "",
    description: "",
    tech_stack: [],
    bullets: [],
  }
}

function emptyBullet() {
  return {
    id: makeId("bullet"),
    text: "",
    tags: [],
  }
}

function toEducationEditor(item) {
  return {
    id: makeId("education"),
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
    company: item.company || "",
    title: item.title || "",
    location: item.location || "",
    start_date: item.start_date || "",
    end_date: item.end_date || "",
    bullets: Array.isArray(item.bullets)
      ? item.bullets.map((bullet) => ({
          id: makeId("bullet"),
          text: typeof bullet === "string" ? bullet : bullet?.text || "",
          tags:
            typeof bullet === "object" ? normalizeStringArray(bullet?.tags) : [],
        }))
      : [],
  }
}

function toProjectEditor(item) {
  return {
    id: makeId("project"),
    name: item.name || "",
    role: item.role || "",
    description: item.description || "",
    tech_stack: normalizeStringArray(item.tech_stack),
    bullets: Array.isArray(item.bullets)
      ? item.bullets.map((bullet) => ({
          id: makeId("bullet"),
          text: typeof bullet === "string" ? bullet : bullet?.text || "",
          tags:
            typeof bullet === "object" ? normalizeStringArray(bullet?.tags) : [],
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

function prettifyKey(value) {
  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
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

function makeId(prefix) {
  localId += 1
  return `${prefix}-${localId}`
}

onMounted(() => load())
</script>

<template>
  <div class="page-stack">
    <div v-if="state.loading" class="empty-state">Loading</div>
    <div v-if="state.error" class="banner is-danger">{{ state.error }}</div>
    <div v-if="state.message" class="banner is-success">{{ state.message }}</div>

    <template v-if="!state.loading">
      <section class="content-grid content-grid-wide profile-admin-grid">
        <article class="surface">
          <div class="section-head">
            <h2>Profiles</h2>
            <span class="muted">{{ profiles.length }}</span>
          </div>

          <div class="page-stack">
            <div class="list-stack">
              <button
                v-for="profile in profiles"
                :key="profile.id"
                class="list-row profile-row-button"
                type="button"
                @click="activateProfile(profile.id)"
              >
                <div>
                  <strong>{{ profile.name }}</strong>
                  <div class="muted-inline">{{ profile.path }}</div>
                </div>
                <span class="chip" :class="{ success: profile.is_active }">
                  {{ profile.is_active ? "Active" : "Open" }}
                </span>
              </button>
            </div>

            <div class="form-grid">
              <label class="field">
                <span>New profile id</span>
                <input v-model="state.createProfileId" class="input" type="text" placeholder="new-profile" />
              </label>

              <div class="actions-row">
                <button class="button" type="button" :disabled="state.saving" @click="createProfile">
                  {{ state.saving ? "Working" : "Create" }}
                </button>
              </div>
            </div>

            <div class="form-grid">
              <label class="field">
                <span>Upload resume target</span>
                <input
                  v-model="state.uploadProfileId"
                  class="input"
                  type="text"
                  :placeholder="currentProfileId || 'default or new-profile'"
                />
              </label>

              <label class="field">
                <span>Resume file</span>
                <input ref="fileInput" class="input file-input" type="file" accept=".pdf,.docx" />
              </label>

              <label class="checkbox-row">
                <input v-model="state.overwriteUpload" type="checkbox" />
                <span>Overwrite if profile already exists</span>
              </label>

              <div class="actions-row">
                <button class="button" type="button" :disabled="state.uploading" @click="upload">
                  {{ state.uploading ? "Parsing" : "Upload" }}
                </button>
              </div>
            </div>
          </div>
        </article>

        <article class="surface">
          <div class="section-head">
            <h2>Editor</h2>
            <div class="actions-row">
              <span v-if="currentProfileId" class="chip success">{{ currentProfileId }}</span>
              <button
                v-if="currentProfileId"
                class="button ghost compact"
                type="button"
                :disabled="state.deleting"
                @click="deleteProfile(currentProfileId)"
              >
                Delete
              </button>
              <button class="button compact" type="button" :disabled="state.saving" @click="saveProfile">
                {{ state.saving ? "Saving" : "Save" }}
              </button>
            </div>
          </div>

          <div class="page-stack">
            <section class="editor-section">
              <div class="section-head compact-head">
                <h2>Identity</h2>
              </div>

              <div class="form-grid form-grid-4">
                <label class="field">
                  <span>Name</span>
                  <input v-model="state.editor.identity.full_name" class="input" type="text" />
                </label>
                <label class="field">
                  <span>Email</span>
                  <input v-model="state.editor.identity.email" class="input" type="email" />
                </label>
                <label class="field">
                  <span>Phone</span>
                  <input v-model="state.editor.identity.phone" class="input" type="text" />
                </label>
                <label class="field">
                  <span>Location</span>
                  <input v-model="state.editor.identity.location" class="input" type="text" />
                </label>
                <label class="field field-span-2">
                  <span>LinkedIn</span>
                  <input v-model="state.editor.identity.linkedin_url" class="input" type="url" />
                </label>
                <label class="field field-span-2">
                  <span>GitHub</span>
                  <input v-model="state.editor.identity.github_url" class="input" type="url" />
                </label>
                <label class="field field-span-full">
                  <span>Portfolio</span>
                  <input v-model="state.editor.identity.portfolio_url" class="input" type="url" />
                </label>
              </div>
            </section>

            <section class="editor-section">
              <div class="section-head compact-head">
                <h2>Education</h2>
                <button class="button ghost compact" type="button" @click="addEducation">Add</button>
              </div>

              <div v-if="state.editor.education.length" class="editor-stack">
                <article v-for="(item, index) in state.editor.education" :key="item.id" class="editor-card">
                  <div class="editor-card-head">
                    <strong>Education {{ index + 1 }}</strong>
                    <button class="button ghost compact" type="button" @click="removeEducation(index)">Remove</button>
                  </div>

                  <div class="editor-grid editor-grid-2">
                    <label class="field"><span>Institution</span><input v-model="item.institution" class="input" type="text" /></label>
                    <label class="field"><span>Degree</span><input v-model="item.degree" class="input" type="text" /></label>
                    <label class="field"><span>Field</span><input v-model="item.field" class="input" type="text" /></label>
                    <label class="field"><span>Location</span><input v-model="item.location" class="input" type="text" /></label>
                    <label class="field"><span>Start</span><input v-model="item.start_date" class="input" type="text" placeholder="YYYY-MM" /></label>
                    <label class="field"><span>End</span><input v-model="item.end_date" class="input" type="text" placeholder="YYYY-MM or Present" /></label>
                    <label class="field"><span>GPA</span><input v-model="item.gpa" class="input" type="text" /></label>
                  </div>

                  <div class="editor-subsection">
                    <div class="section-head compact-head">
                      <h2>Relevant Courses</h2>
                      <button class="button ghost compact" type="button" @click="addCourse(index)">Add</button>
                    </div>

                    <div v-if="item.relevant_courses.length" class="editor-stack">
                      <div v-for="(course, courseIndex) in item.relevant_courses" :key="course.id" class="editor-mini-card">
                        <div class="editor-grid editor-grid-2">
                          <label class="field"><span>Course</span><input v-model="course.name" class="input" type="text" /></label>
                          <label class="field"><span>Tags</span><TagInput v-model="course.tags" placeholder="python, systems" /></label>
                        </div>
                        <div class="actions-row">
                          <button class="button ghost compact" type="button" @click="removeCourse(index, courseIndex)">Remove course</button>
                        </div>
                      </div>
                    </div>
                  </div>
                </article>
              </div>
              <div v-else class="empty-state">No education entries</div>
            </section>

            <section class="editor-section">
              <div class="section-head compact-head">
                <h2>Experience</h2>
                <button class="button ghost compact" type="button" @click="addExperience">Add</button>
              </div>

              <div v-if="state.editor.work_experiences.length" class="editor-stack">
                <article v-for="(item, index) in state.editor.work_experiences" :key="item.id" class="editor-card">
                  <div class="editor-card-head">
                    <strong>Experience {{ index + 1 }}</strong>
                    <button class="button ghost compact" type="button" @click="removeExperience(index)">Remove</button>
                  </div>

                  <div class="editor-grid editor-grid-2">
                    <label class="field"><span>Company</span><input v-model="item.company" class="input" type="text" /></label>
                    <label class="field"><span>Title</span><input v-model="item.title" class="input" type="text" /></label>
                    <label class="field"><span>Location</span><input v-model="item.location" class="input" type="text" /></label>
                    <label class="field"><span>Start</span><input v-model="item.start_date" class="input" type="text" placeholder="YYYY-MM" /></label>
                    <label class="field"><span>End</span><input v-model="item.end_date" class="input" type="text" placeholder="YYYY-MM or Present" /></label>
                  </div>

                  <div class="editor-subsection">
                    <div class="section-head compact-head">
                      <h2>Bullets</h2>
                      <button class="button ghost compact" type="button" @click="addExperienceBullet(index)">Add</button>
                    </div>

                    <div v-if="item.bullets.length" class="editor-stack">
                      <div v-for="(bullet, bulletIndex) in item.bullets" :key="bullet.id" class="editor-mini-card">
                        <label class="field"><span>Bullet</span><textarea v-model="bullet.text" class="input textarea editor-textarea" rows="3"></textarea></label>
                        <label class="field"><span>Tags</span><TagInput v-model="bullet.tags" placeholder="python, distributed_systems" /></label>
                        <div class="actions-row">
                          <button class="button ghost compact" type="button" @click="removeExperienceBullet(index, bulletIndex)">Remove bullet</button>
                        </div>
                      </div>
                    </div>
                  </div>
                </article>
              </div>
              <div v-else class="empty-state">No work experiences</div>
            </section>

            <section class="editor-section">
              <div class="section-head compact-head">
                <h2>Projects</h2>
                <button class="button ghost compact" type="button" @click="addProject">Add</button>
              </div>

              <div v-if="state.editor.projects.length" class="editor-stack">
                <article v-for="(item, index) in state.editor.projects" :key="item.id" class="editor-card">
                  <div class="editor-card-head">
                    <strong>Project {{ index + 1 }}</strong>
                    <button class="button ghost compact" type="button" @click="removeProject(index)">Remove</button>
                  </div>

                  <div class="editor-grid editor-grid-2">
                    <label class="field"><span>Name</span><input v-model="item.name" class="input" type="text" /></label>
                    <label class="field"><span>Role</span><input v-model="item.role" class="input" type="text" /></label>
                    <label class="field field-span-full"><span>Description</span><textarea v-model="item.description" class="input textarea editor-textarea" rows="3"></textarea></label>
                    <label class="field field-span-full"><span>Tech stack</span><TagInput v-model="item.tech_stack" placeholder="vue, fastapi, postgres" /></label>
                  </div>

                  <div class="editor-subsection">
                    <div class="section-head compact-head">
                      <h2>Bullets</h2>
                      <button class="button ghost compact" type="button" @click="addProjectBullet(index)">Add</button>
                    </div>

                    <div v-if="item.bullets.length" class="editor-stack">
                      <div v-for="(bullet, bulletIndex) in item.bullets" :key="bullet.id" class="editor-mini-card">
                        <label class="field"><span>Bullet</span><textarea v-model="bullet.text" class="input textarea editor-textarea" rows="3"></textarea></label>
                        <label class="field"><span>Tags</span><TagInput v-model="bullet.tags" placeholder="frontend, analytics" /></label>
                        <div class="actions-row">
                          <button class="button ghost compact" type="button" @click="removeProjectBullet(index, bulletIndex)">Remove bullet</button>
                        </div>
                      </div>
                    </div>
                  </div>
                </article>
              </div>
              <div v-else class="empty-state">No projects</div>
            </section>

            <section class="editor-section">
              <div class="section-head compact-head">
                <h2>Skills</h2>
                <div class="actions-row">
                  <input v-model="state.newSkillCategory" class="input compact-input" type="text" placeholder="custom_category" />
                  <button class="button ghost compact" type="button" @click="addSkillCategory">Add</button>
                </div>
              </div>

              <div class="editor-stack">
                <div v-for="(entry, index) in state.editor.skills" :key="entry.id" class="editor-mini-card">
                  <div class="editor-grid editor-grid-2 editor-grid-skill">
                    <label class="field"><span>Category</span><input v-model="entry.key" class="input" type="text" /></label>
                    <label class="field"><span>Values</span><TagInput v-model="entry.values" placeholder="python, sql, react" /></label>
                  </div>
                  <div class="actions-row" v-if="!defaultSkillCategories.includes(slugifyCategory(entry.key))">
                    <button class="button ghost compact" type="button" @click="removeSkillCategory(index)">Remove category</button>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>
