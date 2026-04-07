import { reactive } from "vue"

const JOBS_STORAGE_KEY = "autoapply.jobs.state"

export function emptyCounts() {
  return {
    ats: 0,
    linkedin: 0,
    linkedin_external_ats: 0,
    raw_total: 0,
    filtered_total: 0,
    total: 0,
  }
}

export function emptyResultSets() {
  return {
    shown: [],
    fetched: [],
    linkedin: [],
    ats: [],
  }
}

const persisted = loadPersistedJobsState()

export const jobsForm = reactive({
  source: "ats",
  keywords: [],
  profile: "",
  time_filter: "all",
  max_pages: 20,
  ats: "",
  company: "",
  locations: [],
  experience_levels: [],
  employment_types: [],
  location_types: [],
  education_levels: [],
  pay_operator: "",
  pay_amount: "",
  experience_operator: "",
  experience_years: "",
  ...(persisted.form || {}),
})

export const jobsState = reactive({
  searching: false,
  searched: persisted.state?.searched || false,
  error: persisted.state?.error || "",
  message: persisted.state?.message || "",
  filteredJobs: persisted.state?.filteredJobs || [],
  resultSets: persisted.state?.resultSets || emptyResultSets(),
  counts: persisted.state?.counts || emptyCounts(),
  viewMode: persisted.state?.viewMode || "shown",
  pageSize: persisted.state?.pageSize || 10,
  currentPage: persisted.state?.currentPage || 1,
  pageJump: "",
  lastFetchSignature: persisted.state?.lastFetchSignature || "",
  applyState: {},
  filterProfilesLoading: false,
  filterProfiles: persisted.state?.filterProfiles || [],
  selectedFilterProfileId: persisted.state?.selectedFilterProfileId || "",
  sections: {
    basic: persisted.state?.sections?.basic ?? true,
    advanced: persisted.state?.sections?.advanced ?? false,
  },
})

export function persistJobsState() {
  try {
    localStorage.setItem(
      JOBS_STORAGE_KEY,
      JSON.stringify({
        form: {
          ...jobsForm,
          keywords: [...jobsForm.keywords],
          locations: [...jobsForm.locations],
          experience_levels: [...jobsForm.experience_levels],
          employment_types: [...jobsForm.employment_types],
          location_types: [...jobsForm.location_types],
          education_levels: [...jobsForm.education_levels],
        },
        state: {
          searched: jobsState.searched,
          error: jobsState.error,
          message: jobsState.message,
          filteredJobs: jobsState.filteredJobs,
          resultSets: jobsState.resultSets,
          counts: jobsState.counts,
          viewMode: jobsState.viewMode,
          pageSize: jobsState.pageSize,
          currentPage: jobsState.currentPage,
          lastFetchSignature: jobsState.lastFetchSignature,
          filterProfiles: jobsState.filterProfiles,
          selectedFilterProfileId: jobsState.selectedFilterProfileId,
          sections: jobsState.sections,
        },
      }),
    )
  } catch {
    // Ignore storage failures and continue with in-memory state.
  }
}


function loadPersistedJobsState() {
  try {
    const payload = localStorage.getItem(JOBS_STORAGE_KEY)
    return payload ? JSON.parse(payload) : {}
  } catch {
    return {}
  }
}
