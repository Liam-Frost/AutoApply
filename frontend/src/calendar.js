// The calendar's model (CalendarView.vue and views/calendar/): what an item is, where it stands, how much it matters,
// and how a day's items are laid out on the month grid, the week's time grid and the day's agenda. The items come from
// the server (agenda.py: {id, kind, title, start, all_day, done, state, score, priority, company, about, ...}, times
// on the local wall clock). Nothing here draws; the views draw what these return (tests/calendar.test.js).

export const KINDS = ['deadline', 'interview', 'assessment', 'offer', 'info_request', 'contact', 'own', 'snoozed', 'sent', 'reply', 'task']
export const SHOWN = ['deadline', 'interview', 'assessment', 'offer', 'info_request', 'contact', 'own']      // (the server's default)
export const RECORDS = ['snoozed', 'sent', 'reply', 'task']                                               // what happened, the program's own work
// The quick filters above the calendar: each a set of kinds, the same kinds the full filter lists one by one.
export const QUICK = [
  { id: 'deadline', kinds: ['deadline'] },
  { id: 'interview', kinds: ['interview'] },
  { id: 'assessment', kinds: ['assessment'] },
  { id: 'todo', kinds: ['offer', 'info_request', 'contact', 'own'] },
]
// The colour of a kind (style.css: --ev-<family>, --ev-<family>-bg, --ev-<family>-fg). The colour says what an item
// is; where it stands is said in words, a line through and weaker text; how much it matters, by its place.
export const FAMILY = { deadline: 'deadline', interview: 'interview', assessment: 'assessment', offer: 'offer', info_request: 'follow', contact: 'follow',
  own: 'own', snoozed: 'system', sent: 'system', reply: 'system', task: 'system' }
// what the applicant has to do by its time: late once that time has passed
const BY_THEN = ['offer', 'info_request', 'contact', 'own']
// how long an interview or an assessment is taken to last before it counts as past (nothing says how long it is)
const LASTS = 60

// --- days and moments ------------------------------------------------------------------------------------------------
const pad = (n) => String(n).padStart(2, '0')
export const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
export const parseDay = (s) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || ''); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null }
export const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
export const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate())
// the same day of another month, or that month's last day when it is shorter (31 Jan + 1 month: 28 Feb)
export function addMonths(d, n) {
  const last = new Date(d.getFullYear(), d.getMonth() + n + 1, 0).getDate()
  return new Date(d.getFullYear(), d.getMonth() + n, Math.min(d.getDate(), last))
}
// the first day of the week a day is in (first: 0 Sunday ... 6 Saturday)
export const weekOf = (d, first) => addDays(d, -((d.getDay() - first + 7) % 7))
// The days the page needs: a month as whole weeks (the grid), which holds the week and the day of the same date - the
// three views of one date are one request.
export function monthGrid(d, first) {
  const start = weekOf(new Date(d.getFullYear(), d.getMonth(), 1), first)
  const next = new Date(d.getFullYear(), d.getMonth() + 1, 1)
  const end = next.getDay() === first ? next : addDays(weekOf(next, first), 7)
  return [start, end]
}
export const daysOf = ([a, b]) => { const out = []; for (let d = a; d < b; d = addDays(d, 1)) out.push(d); return out }

// An item's moment from the parts its local time is written with - not a string handed to the browser to guess at,
// and never moved by a fixed offset.
export function at(x) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec((x && x.start) || '')
  return m ? new Date(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0)) : new Date(NaN)
}
export const dayKey = (x) => String(x.start || '').slice(0, 10)
export const minuteOf = (x) => { const d = at(x); return d.getHours() * 60 + d.getMinutes() }
// When it ends, if that is known (an interview "from 10:00 to 10:45" - the mail said): a Date on the same day after the
// start, else null. Most items have none: they are drawn at a usual length (`lanes`), which claims nothing.
export function saidEnd(x) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec((x && x.end) || '')
  if (!m) return null
  const e = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5])
  const s = at(x)
  return e > s && e.toDateString() === s.toDateString() ? e : null
}
// On the time grid: what happens at a time. A deadline is a point a day ends with, not time taken - it stays with the
// whole-day items, whatever its time (most sources give 23:59).
export const timed = (x) => !x.all_day && x.kind !== 'deadline'
// a deadline at a time of its own, not the end of the day
export const ownTime = (x) => x.kind === 'deadline' && !x.all_day && !String(x.start).endsWith('T23:59')

