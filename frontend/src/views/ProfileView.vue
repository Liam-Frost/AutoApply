<script setup>
import { computed, onMounted, reactive, ref } from "vue"

import { api } from "../lib/api"

const fileInput = ref(null)

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
  data: {
    has_profile: false,
    profile: null,
    profile_path: "",
    profiles: [],
    active_profile_id: "",
    selected_profile_id: "",
  },
  editor: emptyProfile(),
  sections: {
    education: "[]",
    work_experiences: "[]",
    projects: "[]",
    skills: "{}",
  },
})

const currentProfileId = computed(() => state.data.selected_profile_id || state.data.active_profile_id || "")
const profiles = computed(() => state.data.profiles || [])

async function load(profileId = "") {
  state.loading = true
  state.error = ""

  try {
    const suffix = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : ""
    state.data = await fetch(`/api/profile${suffix}`).then(async (response) => {
      const payload = await response.json()
      if (!response.ok) {
        throw new Error(payload.detail || response.statusText)
      }
      return payload
    })
    syncEditorFromProfile(state.data.profile)
  } catch (error) {
    state.error = error.message
  } finally {
    state.loading = false
  }
}

function syncEditorFromProfile(profile) {
  const normalized = normalizeProfile(profile)
  state.editor = normalized
  state.sections.education = JSON.stringify(normalized.education, null, 2)
  state.sections.work_experiences = JSON.stringify(normalized.work_experiences, null, 2)
  state.sections.projects = JSON.stringify(normalized.projects, null, 2)
  state.sections.skills = JSON.stringify(normalized.skills, null, 2)
}

async function createProfile() {
  if (!state.createProfileId.trim()) {
    state.error = "Profile id is required."
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
    const payload = {
      identity: { ...state.editor.identity },
      education: JSON.parse(state.sections.education || "[]"),
      work_experiences: JSON.parse(state.sections.work_experiences || "[]"),
      projects: JSON.parse(state.sections.projects || "[]"),
      skills: JSON.parse(state.sections.skills || "{}"),
    }

    state.data = await api.saveProfile(currentProfileId.value, payload, true)
    state.message = state.data.message || "Saved"
    syncEditorFromProfile(state.data.profile)
  } catch (error) {
    state.error = error.message.includes("JSON")
      ? `Invalid JSON: ${error.message}`
      : error.message
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

  state.uploading = true
  state.error = ""
  state.message = ""

  try {
    state.data = await api.uploadResume(file, {
      profileId: state.uploadProfileId.trim(),
      overwrite: state.overwriteUpload,
      setActive: true,
    })
    state.message = state.data.message || "Parsed"
    state.uploadProfileId = ""
    state.overwriteUpload = false
    fileInput.value.value = ""
    syncEditorFromProfile(state.data.profile)
  } catch (error) {
    state.error = error.message
  } finally {
    state.uploading = false
  }
}

function normalizeProfile(profile) {
  const base = emptyProfile()
  if (!profile) {
    return base
  }

  return {
    identity: { ...base.identity, ...(profile.identity || {}) },
    education: profile.education || [],
    work_experiences: profile.work_experiences || [],
    projects: profile.projects || [],
    skills: profile.skills || {},
  }
}

function emptyProfile() {
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
    skills: {},
  }
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
                <span>Upload resume to profile</span>
                <input v-model="state.uploadProfileId" class="input" type="text" placeholder="default or new-profile" />
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
            <section class="form-grid form-grid-4">
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
            </section>

            <label class="field">
              <span>Education JSON</span>
              <textarea v-model="state.sections.education" class="input textarea code-textarea" rows="8"></textarea>
            </label>

            <label class="field">
              <span>Work experiences JSON</span>
              <textarea v-model="state.sections.work_experiences" class="input textarea code-textarea" rows="10"></textarea>
            </label>

            <label class="field">
              <span>Projects JSON</span>
              <textarea v-model="state.sections.projects" class="input textarea code-textarea" rows="8"></textarea>
            </label>

            <label class="field">
              <span>Skills JSON</span>
              <textarea v-model="state.sections.skills" class="input textarea code-textarea" rows="8"></textarea>
            </label>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>
