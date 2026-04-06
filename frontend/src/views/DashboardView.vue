<script setup>
import { computed, onMounted, reactive } from "vue"

import AppIcon from "../components/AppIcon.vue"
import { api } from "../lib/api"
import { formatPercent } from "../lib/format"

const MAX_CONNECTION_ATTEMPTS = 3
const CONNECTION_RETRY_DELAY_MS = 350

const state = reactive({
  loading: true,
  error: "",
  data: {
    pipeline: {},
    summary: {
      total_discovered: 0,
      total_applied: 0,
      total_failed: 0,
      total_review: 0,
      avg_match_score: 0,
      avg_fields_filled_pct: 0,
    },
    outcomes: {
      total: 0,
      pending: 0,
      rates: {
        response_rate: 0,
        positive_rate: 0,
      },
    },
    companies: [],
    db_connected: false,
  },
})

const cards = computed(() => [
  { label: "Tracked", value: state.data.summary.total_discovered },
  { label: "Submitted", value: state.data.summary.total_applied },
  { label: "Pending", value: state.data.outcomes.pending },
  {
    label: "Response",
    value: formatPercent(state.data.outcomes.rates.response_rate, "N/A"),
  },
])

async function load() {
  state.loading = true
  state.error = ""

  let latestResponse = null
  let latestException = null

  for (let attempt = 1; attempt <= MAX_CONNECTION_ATTEMPTS; attempt += 1) {
    try {
      const response = await api.dashboard()
      latestResponse = response
      latestException = null
      if (response.db_connected) {
        break
      }
    } catch (error) {
      latestResponse = null
      latestException = error
    }

    if (attempt < MAX_CONNECTION_ATTEMPTS) {
      await delay(CONNECTION_RETRY_DELAY_MS)
    }
  }

  try {
    if (latestResponse) {
      state.data = latestResponse
    }

    if (!latestResponse && latestException) {
      state.error = latestException.message
    }
  } finally {
    state.loading = false
  }
}

function delay(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

function prettify(status) {
  return status.replaceAll("_", " ")
}

onMounted(load)
</script>

<template>
  <div class="page-stack">
    <section class="metric-grid">
      <article v-for="card in cards" :key="card.label" class="metric-card">
        <span class="metric-label">{{ card.label }}</span>
        <strong class="metric-value">{{ card.value }}</strong>
      </article>
    </section>

    <div v-if="state.error" class="banner is-danger">{{ state.error }}</div>
    <div v-else-if="!state.loading && !state.data.db_connected" class="banner is-warning">Database Not Connected</div>

    <section class="content-grid content-grid-wide">
      <article class="surface">
        <div class="section-head">
          <h2>Pipeline</h2>
          <button class="icon-button" type="button" :disabled="state.loading" aria-label="Refresh dashboard" title="Refresh dashboard" @click="load">
            <AppIcon name="refresh" />
          </button>
        </div>

        <div v-if="state.loading" class="empty-state">Loading</div>
        <div v-else-if="Object.keys(state.data.pipeline).length" class="list-stack">
          <div v-for="(count, status) in state.data.pipeline" :key="status" class="list-row">
            <span>{{ prettify(status) }}</span>
            <span class="chip">{{ count }}</span>
          </div>
        </div>
        <div v-else class="empty-state">No data</div>
      </article>

      <div class="panel-stack">
        <article class="surface">
          <div class="section-head">
            <h2>Companies</h2>
            <span class="muted">{{ state.data.companies.length }}</span>
          </div>

          <div v-if="state.data.companies.length" class="list-stack">
            <div v-for="company in state.data.companies.slice(0, 6)" :key="company.company" class="list-row">
              <div>
                <strong>{{ company.company }}</strong>
                <div class="muted-inline">{{ company.applications }} / {{ company.submitted }}</div>
              </div>
              <span class="chip">{{ formatPercent(company.avg_match_score, "0%") }}</span>
            </div>
          </div>
          <div v-else class="empty-state">No data</div>
        </article>

        <article class="surface">
          <div class="section-head">
            <h2>Signals</h2>
          </div>

          <div class="list-stack">
            <div class="list-row">
              <span>Positive</span>
              <span class="chip">{{ formatPercent(state.data.outcomes.rates.positive_rate, "N/A") }}</span>
            </div>
            <div class="list-row">
              <span>Avg match</span>
              <span class="chip">{{ formatPercent(state.data.summary.avg_match_score, "0%") }}</span>
            </div>
            <div class="list-row">
              <span>Form fill</span>
              <span class="chip">{{ formatPercent(state.data.summary.avg_fields_filled_pct, "0%") }}</span>
            </div>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>
