<script setup>
import { reactive } from "vue"

import { api } from "../lib/api"
import { formatPercent, truncateText } from "../lib/format"

const form = reactive({
  source: "ats",
  keyword: "",
  location: "",
  profile: "default",
  time_filter: "week",
  ats: "",
  company: "",
})

const state = reactive({
  searching: false,
  error: "",
  jobs: [],
  applyState: {},
})

async function search() {
  state.searching = true
  state.error = ""
  state.jobs = []

  try {
    const response = await api.searchJobs({ ...form })
    state.jobs = response.jobs
    state.error = response.error || ""
  } catch (error) {
    state.jobs = []
    state.error = error.message
  } finally {
    state.searching = false
  }
}

async function applyToJob(job) {
  state.applyState[job.id] = { loading: true, message: "" }

  try {
    const response = await api.applyJob(job.application_url)
    state.applyState[job.id] = { loading: false, message: response.message, status: response.status }
  } catch (error) {
    state.applyState[job.id] = { loading: false, message: error.message, status: "error" }
  }
}

function score(job) {
  return job.raw_data?.match_score ?? null
}
</script>

<template>
  <div class="page-stack">
    <section class="surface">
      <form class="form-grid form-grid-4" @submit.prevent="search">
        <label class="field">
          <span>Source</span>
          <select v-model="form.source" class="select">
            <option value="ats">ATS</option>
            <option value="linkedin">LinkedIn</option>
            <option value="all">All</option>
          </select>
        </label>

        <label class="field">
          <span>Keyword</span>
          <input v-model="form.keyword" class="input" type="text" placeholder="software engineer" />
        </label>

        <label class="field">
          <span>Location</span>
          <input v-model="form.location" class="input" type="text" placeholder="United States" />
        </label>

        <label class="field">
          <span>Profile</span>
          <input v-model="form.profile" class="input" type="text" />
        </label>

        <label class="field">
          <span>Posted</span>
          <select v-model="form.time_filter" class="select">
            <option value="24h">24h</option>
            <option value="week">Week</option>
            <option value="month">Month</option>
          </select>
        </label>

        <label class="field">
          <span>ATS</span>
          <select v-model="form.ats" class="select">
            <option value="">All</option>
            <option value="greenhouse">Greenhouse</option>
            <option value="lever">Lever</option>
          </select>
        </label>

        <label class="field">
          <span>Company</span>
          <input v-model="form.company" class="input" type="text" placeholder="stripe" />
        </label>

        <div class="actions-row align-end">
          <button class="button" type="submit" :disabled="state.searching">
            {{ state.searching ? "Searching" : "Search" }}
          </button>
        </div>
      </form>
    </section>

    <div v-if="state.error" class="banner is-danger">{{ state.error }}</div>

    <section class="surface">
      <div class="section-head">
        <h2>Results</h2>
        <span class="muted">{{ state.jobs.length }}</span>
      </div>

      <div v-if="state.searching" class="empty-state">Searching</div>
      <div v-else-if="state.jobs.length" class="job-list">
        <article v-for="job in state.jobs" :key="job.id" class="job-card">
          <div class="job-head">
            <div>
              <h3>{{ job.title }}</h3>
              <div class="muted-inline">{{ job.company }}<span v-if="job.location"> - {{ job.location }}</span></div>
            </div>

            <div class="chip-row">
              <span v-if="score(job) !== null" class="chip">{{ formatPercent(score(job), "0%") }}</span>
              <span v-if="job.ats_type && job.ats_type !== 'unknown'" class="chip">{{ job.ats_type }}</span>
              <span v-if="job.raw_data?.disqualified" class="chip danger">Review</span>
            </div>
          </div>

          <p v-if="job.description" class="muted-text">{{ truncateText(job.description) }}</p>

          <div class="actions-row">
            <button
              v-if="job.application_url"
              class="button"
              type="button"
              @click="applyToJob(job)"
              :disabled="state.applyState[job.id]?.loading"
            >
              {{ state.applyState[job.id]?.loading ? "Applying" : "Apply" }}
            </button>

            <a v-if="job.application_url" class="button ghost" :href="job.application_url" target="_blank" rel="noopener">
              Open
            </a>
          </div>

          <div v-if="state.applyState[job.id]?.message" class="inline-feedback" :class="state.applyState[job.id]?.status">
            {{ state.applyState[job.id].message }}
          </div>
        </article>
      </div>
      <div v-else class="empty-state">No jobs</div>
    </section>
  </div>
</template>
