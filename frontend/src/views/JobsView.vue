<script setup>
import { computed, onMounted, watch } from "vue"
import { RouterLink } from "vue-router"

import AppIcon from "../components/AppIcon.vue"
import AppSelect from "../components/AppSelect.vue"
import PaginationBar from "../components/PaginationBar.vue"
import TagInput from "../components/TagInput.vue"
import { api } from "../lib/api"
import { formatPercent, truncateText } from "../lib/format"
import { ensureLinkedInSessionLoaded, linkedinSessionState, syncLinkedInSession } from "../lib/linkedin-session"
import {
  emptyCounts,
  emptyResultSets,
  jobsForm as form,
  jobsState as state,
  persistJobsState,
} from "../lib/jobs-state"

const sourceOptions = [
  { value: "ats", label: "ATS" },
  { value: "linkedin", label: "LinkedIn" },
  { value: "all", label: "All" },
]

const postedDateOptions = [
  { value: "all", label: "All Dates" },
  { value: "month", label: "Past Month" },
  { value: "week", label: "Past Week" },
  { value: "24h", label: "Past 24 Hours" },
]

const atsOptions = [
  { value: "", label: "All" },
  { value: "greenhouse", label: "Greenhouse" },
  { value: "lever", label: "Lever" },
]

const experienceLevelOptions = [
  { value: "entry", label: "Entry-level" },
  { value: "senior", label: "Senior" },
  { value: "manager", label: "Manager" },
  { value: "director", label: "Director" },
  { value: "executive", label: "Executive" },
]

const employmentTypeOptions = [
  { value: "part_time", label: "Part-time" },
  { value: "contract", label: "Contract" },
  { value: "internship", label: "Internship" },
  { value: "coop", label: "Co-op" },
  { value: "full_time", label: "Full-time" },
  { value: "permanent", label: "Permanent" },
  { value: "temporary", label: "Temporary" },
  { value: "casual", label: "Casual" },
  { value: "seasonal", label: "Seasonal" },
  { value: "freelance", label: "Freelance" },
  { value: "volunteer", label: "Volunteer" },
]

const locationTypeOptions = [
  { value: "in_person", label: "In-person" },
  { value: "hybrid", label: "Hybrid" },
  { value: "remote", label: "Remote" },
]

const educationOptions = [
  { value: "high_school", label: "High school" },
  { value: "associate", label: "Associate" },
  { value: "bachelor", label: "Bachelor" },
  { value: "master", label: "Master" },
  { value: "mba", label: "MBA" },
  { value: "phd", label: "PhD" },
  { value: "jd", label: "JD" },
  { value: "md", label: "MD" },
]

const numericOperators = [
  { value: "", label: "Any" },
  { value: "gt", label: ">" },
  { value: "gte", label: ">=" },
  { value: "lt", label: "<" },
  { value: "lte", label: "<=" },
]

const pageSizeOptions = [10, 20, 50, 100].map((value) => ({
  value,
  label: `${value} / page`,
}))

const sourceUsesLinkedIn = computed(() => form.source === "linkedin" || form.source === "all")
const sourceUsesAts = computed(() => form.source === "ats" || form.source === "all")
const filterProfileOptions = computed(() => [
  { value: "", label: "Select saved profile" },
  ...state.filterProfiles.map((profile) => ({ value: profile.id, label: profile.id })),
])
const currentViewJobs = computed(() => {
  if (state.viewMode === "shown") {
    return state.filteredJobs
  }
  return state.resultSets[state.viewMode] || []
})
const totalPages = computed(() => Math.max(1, Math.ceil(currentViewJobs.value.length / state.pageSize)))
const paginatedJobs = computed(() => {
  const start = (state.currentPage - 1) * state.pageSize
  return currentViewJobs.value.slice(start, start + state.pageSize)
})
const resultViewChips = computed(() => {
  const chips = []
  if (state.searched) {
    chips.push({ id: "shown", label: `${state.filteredJobs.length} shown` })
    if (state.resultSets.fetched.length) {
      chips.push({ id: "fetched", label: `${state.resultSets.fetched.length} fetched` })
    }
    if (state.resultSets.linkedin.length) {
      chips.push({ id: "linkedin", label: `${state.resultSets.linkedin.length} LinkedIn` })
    }
    if (state.resultSets.ats.length) {
      chips.push({ id: "ats", label: `${state.resultSets.ats.length} ATS` })
    }
  }
  return chips
})

