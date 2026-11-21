// A deadline, as a day and as words.
//
// "Due today / tomorrow" was worked out twice, both times as the number of 24-hour spans left, rounded up: at noon, a
// deadline of 23:59 the same day is half a span away, rounded up to one - "due tomorrow". And a deadline that had
// passed an hour ago was "due today". What is meant is the calendar: how many midnights lie between now and the
// deadline, in the applicant's own time (the deadline is written as the source gives it, without a zone; it is read
// as local time, which is what the page shows it in).

// "2026-11-18 23:59" / "2026-11-18" / "2026-11-18T23:59" -> a Date in local time (a day without a time ends at 23:59),
// or null for what is not a date.
import { t } from './i18n/catalog'
import { clockOf } from './i18n/format'

export function parseDeadline(dl) {
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?/.exec(String(dl || '').trim())
  if (!m) return null
  const d = new Date(+m[1], +m[2] - 1, +m[3], m[4] === undefined ? 23 : +m[4], m[5] === undefined ? 59 : +m[5])
  return Number.isNaN(d.getTime()) ? null : d
}

const midnight = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()

// How many calendar days from `now` to the deadline: 0 today, 1 tomorrow, -1 yesterday. null for no deadline.
export function daysUntil(dl, now = new Date()) {
  const d = parseDeadline(dl)
  return d ? Math.round((midnight(d) - midnight(now)) / 86400000) : null
}

// Is the deadline over (the moment itself, not only the day)?
export function isPast(dl, now = new Date()) {
  const d = parseDeadline(dl)
  return !!d && d.getTime() < now.getTime()
}

// { text, tone }: closed / due today 23:59 / due tomorrow / N days left. tone: 'past' | 'soon' (today, tomorrow) | ''.
export function deadlineLabel(dl, now = new Date()) {
  const d = parseDeadline(dl)
  if (!d) return { text: '', tone: '' }
  if (d.getTime() < now.getTime()) return { text: t('deadline.over'), tone: 'past' }
  const days = daysUntil(dl, now)
  if (days === 0) return { text: t('deadline.todayAt', { time: clockOf(d) }), tone: 'soon' }
  if (days === 1) return { text: t('deadline.tomorrow'), tone: 'soon' }
  return { text: t('deadline.daysLeft', { n: days }, days), tone: '' }
}

// --- what is ticked in a list -----------------------------------------------------------------------------------------
// The rows that are ticked are among the rows that are shown: a filter that hides a row unticks it. (A batch used to
// act on rows the page no longer showed - "0 postings" above, "1 selected" below.)
export const keepVisible = (picked, rows) => {
  const shown = new Set(rows.map((r) => r.id))
  const kept = [...picked].filter((id) => shown.has(id))
  return kept.length === picked.size ? picked : new Set(kept)
}
