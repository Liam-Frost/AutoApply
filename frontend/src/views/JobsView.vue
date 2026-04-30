<script setup>
import { computed, onMounted, reactive, watch } from "vue"
import { RouterLink, useRouter } from "vue-router"

import AppIcon from "../components/AppIcon.vue"
import AppSelect from "../components/AppSelect.vue"
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

const router = useRouter()

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

const materialTargets = [
  {
    id: "resume",
    materialType: "resume_docx",
    label: "Resume",
    description: "Tailored resume preview with DOCX/PDF downloads when available.",
  },
  {
    id: "cover_letter",
    materialType: "cover_letter_docx",
    label: "Cover Letter",
    description: "Role-specific cover letter preview with DOCX/PDF/TXT downloads.",
  },
]

const materialOptions = [
  { type: "resume_pdf", label: "Resume PDF" },
  { type: "resume_docx", label: "Resume DOCX" },
  { type: "cover_letter_pdf", label: "Cover Letter PDF" },
  { type: "cover_letter_docx", label: "Cover Letter DOCX" },
  { type: "cover_letter_txt", label: "Cover Letter TXT" },
]

const materialModal = reactive({
  open: false,
  job: null,
  selected: {
    resume: true,
    cover_letter: true,
  },
  templateIds: {
    resume: "",
    cover_letter: "",
  },
})

const modalMaterialState = computed(() => {
  const jobId = materialModal.job?.id
  return jobId ? state.materialState[jobId] || {} : {}
})

const canGenerateMaterials = computed(
  () => Boolean(materialModal.job) && selectedMaterialTargets().length > 0 && !modalMaterialState.value.loading,
)

const materialReviewEntries = computed(() => buildMaterialReviewEntries(modalMaterialState.value))
const resumeTemplateOptions = computed(() => templateOptions("resume"))
const coverLetterTemplateOptions = computed(() => templateOptions("cover_letter"))

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
const pageButtons = computed(() => buildPageButtons(totalPages.value, state.currentPage))
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

watch(
  [form, state],
  () => {
    persistJobsState()
  },
  { deep: true },
)

