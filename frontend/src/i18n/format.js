// Dates, times and numbers in the interface language, by Intl - nothing here is written out by hand ("11月20日",
// "$" + digits): each language has them its own way (20 nov., 1 234,50 $), and Intl knows them.
import { t, tag } from './catalog'

// Server timestamps are UTC without a zone suffix.
export const asDate = (iso) => new Date(/Z$|[+-]\d\d:\d\d$/.test(iso) ? iso : iso + 'Z')

const made = new Map()
function dtf(opts) {
  const key = tag() + JSON.stringify(opts)
  if (!made.has(key)) made.set(key, new Intl.DateTimeFormat(tag(), opts))
  return made.get(key)
}

const HM = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }
export const clockOf = (d) => dtf(HM).format(d)                                      // 15:05
export const dayOf = (d) => dtf({ month: 'short', day: 'numeric' }).format(d)         // 11月20日 / Nov 20 / 20 nov.
export const shortDayOf = (d) => dtf({ month: 'numeric', day: 'numeric' }).format(d)  // 11/20 / 20/11 (a chart's axis)
// A day, the same way on every page: "11月20日" / "Nov 20" this year, with the year otherwise ("2027年1月20日" /
// "Jan 20, 2027"). A scheduled thing (a deadline, a follow-up, an expiry) is always written so; a moment of what
// happened is `when` (today / yesterday / a day).
const DAY_YEAR = { year: 'numeric', month: 'short', day: 'numeric' }
const thisYear = (d) => d.getFullYear() === new Date().getFullYear()
export const dateOf = (d) => dtf(thisYear(d) ? { month: 'short', day: 'numeric' } : DAY_YEAR).format(d)
export const dateTimeOf = (d) => t('time.dayAt', { day: dateOf(d), time: clockOf(d) })      // as `when` writes a day and a time
export const dayRange = (a, b) => t('time.range', { from: dayOf(a), to: dayOf(b) })

const midnight = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()

// A day written as the source or the applicant wrote it ("2026-11-20", "2026-11-20 23:59"): that day in local time.
export function localDay(s) {
  const m = /^(\d{4})-(\d{1,2})-(\d{1,2})/.exec(String(s || ''))
  return m ? new Date(+m[1], +m[2] - 1, +m[3], 12) : null
}
// such a day for a list ("" when there is none)
export const dayText = (s) => { const d = localDay(s); return d ? dateOf(d) : '' }
export const shortDayText = dayText      // (was "11/20": one form of a day everywhere)
// a server timestamp (UTC) as its local day
export const stampDay = (iso) => (iso ? dateOf(asDate(iso)) : '')

// A moment in a list of what happened: "Today 15:05", "Yesterday 09:30", "Nov 20 15:05".
export function when(d, now = new Date()) {
  const time = clockOf(d)
  const days = Math.round((midnight(now) - midnight(d)) / 86400000)
  if (days === 0) return t('time.today', { time })
  if (days === 1) return t('time.yesterday', { time })
  return t('time.dayAt', { day: dayOf(d), time })
}

// Several names as one phrase in the interface language ("A, B and C", "A、B 和 C") - never a typed separator.
export const listed = (xs) => new Intl.ListFormat(tag(), { style: 'short', type: 'conjunction' }).format(xs)

export const num = (v, opts) => new Intl.NumberFormat(tag(), opts).format(v)
// an amount in US dollars (what the model services charge in)
export const usd = (v, digits = 2) => num(v, { style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol', minimumFractionDigits: digits, maximumFractionDigits: digits })

// A span of time from its parts ({ hours, minutes, seconds }): "12 min 5 sec", "12分钟5秒", "1 h et 5 min".
export function duration(parts) {
  if (typeof Intl.DurationFormat === 'function') return new Intl.DurationFormat(tag(), { style: 'short' }).format(parts)
  // (a browser without it: each part as a unit of its own)
  return Object.entries(parts).filter(([, v]) => v).map(([k, v]) => num(v, { style: 'unit', unit: k.replace(/s$/, ''), unitDisplay: 'short' })).join(' ')
}

// The first day of the week where the language is spoken: 1 Monday ... 7 Sunday.
export function weekStart() {
  try {
    const loc = new Intl.Locale(tag())
    const info = typeof loc.getWeekInfo === 'function' ? loc.getWeekInfo() : loc.weekInfo
    if (info && info.firstDay) return info.firstDay
  } catch (e) { /* an older browser */ }
  return /^en(-US)?$/.test(tag()) ? 7 : 1
}