const activeFilterLabels = computed(() => {
  const labels = []

  if (form.profile.trim()) {
    labels.push(`Profile: ${form.profile.trim()}`)
  }
  if (sourceUsesLinkedIn.value && form.keywords.length) {
    labels.push(...form.keywords.map((keyword) => `Keyword: ${keyword}`))
  }
  if (sourceUsesAts.value && form.ats) {
    labels.push(`ATS: ${prettyLabel(form.ats)}`)
  }
  if (sourceUsesAts.value && form.company.trim()) {
    labels.push(`Company: ${form.company.trim()}`)
  }

  if (form.time_filter !== "all") {
    labels.push(`Posted: ${timeFilterLabel(form.time_filter)}`)
  }
  if (form.locations.length) {
    labels.push(...form.locations.map((value) => `Location: ${value}`))
  }
  labels.push(...labelValues(form.experience_levels, experienceLevelOptions))
  labels.push(...labelValues(form.employment_types, employmentTypeOptions))
  labels.push(...labelValues(form.location_types, locationTypeOptions))
  labels.push(...labelValues(form.education_levels, educationOptions))

  if (form.pay_operator && form.pay_amount) {
    labels.push(`Pay ${operatorLabel(form.pay_operator)} ${formatMoney(Number(form.pay_amount))}`)
  }
  if (form.experience_operator && form.experience_years) {
    labels.push(`Exp ${operatorLabel(form.experience_operator)} ${form.experience_years}y`)
  }

  return labels
})

const searchLocationNote = computed(() => {
  if (!sourceUsesLinkedIn.value || !form.locations.length) {
    return ""
  }
  return "LinkedIn search runs once per candidate location and merges the results."
})

watch(
  () => form.source,
  (source) => {
    if (source === "ats") {
      form.keywords = []
      form.time_filter = "all"
    }

    if (source === "linkedin") {
      form.ats = ""
      form.company = ""
    }

    if (source === "linkedin" || source === "all") {
      void ensureLinkedInSessionLoaded()
    }
  },
)

watch(
  () => state.selectedFilterProfileId,
  (profileId) => {
    if (!profileId) {
      return
    }
    const profile = state.filterProfiles.find((item) => item.id === profileId)
    if (profile) {
      applyFilterProfile(profile)
    }
  },
)

watch(
  () => [state.viewMode, state.pageSize, currentViewJobs.value.length],
  () => {
    if (state.currentPage > totalPages.value) {
      state.currentPage = totalPages.value
    }
    if (state.currentPage < 1) {
      state.currentPage = 1
    }
  },
)

let persistTimer = null
watch(
  [form, state],
  () => {
    clearTimeout(persistTimer)
    persistTimer = setTimeout(persistJobsState, 300)
  },
  { deep: true },
)

onMounted(() => {
  if (sourceUsesLinkedIn.value) {
    void ensureLinkedInSessionLoaded()
  }
  void loadFilterProfiles()
})

const emptyStateMessage = computed(() => {
  if (!state.searched) {
    return "No jobs"
  }
  if (state.viewMode === "shown" && state.resultSets.fetched.length > 0 && state.filteredJobs.length === 0) {
    return "Jobs were fetched, but none matched your current filters."
  }
  return "No jobs"
})