// --- where an item stands, and how much it matters -------------------------------------------------------------------
function endOf(x) {
  const t = at(x)
  if (x.all_day) return addDays(startOfDay(t), 1)
  if (x.kind === 'interview' || x.kind === 'assessment') return saidEnd(x) || new Date(t.getTime() + LASTS * 60000)
  return t
}
// open · done · overdue (to do by a time that has passed) · past · applied (a deadline of a posting applied to) ·
// closed (a deadline that has passed) · record (what happened, the program's own work)
export function status(x, now = new Date()) {
  if (x.done) return 'done'
  if (RECORDS.includes(x.kind)) return 'record'
  const ended = endOf(x) <= now
  if (x.kind === 'deadline') return x.state === 'sent' || x.state === 'progressed' ? 'applied' : ended ? 'closed' : 'open'
  if (!ended) return 'open'
  return BY_THEN.includes(x.kind) && x.about && x.about.todo_id ? 'overdue' : 'past'
}
export const active = (x, now) => ['open', 'overdue'].includes(status(x, now))
// a deadline worth a line of its own on a crowded day: not applied yet, and at a priority employer or scored 8 or more
export const featured = (x) => x.kind === 'deadline' && x.state === 'unapplied' && (!!x.priority || (x.score || 0) >= 8)
// 0 first: an interview; an assessment or an offer to answer; what to send, whom to get back to, one's own items; a
// featured deadline; the other deadlines; what is done, past or a record
export function rank(x, now = new Date()) {
  if (!active(x, now)) return 6
  if (x.kind === 'interview') return 0
  if (x.kind === 'assessment' || x.kind === 'offer') return 1
  if (x.kind === 'deadline') return featured(x) ? 3 : 4
  return 2
}
const byName = (a, b) => String(a.title).localeCompare(String(b.title))
// deadlines: the ones still to act on first; among them a priority employer, then the score, then the time
export const deadlineOrder = (now = new Date()) => (a, b) =>
  (status(a, now) !== 'open') - (status(b, now) !== 'open') || (!!b.priority - !!a.priority) || ((b.score ?? -1) - (a.score ?? -1))
  || String(a.start).localeCompare(String(b.start)) || byName(a, b)
export const byRank = (now = new Date()) => (a, b) =>
  rank(a, now) - rank(b, now) || (a.kind === 'deadline' && b.kind === 'deadline' ? deadlineOrder(now)(a, b) : 0)
  || String(a.start).localeCompare(String(b.start)) || byName(a, b)

// --- a day on the month grid, or in the week's whole-day strip -------------------------------------------------------
// With room for `lines` lines: what matters most each on a line (`top`), the day's other deadlines as one count
// (`deadlines`), what is done or past where room is left (`rest`) and how many others did not fit (`more`). Every
// item is in exactly one of them: one shown on its own line is not counted again. When the room is short, what
// matters most still gets its line: the deadlines are then counted with the others in `more`.
export function plan(list, lines, now = new Date()) {
  const sorted = list.slice().sort(byRank(now))
  const dl = sorted.filter((x) => x.kind === 'deadline')
  const head = sorted.filter((x) => x.kind !== 'deadline' && rank(x, now) < 6)
  const tail = sorted.filter((x) => x.kind !== 'deadline' && rank(x, now) >= 6)
  const order = [...head, ...dl.filter((x) => rank(x, now) === 3), ...tail]
  const others = head.length + tail.length
  const room = Math.max(1, lines)
  const split = (k) => {
    const shown = order.slice(0, k)
    return { shown, grouped: dl.filter((x) => !shown.includes(x)), more: others - shown.filter((x) => x.kind !== 'deadline').length }
  }
  const out = (shown, deadlines, more) => ({ top: shown.filter((x) => rank(x, now) < 6), deadlines, rest: shown.filter((x) => rank(x, now) >= 6), more })
  // the deadlines as their own line, with at least one of what matters most when there is any
  for (let k = order.length; k >= (head.length ? 1 : 0); k--) {
    const s = split(k)
    if (k + (s.grouped.length ? 1 : 0) + (s.more ? 1 : 0) <= room) return out(s.shown, s.grouped, s.more)
  }
  // short of room: what matters most first, everything else in one "+N"
  const k = Math.min(head.length, room - 1)
  if (k >= 1) { const s = split(k); return out(s.shown, [], s.more + s.grouped.length) }
  const s = split(0)
  return (s.grouped.length ? 1 : 0) + (s.more ? 1 : 0) <= room ? out([], s.grouped, s.more) : out([], [], others + dl.length)
}

