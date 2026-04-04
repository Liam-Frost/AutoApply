export function formatPercent(value, fallback = "0%") {
  if (value === null || value === undefined) {
    return fallback
  }

  return `${Math.round(value * 100)}%`
}

export function formatDate(value) {
  if (!value) {
    return "-"
  }

  return new Date(value).toLocaleDateString("en-CA")
}

export function truncateText(value, limit = 220) {
  if (!value) {
    return ""
  }

  return value.length > limit ? `${value.slice(0, limit)}...` : value
}