async function search() {
  const signature = buildFetchSignature()
  if (canReuseFetchedResults(signature)) {
    state.searched = true
    state.error = ""
    state.message = "Updated results from the last fetched set."
    refreshDisplayedJobs()
    return
  }

  state.searching = true
  state.searched = true
  state.error = ""
  state.message = ""
  if (sourceUsesLinkedIn.value) {
    linkedinSessionState.checked = true
    linkedinSessionState.authenticated = true
    linkedinSessionState.ok = true
  }
  state.filteredJobs = []
  state.resultSets = emptyResultSets()
  state.counts = emptyCounts()

  try {
    const response = await api.searchJobs({
      ...form,
      keyword: "",
      keywords: [...form.keywords],
      profile: "",
      location: "",
      max_pages: Number(form.max_pages) || 20,
      locations: [...form.locations],
      pay_amount: parseOptionalNumber(form.pay_amount),
      experience_years: parseOptionalNumber(form.experience_years),
    })
    state.viewMode = "shown"
    setResultSets(response.views)
    refreshDisplayedJobs()
    state.counts = response.counts || emptyCounts()
    state.error = response.error || ""
    state.lastFetchSignature = signature
    state.currentPage = 1

    if (sourceUsesLinkedIn.value && response.error_code === "linkedin_auth_required") {
      syncLinkedInSession({
        ok: false,
        authenticated: false,
        has_session_data: linkedinSessionState.has_session_data,
        message: response.error || "LinkedIn login required.",
        error: response.error || "LinkedIn login required.",
      })
    } else if (sourceUsesLinkedIn.value && response.counts?.linkedin) {
      syncLinkedInSession({
        ok: true,
        authenticated: true,
        has_session_data: true,
        message:
          linkedinSessionState.message || "LinkedIn session is ready for authenticated searches.",
      })
      if (!linkedinSessionState.message) {
        linkedinSessionState.message = "LinkedIn session is ready for authenticated searches."
      }
    }
  } catch (error) {
    state.filteredJobs = []
    state.resultSets = emptyResultSets()
    state.counts = emptyCounts()
    state.error = error.message
  } finally {
    state.searching = false
  }
}

async function loadFilterProfiles() {
  state.filterProfilesLoading = true
  try {
    const response = await api.filterProfiles()
    state.filterProfiles = response.profiles || []

    const activeProfileId = state.selectedFilterProfileId || form.profile.trim()
    if (activeProfileId) {
      const profile = state.filterProfiles.find((item) => item.id === activeProfileId)
      if (profile) {
        state.selectedFilterProfileId = profile.id
        applyFilterProfile(profile)
      }
    }
  } catch (error) {
    state.error = error.message
  } finally {
    state.filterProfilesLoading = false
  }
}

async function saveCurrentFilterProfile() {
  const profileId = form.profile.trim()
  if (!profileId) {
    state.error = "Enter a filter profile name before saving."
    state.message = ""
    return
  }

  state.error = ""
  try {
    const response = await api.saveFilterProfile(profileId, currentFilterProfilePayload())
    state.filterProfiles = response.profiles || []
    state.selectedFilterProfileId = profileId
    state.message = response.message || `Saved filter profile '${profileId}'.`
  } catch (error) {
    state.error = error.message
    state.message = ""
  }
}

async function deleteCurrentFilterProfile() {
  const profileId = form.profile.trim()
  if (!profileId) {
    state.error = "Enter a filter profile name before deleting."
    state.message = ""
    return
  }

  state.error = ""
  try {
    const response = await api.deleteFilterProfile(profileId)
    state.filterProfiles = response.profiles || []
    state.selectedFilterProfileId = ""
    form.profile = ""
    state.message = response.message || `Deleted filter profile '${profileId}'.`
  } catch (error) {
    state.error = error.message
    state.message = ""
  }
}

function currentFilterProfilePayload() {
  return {
    source: form.source,
    keywords: [...form.keywords],
    time_filter: form.time_filter,
    max_pages: Number(form.max_pages) || 20,
    ats: form.ats,
    company: form.company,
    locations: [...form.locations],
    experience_levels: [...form.experience_levels],
    employment_types: [...form.employment_types],
    location_types: [...form.location_types],
    education_levels: [...form.education_levels],
    pay_operator: form.pay_operator,
    pay_amount: parseOptionalNumber(form.pay_amount),
    experience_operator: form.experience_operator,
    experience_years: parseOptionalNumber(form.experience_years),
  }
}