// --- the week's time grid ---------------------------------------------------------------------------------------------
// The timed items of a day: from their start to their end when the mail said one, else `least` minutes tall (the item
// is not given an end - this is only how it is drawn), side by side where they meet. Minutes from midnight.
export function lanes(list, least = 45) {
  const boxes = list.map((x) => { const top = minuteOf(x), e = saidEnd(x); return { x, top, end: Math.min(1440, e ? e.getHours() * 60 + e.getMinutes() : top + least) } })
    .sort((a, b) => a.top - b.top || a.end - b.end || String(a.x.id).localeCompare(String(b.x.id)))
  const out = []
  let group = []
  let groupEnd = -1
  const flush = () => {
    const cols = []
    for (const b of group) {
      let i = cols.findIndex((end) => end <= b.top)
      if (i < 0) { i = cols.length; cols.push(0) }
      cols[i] = b.end
      b.col = i
    }
    for (const b of group) b.cols = cols.length
    out.push(...group)
    group = []
  }
  for (const b of boxes) {
    if (group.length && b.top >= groupEnd) { flush(); groupEnd = -1 }
    group.push(b)
    groupEnd = Math.max(groupEnd, b.end)
  }
  if (group.length) flush()
  return out.map(({ x, top, end, col, cols }) => ({ item: x, top, height: Math.max(end - top, 15), col, cols }))
}

// --- the day's agenda -------------------------------------------------------------------------------------------------
// What has a time, the deadlines (to act on first), the other things to do, and what is done, past or a record.
export function dayGroups(list, now = new Date()) {
  const g = { timed: [], deadlines: [], other: [], past: [] }
  for (const x of list) {
    const s = status(x, now)
    if (x.kind === 'deadline') g.deadlines.push(x)
    else if (s === 'done' || s === 'past' || s === 'record') g.past.push(x)
    else if (timed(x)) g.timed.push(x)
    else g.other.push(x)
  }
  const byTime = (a, b) => String(a.start).localeCompare(String(b.start)) || byName(a, b)
  g.timed.sort(byTime)
  g.deadlines.sort(deadlineOrder(now))
  g.other.sort(byRank(now))
  g.past.sort(byTime)
  return g
}

// --- the line above the calendar --------------------------------------------------------------------------------------
// Counted from what the server gave for the days around today, whatever the filters: deadlines to act on today and in
// the next 7 days (today and the 6 after it), interviews still to come in those days, and what was to be done by a
// time that has passed.
export function summary(list, now = new Date()) {
  const today = iso(now)
  const end = iso(addDays(now, 7))
  const open = list.filter((x) => status(x, now) === 'open')
  const dl = open.filter((x) => x.kind === 'deadline')
  const interviews = open.filter((x) => x.kind === 'interview' && dayKey(x) < end).sort((a, b) => String(a.start).localeCompare(String(b.start)))
  return {
    today: dl.filter((x) => dayKey(x) === today).length,
    week: dl.filter((x) => dayKey(x) >= today && dayKey(x) < end).length,
    interviews: interviews.length,
    next: interviews[0] || null,
    overdue: list.filter((x) => status(x, now) === 'overdue').sort((a, b) => String(a.start).localeCompare(String(b.start))),
  }
}

// --- the filters ------------------------------------------------------------------------------------------------------
export const matches = (x, q) => {
  const s = String(q || '').trim().toLowerCase()
  return !s || [x.title, x.company, x.subject, x.note].some((v) => String(v || '').toLowerCase().includes(s))
}
// a quick filter: all its kinds shown, some, or none
export function quickState(kinds, group) {
  const n = group.kinds.filter((k) => kinds.includes(k)).length
  return n === 0 ? 'off' : n === group.kinds.length ? 'on' : 'some'
}
export const everything = (kinds) => SHOWN.every((k) => kinds.includes(k))
// Pressing a quick filter: from everything, only that one; otherwise it is added or taken away (and with nothing left,
// everything again). What the full filter added (records, the program's work) stays.
export function pressQuick(kinds, group) {
  const records = kinds.filter((k) => RECORDS.includes(k))
  if (everything(kinds)) return [...group.kinds, ...records]
  const next = quickState(kinds, group) === 'on' ? kinds.filter((k) => !group.kinds.includes(k)) : [...new Set([...kinds, ...group.kinds])]
  return next.some((k) => SHOWN.includes(k)) ? next : [...SHOWN, ...records]
}
