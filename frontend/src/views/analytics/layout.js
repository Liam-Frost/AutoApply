// How the analysis page composes its cards. Pure functions - no Vue - so that the rules can be tested.
//
// Two cards share a row only when what they hold is of about one height; a short card beside a tall one would be
// stretched to the tall one's height and stand mostly empty (or, not stretched, end halfway down its row). What a card
// holds depends on the data (four failure reasons or one, twelve models or two), so whether two cards pair is decided
// from the data, by the rough height of their contents: paired when the shorter is at least `LEAST` of the taller,
// otherwise each takes the whole row.

import { localDay } from '../../i18n/format'

// Rough heights in px of the parts of an analysis card, as the page's CSS draws them (measured on the page). They only
// decide pairing - nothing is sized by them - and need to be right to within about a tenth.
export const H = {
  card: 64,         // the card's padding and its head (title line)
  foot: 44,         // a card-foot with a button
  hint: 32,         // a card-foot with one line of hint
  bar: 30,          // one row of .hbars
  reason: 32,       // one row of .reason
  thead: 42,        // the head row of a compact table
  row: 40,          // a compact table row (one line)
  row2: 52,         // a table row of two lines (.an-table.two)
  entity: 56,       // a DataTable row of the standard density (two-line EntityCell)
  legend: 26,       // one line of a chart legend
}
// a card of bars by category, a list of failure reasons, a compact table
export const bars = (n, { foot = 0 } = {}) => H.card + n * H.bar + foot
export const reasons = (n, { foot = 0 } = {}) => H.card + n * H.reason + foot
export const table = (n, { row = H.row, foot = 0, extra = 0 } = {}) => H.card + H.thead + n * row + foot + extra

// the shorter card must have at least this share of the taller one's height: at most about a third of it empty
export const LEAST = 0.7
export function pairs(a, b, least = LEAST) {
  if (!(a > 0) || !(b > 0)) return false
  return Math.min(a, b) / Math.max(a, b) >= least
}

// The first rows of a ranked list, and the rest (shown behind a control). One row alone is never hidden: a control
// that reveals a single row takes the room of the row.
export function splitTop(rows, top = 5) {
  const all = rows || []
  if (all.length <= top + 1) return { shown: all, rest: [] }
  return { shown: all.slice(0, top), rest: all.slice(top) }
}

// Where a to-do that is still open stands, for a list: put off (until a day), a date of its own (passed, or when), the
// deadline of the posting it is about (passed, or when), or simply open. `today` is the local day ('YYYY-MM-DD' or a
// Date). Returns { key, tone, day } - the words are the page's (analytics.backlog.st.<key>), `day` a 'YYYY-MM-DD'.
export function standing(item, today = new Date()) {
  const t = today instanceof Date ? new Date(today.getFullYear(), today.getMonth(), today.getDate(), 12) : localDay(today)
  const days = (s) => Math.round((localDay(s) - t) / 86400000)
  const day = (s) => String(s).slice(0, 10)
  if (item.snoozed_until) return { key: 'snoozed', tone: '', day: day(item.snoozed_until) }
  if (item.due_at && localDay(item.due_at)) {
    const d = days(item.due_at)
    return d < 0 ? { key: 'datePassed', tone: 'bad', day: day(item.due_at) } : { key: 'on', tone: d <= 1 ? 'warn' : '', day: day(item.due_at) }
  }
  if (item.deadline && localDay(item.deadline)) {
    const d = days(item.deadline)
    return d < 0 ? { key: 'closed', tone: 'bad', day: day(item.deadline) } : { key: 'closes', tone: d <= 3 ? 'warn' : '', day: day(item.deadline) }
  }
  return { key: 'open', tone: '', day: '' }
}
