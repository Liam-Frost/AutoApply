// The reminders a kind of calendar item gets by itself (Settings, `calendar.reminders`; backend/autoapply/alarms.py):
// a list of minutes before the item - [1440, 30] is a day and half an hour before, [0] at its start, [] none. This is
// the one place that says what such a list is (whole minutes, each once, the largest first) and what one of its
// numbers is called; ReminderRules.vue draws it. Pure, but for the words.
import { t as T } from './i18n/catalog'

export const DAY = 1440
export const WEEK = 7 * DAY
// the most a reminder may be ahead: alarms.add keeps one within 60 days, and the settings refuse more (put_settings)
export const MOST = 60 * DAY
// what the "+" offers at once (alarms.CHOICES, with the start itself and without the five minutes)
export const PRESETS = [0, 15, 30, 60, 120, DAY, 2 * DAY, WEEK]
export const UNITS = { minutes: 1, hours: 60, days: DAY }

// The list as it is kept: whole minutes from 0 to MOST, each once, the largest first. What is not a number is dropped.
export function normalize(list) {
  const out = new Set()
  for (const x of Array.isArray(list) ? list : []) {
    if (x === null || x === '' || typeof x === 'boolean') continue
    const n = Math.round(Number(x))
    if (Number.isFinite(n) && n >= 0 && n <= MOST) out.add(n)
  }
  return [...out].sort((a, b) => b - a)
}
export const withAdded = (list, m) => normalize([...normalize(list), m])
export const without = (list, m) => normalize(list).filter((x) => x !== m)
export const has = (list, m) => normalize(list).includes(m)
export const toggled = (list, m) => (has(list, m) ? without(list, m) : withAdded(list, m))

// An item that lasts a whole day is reminded in the morning (`calendar.allday_at`): a reminder of part of a day is the
// morning before, as alarms.give_defaults makes it - so for such an item only whole days are told apart.
export const asDays = (m) => Math.ceil(m / DAY)

// What an amount typed into the "+" comes to: { minutes }, { empty: true }, or { error } - why not, as the key of its
// words (controls.reminders.<error>): not a whole number, below zero, further ahead than the backend keeps, there already.
export function parseAmount(text, unit = 'minutes', list = []) {
  const s = String(text ?? '').trim()
  if (!s) return { empty: true }
  if (!/^[-+]?\d+(?:[.,]\d+)?$/.test(s)) return { error: 'notWhole' }
  const n = Number(s.replace(',', '.'))
  if (n < 0) return { error: 'negative' }
  if (!Number.isInteger(n)) return { error: 'notWhole' }
  const minutes = n * (UNITS[unit] || 1)
  if (minutes > MOST) return { error: 'tooFar' }
  if (has(list, minutes)) return { error: 'duplicate', minutes }
  return { minutes }
}

// One reminder in words: "1 day before", "30 minutes before", "At the start" - for an item of a whole day "Morning of
// the day" and whole days ("2 hours before" is the morning before: "1 day before"). The calendar's own words where
// they fit (calendar.alarm.*).
export function formatReminder(m, { allDay = false } = {}, t = T) {
  const n = Math.max(0, Math.round(Number(m) || 0))
  if (allDay) {
    const d = asDays(n)
    if (d === 0) return t('controls.reminders.dayMorning')
    if (d % 7 === 0) return t('controls.reminders.weeks', { n: d / 7 }, d / 7)
    return t('calendar.alarm.days', { n: d }, d)
  }
  if (n === 0) return t('controls.reminders.atStart')
  if (n % WEEK === 0) return t('controls.reminders.weeks', { n: n / WEEK }, n / WEEK)
  if (n % DAY === 0) return t('calendar.alarm.days', { n: n / DAY }, n / DAY)
  if (n % 60 === 0) return t('calendar.alarm.hours', { n: n / 60 }, n / 60)
  return t('calendar.alarm.minutes', { n }, n)
}

// The presets that mean something for an item: all of them, or for a whole day the ones that are whole days.
export const presetsFor = (allDay) => (allDay ? PRESETS.filter((m) => m % DAY === 0) : PRESETS)
