<script setup>
import { computed, onMounted, reactive, ref } from "vue"

import { api } from "../lib/api"

const fileInput = ref(null)

const state = reactive({
  loading: true,
  uploading: false,
  error: "",
  message: "",
  data: {
    has_profile: false,
    profile: null,
    profile_path: "",
  },
})

const identity = computed(() => state.data.profile?.identity || {})
const skills = computed(() => Object.entries(state.data.profile?.skills || {}).filter(([, items]) => items?.length))
const education = computed(() => state.data.profile?.education || [])
const experiences = computed(() => state.data.profile?.work_experiences || [])
const projects = computed(() => state.data.profile?.projects || [])

async function load() {
  state.loading = true
  state.error = ""

  try {
    state.data = await api.profile()
  } catch (error) {
    state.error = error.message
  } finally {
    state.loading = false
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
    state.data = await api.uploadResume(file)
    state.message = state.data.message || "Parsed"
    fileInput.value.value = ""
  } catch (error) {
    state.error = error.message
  } finally {
    state.uploading = false
  }
}

function bulletText(item) {
  return typeof item === "string" ? item : item?.text || ""
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <div v-if="state.loading" class="empty-state">Loading</div>

    <div v-if="state.error" class="banner is-danger">{{ state.error }}</div>
    <div v-if="state.message" class="banner is-success">{{ state.message }}</div>

    <section v-if="!state.loading && !state.data.has_profile" class="surface surface-narrow">
      <div class="section-head">
        <h2>Resume</h2>
      </div>

      <form class="form-grid" @submit.prevent="upload">
        <label class="field">
          <span>File</span>
          <input ref="fileInput" class="input file-input" type="file" accept=".pdf,.docx" required />
        </label>

        <div class="actions-row">
          <button class="button" type="submit" :disabled="state.uploading">
            {{ state.uploading ? "Parsing" : "Parse" }}
          </button>
        </div>
      </form>
    </section>

    <template v-else-if="!state.loading">
      <section class="metric-grid">
        <article class="metric-card">
          <span class="metric-label">Education</span>
          <strong class="metric-value">{{ education.length }}</strong>
        </article>
        <article class="metric-card">
          <span class="metric-label">Experience</span>
          <strong class="metric-value">{{ experiences.length }}</strong>
        </article>
        <article class="metric-card">
          <span class="metric-label">Projects</span>
          <strong class="metric-value">{{ projects.length }}</strong>
        </article>
        <article class="metric-card">
          <span class="metric-label">Skills</span>
          <strong class="metric-value">{{ skills.length }}</strong>
        </article>
      </section>

      <section class="content-grid content-grid-wide">
        <article class="surface">
          <div class="section-head">
            <h2>Identity</h2>
          </div>

          <div class="profile-block">
            <strong class="profile-name">{{ identity.full_name || "Unknown" }}</strong>
            <div class="muted-text">{{ identity.location || state.data.profile_path }}</div>
            <div class="list-stack compact-list">
              <div v-if="identity.email" class="list-row"><span>Email</span><span>{{ identity.email }}</span></div>
              <div v-if="identity.phone" class="list-row"><span>Phone</span><span>{{ identity.phone }}</span></div>
              <div v-if="identity.linkedin_url" class="list-row"><span>LinkedIn</span><a :href="identity.linkedin_url" target="_blank" rel="noopener">Open</a></div>
              <div v-if="identity.github_url" class="list-row"><span>GitHub</span><a :href="identity.github_url" target="_blank" rel="noopener">Open</a></div>
            </div>
          </div>
        </article>

        <article v-if="skills.length" class="surface">
          <div class="section-head">
            <h2>Skills</h2>
          </div>

          <div class="category-list">
            <div v-for="[category, items] in skills" :key="category" class="category-block">
              <strong>{{ category }}</strong>
              <div class="chip-row">
                <span v-for="item in items" :key="item" class="chip">{{ item }}</span>
              </div>
            </div>
          </div>
        </article>
      </section>

      <section v-if="education.length" class="surface">
        <div class="section-head">
          <h2>Education</h2>
        </div>

        <div class="list-stack">
          <div v-for="item in education" :key="`${item.institution}-${item.degree}`" class="job-card">
            <strong>{{ item.degree }} {{ item.field }}</strong>
            <div class="muted-inline">{{ item.institution }}</div>
          </div>
        </div>
      </section>

      <section v-if="experiences.length" class="surface">
        <div class="section-head">
          <h2>Experience</h2>
        </div>

        <div class="list-stack">
          <div v-for="item in experiences" :key="`${item.company}-${item.title}`" class="job-card">
            <strong>{{ item.title }}</strong>
            <div class="muted-inline">{{ item.company }}</div>
            <ul v-if="item.bullets?.length" class="bullet-list">
              <li v-for="bullet in item.bullets" :key="bulletText(bullet)">{{ bulletText(bullet) }}</li>
            </ul>
          </div>
        </div>
      </section>

      <section v-if="projects.length" class="surface">
        <div class="section-head">
          <h2>Projects</h2>
        </div>

        <div class="list-stack">
          <div v-for="item in projects" :key="item.name" class="job-card">
            <strong>{{ item.name }}</strong>
            <div v-if="item.tech_stack?.length" class="chip-row">
              <span v-for="tech in item.tech_stack" :key="tech" class="chip">{{ tech }}</span>
            </div>
            <p v-if="item.description" class="muted-text">{{ item.description }}</p>
          </div>
        </div>
      </section>
    </template>

  </div>
</template>