onMounted(() => {
  if (sourceUsesLinkedIn.value) {
    void ensureLinkedInSessionLoaded()
  }
  void loadFilterProfiles()
  void loadMaterialTemplates()
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

async function loadMaterialTemplates() {
  try {
    const response = await api.templates()
    state.materialTemplates = {
      resume: response.templates?.resume || [],
      cover_letter: response.templates?.cover_letter || [],
    }
    materialModal.templateIds.resume ||= state.materialTemplates.resume[0]?.template_id || ""
    materialModal.templateIds.cover_letter ||=
      state.materialTemplates.cover_letter[0]?.template_id || ""
  } catch (error) {
    state.materialTemplates = { resume: [], cover_letter: [] }
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

function materialOptionLabel(materialType) {
  return (
    materialOptions.find((option) => option.type === materialType)?.label ||
    {
      cover_letter_txt: "Cover Letter TXT",
      resume_pdf: "Resume PDF",
      resume_docx: "Resume DOCX",
      cover_letter_pdf: "Cover Letter PDF",
      cover_letter_docx: "Cover Letter DOCX",
    }[materialType] ||
    "Material"
  )
}

function openMaterialModal(job) {
  const previousTargets = state.materialState[job.id]?.selectedTargets || []
  const previousTemplates = state.materialState[job.id]?.selectedTemplates || {}
  materialModal.job = job
  materialModal.open = true
  materialTargets.forEach((target) => {
    materialModal.selected[target.id] = previousTargets.length
      ? previousTargets.includes(target.id)
      : true
  })
  materialModal.templateIds.resume =
    previousTemplates.resume || materialModal.templateIds.resume || state.materialTemplates.resume[0]?.template_id || ""
  materialModal.templateIds.cover_letter =
    previousTemplates.cover_letter ||
    materialModal.templateIds.cover_letter ||
    state.materialTemplates.cover_letter[0]?.template_id ||
    ""
}

function closeMaterialModal() {
  materialModal.open = false
  materialModal.job = null
}

function goToMaterials(job) {
  router.push({ path: "/materials", query: { jobId: job.id } })
}

async function generateSelectedMaterials() {
  const job = materialModal.job
  if (!job) {
    return
  }

  const targets = selectedMaterialTargets()
  if (!targets.length) {
    state.materialState[job.id] = {
      ...(state.materialState[job.id] || {}),
      loading: false,
      message: "Select at least one material to generate.",
      status: "error",
    }
    return
  }

  const existing = state.materialState[job.id] || {}
  state.materialState[job.id] = {
    ...existing,
    loading: true,
    message: `Generating ${targetListLabel(targets)}...`,
    status: "",
    selectedTargets: targets.map((target) => target.id),
    selectedTemplates: selectedTemplateIds(),
  }

  const settled = await Promise.allSettled(
    targets.map((target) =>
      api
        .generateJobMaterial(job, target.materialType, materialModal.templateIds[target.id])
        .then((response) => ({ target, response })),
    ),
  )

  const results = { ...(existing.results || {}) }
  const failures = []
  const successes = []
  settled.forEach((result, index) => {
    const target = targets[index]
    if (result.status === "fulfilled") {
      results[target.id] = result.value.response
      successes.push(target.label)
    } else {
      failures.push(`${target.label}: ${result.reason?.message || "generation failed"}`)
    }
  })

  const primary = results.resume || results.cover_letter || null
  state.materialState[job.id] = {
    loading: false,
    message: materialGenerationMessage(successes, failures),
    status: successes.length ? "review" : "error",
    selectedTargets: targets.map((target) => target.id),
    selectedTemplates: selectedTemplateIds(),
    results,
    artifacts: mergeMaterialArtifacts(results),
    artifact: primary?.artifact || null,
    document: primary?.document || null,
    validation: primary?.validation || null,
    version: primary?.version || null,
    materialType: primary?.material_type || "",
  }
}

function selectedTemplateIds() {
  return {
    resume: materialModal.templateIds.resume,
    cover_letter: materialModal.templateIds.cover_letter,
  }
}

function artifactDownloadUrl(artifact) {
  const path = typeof artifact === "string" ? artifact : artifact?.path
  return path ? api.artifactDownloadUrl(path) : ""
}

function artifactEntries(material) {
  return Object.entries(material?.artifacts || {})
    .filter(([, path]) => Boolean(path))
    .map(([type, path]) => ({ type, path, label: materialOptionLabel(type) }))
}

function selectedMaterialTargets() {
  return materialTargets.filter((target) => materialModal.selected[target.id])
}

function templateOptions(documentType) {
  const templates = state.materialTemplates[documentType] || []
  if (!templates.length) {
    return [{ value: "", label: "Default template" }]
  }
  return templates.map((template) => ({
    value: template.template_id,
    label: template.name || template.template_id,
  }))
}

function targetListLabel(targets) {
  return targets.map((target) => target.label).join(" and ")
}

function materialGenerationMessage(successes, failures) {
  if (successes.length && failures.length) {
    return `Generated ${successes.join(" and ")}. Failed ${failures.join("; ")}.`
  }
  if (successes.length) {
    return `Generated ${successes.join(" and ")}.`
  }
  return failures.join("; ") || "Material generation failed."
}

function mergeMaterialArtifacts(results) {
  const artifacts = Object.fromEntries(materialOptions.map((option) => [option.type, null]))
  Object.values(results || {}).forEach((result) => {
    Object.entries(result?.artifacts || {}).forEach(([type, path]) => {
      if (path) {
        artifacts[type] = path
      }
    })
  })
  return artifacts
}

function buildMaterialReviewEntries(material) {
  const results = material?.results || {}
  const entries = materialTargets
    .map((target) => ({
      id: target.id,
      label: target.label,
      result: results[target.id],
      document: results[target.id]?.document || null,
    }))
    .filter((entry) => entry.document)

  if (!entries.length && material?.document) {
    return [
      {
        id: material.materialType || "material",
        label: materialOptionLabel(material.materialType),
        result: material,
        document: material.document,
      },
    ]
  }
  return entries
}

function validationIssues(material) {
  return material?.validation?.issues || []
}

function validationMetrics(material) {
  return material?.validation?.metrics || {}
}

function resumePreviewItems(document) {
  if (!document || document.document_type !== "resume") {
    return []
  }
  return [
    ...(document.experiences || []).map((item) => ({ ...item, section: "Experience" })),
    ...(document.projects || []).map((item) => ({ ...item, section: "Projects" })),
  ]
}

function coverParagraphs(document) {
  return document?.document_type === "cover_letter" ? document.paragraphs || [] : []
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

function absoluteUrl(url) {
  if (!url) {
    return ""
  }
  if (url.startsWith("/")) {
    return `https://www.linkedin.com${url}`
  }
  return url
}

function detailUrl(job) {
  return absoluteUrl(
    job.raw_data?.detail_url ||
      job.raw_data?.linkedin_url ||
      job.raw_data?.linkedin_href ||
      job.application_url ||
      "",
  )
}

function manualApplyUrl(job) {
  return absoluteUrl(job.raw_data?.manual_apply_url || job.application_url || detailUrl(job))
}

function sourceLabel(job) {
  return prettyLabel(job.ats_type && job.ats_type !== "unknown" ? job.ats_type : job.source)
}

async function manualApply(job) {
  const fallbackUrl = detailUrl(job) || manualApplyUrl(job)
  const initialUrl = manualApplyUrl(job)

  if (initialUrl && !isLinkedInUrl(initialUrl)) {
    window.open(initialUrl, "_blank")
    return
  }

  const targetWindow = window.open(fallbackUrl || initialUrl || "about:blank", "_blank")

  try {
    const response = await api.manualApplyTarget(fallbackUrl)
    const finalUrl = response.url || fallbackUrl
    if (targetWindow && finalUrl) {
      targetWindow.location.replace(finalUrl)
    } else if (finalUrl) {
      window.open(finalUrl, "_blank")
    }
  } catch (error) {
    if (targetWindow && fallbackUrl) {
      targetWindow.location.replace(fallbackUrl || "about:blank")
    } else if (fallbackUrl) {
      window.open(fallbackUrl, "_blank")
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

function jumpToPage() {
  const page = Number(state.pageJump)
  if (Number.isFinite(page) && page >= 1) {
    goToPage(page)
  }
}

function buildPageButtons(total, current) {
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => index + 1)
  }

  const buttons = [1]
  const windowStart = Math.max(2, current - 1)
  const windowEnd = Math.min(total - 1, current + 1)

  if (windowStart > 2) {
    buttons.push("ellipsis-left")
  }

  for (let page = windowStart; page <= windowEnd; page += 1) {
    buttons.push(page)
  }

  if (windowEnd < total - 1) {
    buttons.push("ellipsis-right")
  }

  buttons.push(total)
  return buttons
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

      <div v-if="state.searched && currentViewJobs.length" class="jobs-pagination-bar">
        <div class="jobs-pagination-controls">
          <div class="jobs-page-numbers">
            <button class="icon-button" type="button" aria-label="First page" title="First page" :disabled="state.currentPage <= 1" @click="goToPage(1)">
              <AppIcon name="chevrons-left" />
            </button>
            <button class="icon-button" type="button" aria-label="Previous page" title="Previous page" :disabled="state.currentPage <= 1" @click="goToPage(state.currentPage - 1)">
              <AppIcon name="chevron-left" />
            </button>
            <button
              v-for="page in pageButtons"
              :key="`${page}`"
              class="jobs-page-button"
              :class="{ 'is-active': page === state.currentPage, 'is-ellipsis': String(page).startsWith('ellipsis') }"
              type="button"
              :disabled="String(page).startsWith('ellipsis')"
              @click="typeof page === 'number' ? goToPage(page) : null"
            >
              {{ String(page).startsWith('ellipsis') ? '…' : page }}
            </button>
            <input v-model="state.pageJump" class="input jobs-page-jump" type="number" min="1" :max="totalPages" placeholder="#" @keydown.enter.prevent="jumpToPage" />
            <button class="icon-button" type="button" aria-label="Next page" title="Next page" :disabled="state.currentPage >= totalPages" @click="goToPage(state.currentPage + 1)">
              <AppIcon name="chevron-right" />
            </button>
            <button class="icon-button" type="button" aria-label="Last page" title="Last page" :disabled="state.currentPage >= totalPages" @click="goToPage(totalPages)">
              <AppIcon name="chevrons-right" />
            </button>
          </div>

          <div class="jobs-page-size">
            <AppSelect v-model="state.pageSize" :options="pageSizeOptions" compact aria-label="Results per page" />
          </div>
        </div>
      </div>

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
                  class="button ghost compact material-open-button"
                  type="button"
                  @click="goToMaterials(job)"
                >
                  <AppIcon name="generate" />
                  Generate Apply Materials
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

      <div v-if="state.searched && currentViewJobs.length" class="jobs-pagination-bar jobs-pagination-bar-bottom">
        <div class="jobs-pagination-controls">
          <div class="jobs-page-numbers">
            <button class="icon-button" type="button" aria-label="First page" title="First page" :disabled="state.currentPage <= 1" @click="goToPage(1)">
              <AppIcon name="chevrons-left" />
            </button>
            <button class="icon-button" type="button" aria-label="Previous page" title="Previous page" :disabled="state.currentPage <= 1" @click="goToPage(state.currentPage - 1)">
              <AppIcon name="chevron-left" />
            </button>
            <button
              v-for="page in pageButtons"
              :key="`bottom-${page}`"
              class="jobs-page-button"
              :class="{ 'is-active': page === state.currentPage, 'is-ellipsis': String(page).startsWith('ellipsis') }"
              type="button"
              :disabled="String(page).startsWith('ellipsis')"
              @click="typeof page === 'number' ? goToPage(page) : null"
            >
              {{ String(page).startsWith('ellipsis') ? '…' : page }}
            </button>
            <input v-model="state.pageJump" class="input jobs-page-jump" type="number" min="1" :max="totalPages" placeholder="#" @keydown.enter.prevent="jumpToPage" />
            <button class="icon-button" type="button" aria-label="Next page" title="Next page" :disabled="state.currentPage >= totalPages" @click="goToPage(state.currentPage + 1)">
              <AppIcon name="chevron-right" />
            </button>
            <button class="icon-button" type="button" aria-label="Last page" title="Last page" :disabled="state.currentPage >= totalPages" @click="goToPage(totalPages)">
              <AppIcon name="chevrons-right" />
            </button>
          </div>

          <div class="jobs-page-size">
            <AppSelect v-model="state.pageSize" :options="pageSizeOptions" compact aria-label="Results per page" />
          </div>
        </div>
      </div>
    </section>

    <div v-if="materialModal.open" class="material-modal-backdrop" @click.self="closeMaterialModal">
      <section class="material-modal" role="dialog" aria-modal="true" aria-labelledby="material-modal-title">
        <div class="material-modal-head">
          <div>
            <div class="muted-inline">Apply Materials</div>
            <h3 id="material-modal-title">{{ materialModal.job?.title }}</h3>
            <p>{{ materialModal.job?.company }}<span v-if="materialModal.job?.location"> · {{ materialModal.job.location }}</span></p>
          </div>
          <button class="icon-button" type="button" aria-label="Close materials modal" title="Close" @click="closeMaterialModal">
            <AppIcon name="close" />
          </button>
        </div>

        <div class="material-target-grid" aria-label="Select materials to generate">
          <label
            v-for="target in materialTargets"
            :key="target.id"
            class="material-target-card"
            :class="{ 'is-selected': materialModal.selected[target.id] }"
          >
            <input v-model="materialModal.selected[target.id]" type="checkbox" :disabled="modalMaterialState.loading" />
            <span class="material-target-check">
              <AppIcon name="check" />
            </span>
            <span class="material-target-copy">
              <strong>{{ target.label }}</strong>
              <small>{{ target.description }}</small>
            </span>
          </label>
        </div>

        <div class="material-template-grid">
          <label class="material-template-field" :class="{ 'is-disabled': !materialModal.selected.resume }">
            <span>Resume Template</span>
            <AppSelect
              v-model="materialModal.templateIds.resume"
              :options="resumeTemplateOptions"
              compact
              :disabled="modalMaterialState.loading || !materialModal.selected.resume"
              aria-label="Resume template"
            />
          </label>
          <label class="material-template-field" :class="{ 'is-disabled': !materialModal.selected.cover_letter }">
            <span>Cover Letter Template</span>
            <AppSelect
              v-model="materialModal.templateIds.cover_letter"
              :options="coverLetterTemplateOptions"
              compact
              :disabled="modalMaterialState.loading || !materialModal.selected.cover_letter"
              aria-label="Cover letter template"
            />
          </label>
        </div>

        <div class="material-modal-actions">
          <button class="button" type="button" :disabled="!canGenerateMaterials" @click="generateSelectedMaterials">
            {{ modalMaterialState.loading ? 'Generating...' : 'Generate Selected Materials' }}
          </button>
          <span v-if="modalMaterialState.message" class="inline-feedback" :class="modalMaterialState.status">
            {{ modalMaterialState.message }}
          </span>
        </div>

        <div v-if="materialReviewEntries.length" class="material-review-stack">
          <section v-for="entry in materialReviewEntries" :key="entry.id" class="material-review-panel">
            <div class="material-review-head">
              <div>
                <div class="muted-inline">Generated Preview</div>
                <h4>{{ entry.label }}</h4>
              </div>
            </div>

            <div class="chip-row">
              <span v-if="entry.result?.version?.id" class="chip subtle">Version {{ entry.result.version.id.slice(0, 8) }}</span>
              <span v-if="entry.result?.validation" class="chip" :class="entry.result.validation.ok ? 'success' : 'danger'">
                {{ entry.result.validation.ok ? 'Validation OK' : 'Needs Review' }}
              </span>
              <span v-if="validationMetrics(entry.result).pdf_page_count" class="chip subtle">
                {{ validationMetrics(entry.result).pdf_page_count }} PDF page(s)
              </span>
              <span v-if="validationMetrics(entry.result).coverage_ratio" class="chip subtle">
                {{ Math.round(validationMetrics(entry.result).coverage_ratio * 100) }}% keyword coverage
              </span>
            </div>

            <div v-if="artifactEntries(entry.result).length" class="material-download-row">
              <a
                v-for="artifact in artifactEntries(entry.result)"
                :key="artifact.type"
                class="button ghost compact"
                :href="artifactDownloadUrl(artifact.path)"
                target="_blank"
                rel="noopener"
              >
                Download {{ artifact.label }}
              </a>
            </div>

            <div v-if="validationIssues(entry.result).length" class="material-review-issues">
              <div v-for="issue in validationIssues(entry.result)" :key="`${entry.id}-${issue.type}-${issue.source_id || issue.message}`" class="material-issue" :class="issue.severity">
                <strong>{{ prettyLabel(issue.type) }}</strong>
                <span>{{ issue.message }}</span>
              </div>
            </div>

            <div v-if="entry.document?.document_type === 'resume'" class="material-preview-body">
              <div v-if="entry.document.summary?.length" class="material-preview-section">
                <strong>Summary</strong>
                <p v-for="line in entry.document.summary" :key="line">{{ line }}</p>
              </div>

              <div v-if="entry.document.skills" class="material-preview-section">
                <strong>Skills</strong>
                <div class="chip-row">
                  <template v-for="(items, category) in entry.document.skills" :key="category">
                    <span v-for="skill in items" :key="`${category}-${skill}`" class="chip subtle">{{ skill }}</span>
                  </template>
                </div>
              </div>

              <div v-for="item in resumePreviewItems(entry.document)" :key="item.source_id" class="material-preview-section">
                <div class="material-preview-item-head">
                  <strong>{{ item.section }} · {{ item.name }}</strong>
                  <span class="muted">{{ item.title || item.meta }}</span>
                </div>
                <div v-for="bullet in item.bullets" :key="bullet.source_id" class="material-bullet-preview">
                  <div>{{ bullet.text }}</div>
                  <div class="chip-row material-bullet-meta">
                    <span class="chip subtle">{{ bullet.source_entity }}</span>
                    <span v-if="bullet.score" class="chip subtle">score {{ Number(bullet.score).toFixed(1) }}</span>
                    <span v-for="keyword in bullet.matched_keywords" :key="`${bullet.source_id}-${keyword}`" class="chip">{{ keyword }}</span>
                  </div>
                </div>
              </div>
            </div>

            <div v-else class="material-preview-body">
              <div v-for="paragraph in coverParagraphs(entry.document)" :key="paragraph.text" class="material-preview-section">
                <div class="muted-inline">{{ prettyLabel(paragraph.type) }}</div>
                <p>{{ paragraph.text }}</p>
              </div>
            </div>
          </section>
        </div>
        <div v-else class="material-preview-empty">
          Select Resume, Cover Letter, or both. Generated previews and download buttons appear here.
        </div>
      </section>
    </div>
  </div>
</template>