function applyFilterProfile(profile) {
  form.profile = profile.id
  form.source = profile.source || "ats"
  form.keywords = [...(profile.keywords || [])]
  form.time_filter = profile.time_filter || "all"
  form.max_pages = profile.max_pages ?? 20
  form.ats = profile.ats || ""
  form.company = profile.company || ""
  form.locations = [...(profile.locations || [])]
  form.experience_levels = [...(profile.experience_levels || [])]
  form.employment_types = [...(profile.employment_types || [])]
  form.location_types = [...(profile.location_types || [])]
  form.education_levels = [...(profile.education_levels || [])]
  form.pay_operator = profile.pay_operator || ""
  form.pay_amount = profile.pay_amount ?? ""
  form.experience_operator = profile.experience_operator || ""
  form.experience_years = profile.experience_years ?? ""
  state.message = `Loaded filter profile '${profile.id}'.`
  state.error = ""
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

function parseOptionalNumber(value) {
  if (value === "" || value === null || value === undefined) {
    return null
  }

  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function score(job) {
  return job.match_score ?? job.raw_data?.match_score ?? null
}

function isLinkedInUrl(url) {
  return Boolean(url) && url.toLowerCase().includes("linkedin.com")
}

function detailUrl(job) {
  return job.raw_data?.detail_url || job.raw_data?.linkedin_url || job.raw_data?.linkedin_href || job.application_url || ""
}

function manualApplyUrl(job) {
  return job.raw_data?.manual_apply_url || job.application_url || detailUrl(job)
}

function sourceLabel(job) {
  return prettyLabel(job.ats_type && job.ats_type !== "unknown" ? job.ats_type : job.source)
}

async function manualApply(job) {
  const fallbackUrl = detailUrl(job) || manualApplyUrl(job)
  const targetWindow = window.open("", "_blank")

  try {
    const initialUrl = manualApplyUrl(job)
    if (initialUrl && !isLinkedInUrl(initialUrl)) {
      if (targetWindow) {
        targetWindow.location.replace(initialUrl)
      } else {
        window.open(initialUrl, "_blank", "noopener")
      }
      return
    }

    const response = await api.manualApplyTarget(fallbackUrl)
    const finalUrl = response.url || fallbackUrl
    if (targetWindow) {
      targetWindow.location.replace(finalUrl)
    } else if (finalUrl) {
      window.open(finalUrl, "_blank", "noopener")
    }
  } catch (error) {
    if (targetWindow) {
      targetWindow.location.replace(fallbackUrl || "about:blank")
    } else if (fallbackUrl) {
      window.open(fallbackUrl, "_blank", "noopener")
    }
    state.applyState[job.id] = { loading: false, message: error.message, status: "review" }
  }
}

function chipLabel(value) {
  return prettyLabel(value)
}

function metadataChips(job) {
  return [
    chipLabel(job.employment_category),
    chipLabel(job.experience_level),
    chipLabel(job.education_level),
    payLabel(job),
    experienceLabel(job),
  ].filter(Boolean)
}

function payLabel(job) {
  if (job.pay_min === null || job.pay_min === undefined) {
    if (job.pay_max === null || job.pay_max === undefined) {
      return ""
    }

    return `<= ${formatMoney(job.pay_max)}`
  }

  if (job.pay_max === null || job.pay_max === undefined || job.pay_max === job.pay_min) {
    return formatMoney(job.pay_min)
  }

  return `${formatMoney(job.pay_min)} - ${formatMoney(job.pay_max)}`
}

function experienceLabel(job) {
  if (job.experience_years_min === null || job.experience_years_min === undefined) {
    if (job.experience_years_max === null || job.experience_years_max === undefined) {
      return ""
    }

    return `<= ${job.experience_years_max}y`
  }

  if (job.experience_years_max === null || job.experience_years_max === undefined || job.experience_years_max === job.experience_years_min) {
    return `${job.experience_years_min}+y`
  }

  return `${job.experience_years_min}-${job.experience_years_max}y`
}

function formatMoney(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value)
}

function prettyLabel(value) {
  if (!value || value === "unknown") {
    return ""
  }

  return value
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function labelValues(values, options) {
  return options.filter((option) => values.includes(option.value)).map((option) => option.label)
}

function operatorLabel(value) {
  return numericOperators.find((option) => option.value === value)?.label || value
}

function timeFilterLabel(value) {
  return (
    {
      all: "All dates",
      month: "Past month",
      week: "Past week",
      "24h": "Past 24 hours",
    }[value] || value
  )
}

function resetForm() {
  form.source = "ats"
  form.keywords = []
  form.profile = ""
  form.time_filter = "all"
  form.max_pages = 20
  form.ats = ""
  form.company = ""
  form.locations = []
  form.experience_levels = []
  form.employment_types = []
  form.location_types = []
  form.education_levels = []
  form.pay_operator = ""
  form.pay_amount = ""
  form.experience_operator = ""
  form.experience_years = ""
}

function toggleSection(section) {
  state.sections[section] = !state.sections[section]
}

function setResultSets(views) {
  const next = views || emptyResultSets()
  state.resultSets = {
    shown: next.shown || [],
    fetched: next.fetched || [],
    linkedin: next.linkedin || [],
    ats: next.ats || [],
  }
}

function buildFetchSignature() {
  return JSON.stringify({
    source: form.source,
    keywords: sourceUsesLinkedIn.value
      ? [...form.keywords].map((value) => value.trim().toLowerCase())
      : [],
    time_filter: sourceUsesLinkedIn.value ? form.time_filter : "all",
    search_locations: sourceUsesLinkedIn.value
      ? [...form.locations].map((value) => value.trim().toLowerCase()).filter(Boolean)
      : [],
    ats: sourceUsesAts.value ? form.ats : "",
    company: sourceUsesAts.value ? form.company.trim().toLowerCase() : "",
    max_pages: sourceUsesLinkedIn.value ? Number(form.max_pages) || 20 : 0,
  })
}

function canReuseFetchedResults(signature) {
  return (
    Boolean(state.lastFetchSignature)
    && state.lastFetchSignature === signature
    && state.resultSets.fetched.length > 0
    && !state.error
  )
}

function refreshDisplayedJobs() {
  state.filteredJobs = filterFetchedJobs(state.resultSets.fetched)
}

function filterFetchedJobs(jobs) {
  return jobs.filter((job) => matchesLocalFilters(job))
}

function matchesLocalFilters(job) {
  if (form.experience_levels.length && !form.experience_levels.includes(job.experience_level)) {
    return false
  }
  if (form.employment_types.length && !form.employment_types.includes(job.employment_category)) {
    return false
  }
  if (form.location_types.length && !form.location_types.includes(job.location_type)) {
    return false
  }
  if (form.education_levels.length && !form.education_levels.includes(job.education_level)) {
    return false
  }
  if (!shouldSkipLocalLocationFilter() && form.locations.length && !matchesLocations(job.location, form.locations)) {
    return false
  }

  const payAmount = parseOptionalNumber(form.pay_amount)
  if (form.pay_operator && payAmount !== null && !matchesNumericRange(job.pay_min, job.pay_max, form.pay_operator, payAmount)) {
    return false
  }

  const experienceYears = parseOptionalNumber(form.experience_years)
  if (
    form.experience_operator
    && experienceYears !== null
    && !matchesNumericRange(job.experience_years_min, job.experience_years_max, form.experience_operator, experienceYears)
  ) {
    return false
  }

  return true
}

function shouldSkipLocalLocationFilter() {
  return sourceUsesLinkedIn.value && form.locations.length > 0
}

function matchesLocations(location, candidates) {
  const normalizedLocation = (location || "").toLowerCase()
  if (!normalizedLocation) {
    return false
  }
  return candidates.some((candidate) => normalizedLocation.includes(candidate.toLowerCase()))
}

function matchesNumericRange(minValue, maxValue, operator, target) {
  if (minValue === null || minValue === undefined) {
    if (maxValue === null || maxValue === undefined) {
      return false
    }
  }

  const lower = minValue ?? maxValue
  const upper = maxValue ?? minValue
  if (operator === "gt") {
    return upper > target
  }
  if (operator === "gte") {
    return upper >= target
  }
  if (operator === "lt") {
    return lower < target
  }
  if (operator === "lte") {
    return lower <= target
  }
  return true
}

function setViewMode(mode) {
  state.viewMode = mode
  state.currentPage = 1
  state.pageJump = ""
}

function goToPage(page) {
  state.currentPage = Math.min(Math.max(page, 1), totalPages.value)
  state.pageJump = ""
}

</script>

<template>
  <div class="page-stack">
    <div v-if="state.message" class="banner is-success">{{ state.message }}</div>
    <section class="surface jobs-shell">
      <form class="page-stack" @submit.prevent="search">
        <section class="jobs-panel jobs-panel-full">
          <div class="section-head compact-head">
            <div>
              <h2>Filters</h2>
              <div class="muted-inline">Basic And Advanced Search Controls</div>
            </div>
            <span class="muted">{{ activeFilterLabels.length }}</span>
          </div>

          <div class="jobs-profile-strip">
            <div class="jobs-profile-fields">
              <label class="field">
                <span>Filter Profile</span>
                <input v-model="form.profile" class="input" type="text" placeholder="Saved filter profile name" />
              </label>

              <label class="field">
                <span>Saved Profiles</span>
                <AppSelect v-model="state.selectedFilterProfileId" :options="filterProfileOptions" placeholder="Select saved profile" aria-label="Saved filter profiles" />
              </label>
            </div>

            <div class="jobs-profile-actions">
              <button class="icon-button" type="button" :disabled="state.filterProfilesLoading" aria-label="Refresh Profiles" title="Refresh Profiles" @click="loadFilterProfiles">
                <AppIcon name="refresh" />
              </button>
              <button class="icon-button primary" type="button" aria-label="Save Profile" title="Save Profile" @click="saveCurrentFilterProfile">
                <AppIcon name="save" />
              </button>
              <button class="icon-button danger" type="button" aria-label="Delete Profile" title="Delete Profile" @click="deleteCurrentFilterProfile">
                <AppIcon name="trash" />
              </button>
            </div>
          </div>

          <div class="muted-inline jobs-profile-note">
            Saved filter profiles include both Basic and Advanced filters.
          </div>

          <div class="page-stack jobs-panel-stack">
            <section class="accordion-section jobs-accordion">
              <button class="accordion-head" type="button" @click="toggleSection('basic')">
                <div>
                  <strong>Basic</strong>
                  <div class="muted-inline">Source, Query, And Candidate Locations</div>
                </div>
                <span class="accordion-icon"><AppIcon :name="state.sections.basic ? 'chevron-down' : 'chevron-right'" /></span>
              </button>

              <div v-if="state.sections.basic" class="accordion-body">
                <div class="form-grid jobs-panel-grid jobs-panel-grid-wide">
                  <label class="field">
                    <span>Source</span>
                    <AppSelect v-model="form.source" :options="sourceOptions" aria-label="Source" />
                  </label>

                  <template v-if="sourceUsesLinkedIn">
                    <label class="field">
                      <span>Date Posted</span>
                      <AppSelect v-model="form.time_filter" :options="postedDateOptions" aria-label="Date Posted" />
                    </label>

                    <label class="field">
                      <span>Max Pages</span>
                      <input v-model="form.max_pages" class="input" type="number" min="1" max="100" step="1" />
                    </label>

                    <label class="field field-span-full">
                      <span>Keywords</span>
                      <TagInput v-model="form.keywords" placeholder="Add a keyword or phrase" />
                      <div class="muted-inline">Any keyword tag found in the title or description will keep the result.</div>
                    </label>
                  </template>

                  <template v-if="sourceUsesAts">
                    <label class="field">
                      <span>ATS</span>
                      <AppSelect v-model="form.ats" :options="atsOptions" aria-label="ATS" />
                    </label>

                    <label class="field">
                      <span>Company Slug</span>
                      <input v-model="form.company" class="input" type="text" placeholder="Stripe" />
                    </label>
                  </template>

                  <label class="field field-span-full">
                    <span>Candidate Locations</span>
                    <TagInput v-model="form.locations" placeholder="San Francisco, CA, United States" />
                    <div v-if="searchLocationNote" class="muted-inline">
                      {{ searchLocationNote }}
                    </div>
                  </label>
                </div>
              </div>
            </section>

            <section class="accordion-section jobs-accordion">
              <button class="accordion-head" type="button" @click="toggleSection('advanced')">
                <div>
                  <strong>Advanced</strong>
                  <div class="muted-inline">Pay, Experience, Employment, Location, And Education</div>
                </div>
                <span class="accordion-icon"><AppIcon :name="state.sections.advanced ? 'chevron-down' : 'chevron-right'" /></span>
              </button>

              <div v-if="state.sections.advanced" class="accordion-body">
                <div class="page-stack jobs-filter-stack">
                  <div class="inline-grid inline-grid-2">
                    <div class="field">
                      <span>Pay</span>
                      <div class="inline-grid inline-grid-2">
                        <AppSelect v-model="form.pay_operator" :options="numericOperators" aria-label="Pay Operator" />
                        <input v-model="form.pay_amount" class="input" type="number" min="0" placeholder="120000" />
                      </div>
                    </div>

                    <div class="field">
                      <span>Experience Years</span>
                      <div class="inline-grid inline-grid-2">
                        <AppSelect v-model="form.experience_operator" :options="numericOperators" aria-label="Experience Operator" />
                        <input v-model="form.experience_years" class="input" type="number" min="0" placeholder="3" />
                      </div>
                    </div>
                  </div>

                  <div class="field">
                    <span>Experience Level</span>
                    <div class="toggle-grid">
                      <label v-for="option in experienceLevelOptions" :key="option.value" class="toggle-pill">
                        <input v-model="form.experience_levels" type="checkbox" :value="option.value" />
                        <span>{{ option.label }}</span>
                      </label>
                    </div>
                  </div>

                  <div class="field">
                    <span>Employment Type</span>
                    <div class="toggle-grid">
                      <label v-for="option in employmentTypeOptions" :key="option.value" class="toggle-pill">
                        <input v-model="form.employment_types" type="checkbox" :value="option.value" />
                        <span>{{ option.label }}</span>
                      </label>
                    </div>
                  </div>

                  <div class="field">
                    <span>Location Type</span>
                    <div class="toggle-grid">
                      <label v-for="option in locationTypeOptions" :key="option.value" class="toggle-pill">
                        <input v-model="form.location_types" type="checkbox" :value="option.value" />
                        <span>{{ option.label }}</span>
                      </label>
                    </div>
                  </div>

                  <div class="field">
                    <span>Education</span>
                    <div class="toggle-grid">
                      <label v-for="option in educationOptions" :key="option.value" class="toggle-pill">
                        <input v-model="form.education_levels" type="checkbox" :value="option.value" />
                        <span>{{ option.label }}</span>
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          </div>
        </section>

        <div class="jobs-toolbar">
          <div class="chip-row" v-if="activeFilterLabels.length">
            <span v-for="label in activeFilterLabels" :key="label" class="chip subtle">{{ label }}</span>
          </div>
          <div class="actions-row">
            <button class="icon-button" type="button" aria-label="Reset Filters" title="Reset Filters" @click="resetForm">
              <AppIcon name="refresh" />
            </button>
            <button class="icon-button primary" type="submit" :disabled="state.searching" aria-label="Search Jobs" title="Search Jobs">
              <AppIcon name="search" />
            </button>
          </div>
        </div>
      </form>
    </section>

    <div
      v-if="sourceUsesLinkedIn && linkedinSessionState.checked && !linkedinSessionState.authenticated && !state.searching && !state.resultSets.linkedin.length"
      class="banner is-warning"
    >
      LinkedIn session is not connected for web search.
      <RouterLink class="jobs-settings-link" to="/settings">Go to Settings</RouterLink>
      to connect or clear the saved session.
    </div>

    <div v-if="state.error" class="banner is-danger">{{ state.error }}</div>

    <section class="surface jobs-results-shell">
      <div class="section-head jobs-results-head">
        <div class="jobs-results-copy">
          <h2>Results</h2>
        </div>

        <div class="chip-row jobs-results-metrics" v-if="state.searched">
          <button
            v-for="chip in resultViewChips"
            :key="chip.id"
            class="chip result-chip-button"
            :class="{ subtle: state.viewMode !== chip.id }"
            type="button"
            @click="setViewMode(chip.id)"
          >
            {{ chip.label }}
          </button>
        </div>
      </div>

      <PaginationBar
        v-if="state.searched && currentViewJobs.length"
        :currentPage="state.currentPage"
        :totalPages="totalPages"
        :pageSize="state.pageSize"
        :pageSizeOptions="pageSizeOptions"
        :pageJump="state.pageJump"
        @update:currentPage="goToPage($event)"
        @update:pageSize="state.pageSize = $event"
        @update:pageJump="state.pageJump = $event"
      />

      <div v-if="state.searching" class="empty-state">Searching</div>
      <div v-else-if="currentViewJobs.length" class="job-list">
        <article v-for="job in paginatedJobs" :key="job.id" class="job-card">
          <div class="job-card-main">
            <div class="job-card-header">
              <div class="job-card-copy">
                <div class="chip-row job-card-topline">
                  <span v-if="score(job) !== null" class="chip job-chip-strong">{{ formatPercent(score(job), "0%") }}</span>
                  <span class="chip">{{ sourceLabel(job) }}</span>
                  <span v-if="chipLabel(job.location_type)" class="chip">{{ chipLabel(job.location_type) }}</span>
                  <span v-if="job.raw_data?.search_mode === 'public_guest'" class="chip subtle">Guest</span>
                  <span v-if="job.raw_data?.disqualified" class="chip danger">Review</span>
                </div>

                <h3>{{ job.title }}</h3>
                <div class="job-card-company">{{ job.company }}<span v-if="job.location"> · {{ job.location }}</span></div>
              </div>

            </div>

            <div v-if="metadataChips(job).length" class="job-card-box">
              <div class="chip-row job-card-tags">
                <span v-for="chip in metadataChips(job)" :key="chip" class="chip subtle">{{ chip }}</span>
              </div>
            </div>

            <div v-if="job.description" class="job-card-box">
              <p class="job-card-description">{{ truncateText(job.description) }}</p>
            </div>

            <div class="job-card-actions-row">
              <div class="job-card-actions">
                <a
                  class="button ghost compact"
                  :href="detailUrl(job)"
                  target="_blank"
                  rel="noopener"
                >
                  Details
                </a>
                <button class="button ghost compact" type="button" @click="manualApply(job)">
                  ManualApply
                </button>
                <button
                  class="button compact"
                  type="button"
                  @click="applyToJob(job)"
                  :disabled="state.applyState[job.id]?.loading || !job.application_url"
                >
                  {{ state.applyState[job.id]?.loading ? "Applying..." : "AutoApply" }}
                </button>
              </div>
            </div>

            <div v-if="state.applyState[job.id]?.message" class="inline-feedback" :class="state.applyState[job.id]?.status">
              {{ state.applyState[job.id].message }}
            </div>
          </div>
        </article>
      </div>
      <div v-else class="empty-state">{{ emptyStateMessage }}</div>

      <PaginationBar
        v-if="state.searched && currentViewJobs.length"
        :currentPage="state.currentPage"
        :totalPages="totalPages"
        :pageSize="state.pageSize"
        :pageSizeOptions="pageSizeOptions"
        :pageJump="state.pageJump"
        extraClass="jobs-pagination-bar-bottom"
        @update:currentPage="goToPage($event)"
        @update:pageSize="state.pageSize = $event"
        @update:pageJump="state.pageJump = $event"
      />
    </section>
  </div>
</template>
