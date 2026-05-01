import { reactive } from "vue"

import { api } from "./api"

const OUTPUT_FORMAT_LABELS = {
  docx: "DOCX",
  pdf: "PDF",
  tex: "TEX",
}

const MATERIAL_LABELS = {
  resume_docx: "Resume DOCX",
  resume_pdf: "Resume PDF",
  resume_tex: "Resume TEX",
  cover_letter_docx: "Cover Letter DOCX",
  cover_letter_pdf: "Cover Letter PDF",
  cover_letter_tex: "Cover Letter TEX",
}

const DOCUMENT_TYPES = ["resume", "cover_letter"]

export const templatesState = reactive({
  loading: false,
  loaded: false,
  error: "",
  templates: { resume: [], cover_letter: [] },
})

export async function loadTemplates({ force = false } = {}) {
  if (templatesState.loaded && !force) {
    return templatesState.templates
  }

  templatesState.loading = true
  templatesState.error = ""
  try {
    const response = await api.templates()
    templatesState.templates = {
      resume: response.templates?.resume || [],
      cover_letter: response.templates?.cover_letter || [],
    }
    templatesState.loaded = true
    return templatesState.templates
  } catch (error) {
    templatesState.error = error.message
    throw error
  } finally {
    templatesState.loading = false
  }
}

export function applyTemplatesResponse(response) {
  if (!response) {
    return
  }
  templatesState.templates = {
    resume: response.templates?.resume || templatesState.templates.resume,
    cover_letter: response.templates?.cover_letter || templatesState.templates.cover_letter,
  }
  templatesState.loaded = true
}

export function getTemplate(documentType, templateId) {
  const collection = templatesState.templates[documentType] || []
  return collection.find((template) => template.template_id === templateId) || null
}

export function templateRenderer(template) {
  return template?.renderer || template?.manifest?.renderer || "docx"
}

export function isLatexTemplate(template) {
  return templateRenderer(template) === "latex"
}

export function templateSupportedOutputs(template) {
  const outputs = template?.supported_outputs || template?.manifest?.supported_outputs
  if (Array.isArray(outputs) && outputs.length) {
    return outputs.filter((output) => ["docx", "pdf", "tex"].includes(output))
  }
  return ["docx", "pdf"]
}

export function materialTypeForOutput(documentType, output) {
  const prefix = documentType === "cover_letter" ? "cover_letter" : "resume"
  return `${prefix}_${output}`
}

export function outputFormatLabel(output) {
  return OUTPUT_FORMAT_LABELS[output] || output.toUpperCase()
}

export function materialOptionLabel(materialType) {
  return MATERIAL_LABELS[materialType] || materialType
}

export function documentTypeLabel(documentType) {
  return documentType === "cover_letter" ? "Cover Letter" : "Resume"
}

export { DOCUMENT_TYPES, OUTPUT_FORMAT_LABELS, MATERIAL_LABELS }
