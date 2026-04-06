<script setup>
import { onMounted, reactive } from "vue"

import AppIcon from "../components/AppIcon.vue"
import AppSelect from "../components/AppSelect.vue"
import { api } from "../lib/api"
import { formatDate, formatPercent } from "../lib/format"

const statusOptions = [
  { value: "", label: "All" },
  { value: "SUBMITTED", label: "Submitted" },
  { value: "FAILED", label: "Failed" },
  { value: "REVIEW_REQUIRED", label: "Review Required" },
]

const outcomeOptions = [
  { value: "", label: "All" },
  { value: "pending", label: "Pending" },
  { value: "rejected", label: "Rejected" },
  { value: "oa", label: "OA" },
  { value: "interview", label: "Interview" },
  { value: "offer", label: "Offer" },
]

const outcomeEditOptions = outcomeOptions.filter((option) => option.value !== "")

const filters = reactive({
  status: "",
  outcome: "",
  company: "",
  limit: 50,
})

const state = reactive({
  loading: true,
  error: "",
  updatingId: "",
  data: {
    applications: [],
    pipeline: {},
    outcomes: {
      total: 0,
      pending: 0,
      rates: { response_rate: 0, positive_rate: 0 },
    },
  },
})

async function load() {
  state.loading = true
  state.error = ""

  try {
    const response = await api.applications({ ...filters })
    state.data = response
    state.error = response.error || ""
  } catch (error) {
    state.error = error.message
  } finally {
    state.loading = false
  }
}

async function updateOutcome(application, outcome) {
  state.updatingId = application.id

  try {
    await api.updateOutcome(application.id, outcome)
    await load()
  } catch (error) {
    state.error = error.message
  } finally {
    state.updatingId = ""
  }
}

function prettify(status) {
  return status.replaceAll("_", " ")
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <section class="surface">
      <form class="form-grid form-grid-4" @submit.prevent="load">
        <label class="field">
          <span>Status</span>
          <AppSelect v-model="filters.status" :options="statusOptions" aria-label="Status filter" />
        </label>

        <label class="field">
          <span>Outcome</span>
          <AppSelect v-model="filters.outcome" :options="outcomeOptions" aria-label="Outcome filter" />
        </label>

        <label class="field">
          <span>Company</span>
          <input v-model="filters.company" class="input" type="text" placeholder="Company" />
        </label>

        <div class="actions-row align-end">
          <button class="icon-button primary" type="submit" :disabled="state.loading" aria-label="Apply filters" title="Apply filters">
            <AppIcon name="filter" />
          </button>
        </div>
      </form>
    </section>

    <section class="metric-grid">
      <article class="metric-card">
        <span class="metric-label">Submitted</span>
        <strong class="metric-value">{{ state.data.outcomes.total }}</strong>
      </article>
      <article class="metric-card">
        <span class="metric-label">Pending</span>
        <strong class="metric-value">{{ state.data.outcomes.pending }}</strong>
      </article>
      <article class="metric-card">
        <span class="metric-label">Response</span>
        <strong class="metric-value">{{ formatPercent(state.data.outcomes.rates.response_rate, "N/A") }}</strong>
      </article>
      <article class="metric-card">
        <span class="metric-label">Positive</span>
        <strong class="metric-value">{{ formatPercent(state.data.outcomes.rates.positive_rate, "N/A") }}</strong>
      </article>
    </section>

    <div v-if="state.error" class="banner is-danger">{{ state.error }}</div>

    <section class="content-grid content-grid-wide">
      <article class="surface">
        <div class="section-head">
          <h2>Pipeline</h2>
        </div>

        <div v-if="Object.keys(state.data.pipeline || {}).length" class="list-stack">
          <div v-for="(count, status) in state.data.pipeline" :key="status" class="list-row">
            <span>{{ prettify(status) }}</span>
            <span class="chip">{{ count }}</span>
          </div>
        </div>
        <div v-else class="empty-state">No data</div>
      </article>

      <article class="surface table-surface">
        <div class="section-head">
          <h2>Queue</h2>
          <span class="muted">{{ state.data.applications.length }}</span>
        </div>

        <div v-if="state.loading" class="empty-state">Loading</div>
        <div v-else-if="state.data.applications.length" class="table-shell">
          <table class="table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Status</th>
                <th>Score</th>
                <th>Outcome</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="application in state.data.applications" :key="application.id">
                <td>
                  <strong>{{ application.job.company }}</strong>
                  <div class="muted-inline">{{ application.job.title }}</div>
                </td>
                <td>{{ prettify(application.status) }}</td>
                <td>{{ application.match_score === null ? "-" : formatPercent(application.match_score, "0%") }}</td>
                <td>
                  <AppSelect
                    :model-value="application.outcome"
                    :options="outcomeEditOptions"
                    compact
                    :disabled="state.updatingId === application.id"
                    aria-label="Update outcome"
                    @update:model-value="updateOutcome(application, $event)"
                  />
                </td>
                <td>{{ formatDate(application.created_at) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state">No applications</div>
      </article>
    </section>
  </div>
</template>
