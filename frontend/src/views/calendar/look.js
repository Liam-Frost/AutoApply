// How a calendar item is named on the page: its kind's colour class and glyph, the words for where it stands, its
// title and the line under it, its time. One place for the three views and the panel, so an item reads the same
// everywhere (calendar.js says what it is; this says it in the page's language).
import { t, tag } from '../../i18n/catalog'
import { clockOf, num } from '../../i18n/format'
import { at, FAMILY, status } from '../../calendar'

// a glyph for each kind, so that the kind is never told by colour alone
export const GLYPH = { deadline: 'clock', interview: 'user', assessment: 'check', offer: 'briefcase', info_request: 'draft', contact: 'mail', own: 'edit',
  snoozed: 'bell', sent: 'send', reply: 'inbox', task: 'refresh' }
export const family = (x) => 'ev-' + (FAMILY[x.kind] || 'system')
export const kindName = (x) => t('calendar.kind.' + x.kind)
// the words for where it stands: an interview still to come is "upcoming", other open things "to do"
export function statusName(x, now) {
  const s = status(x, now)
  if (s === 'open' && (x.kind === 'interview' || x.kind === 'assessment')) return t('calendar.status.upcoming')
  if (s === 'open' && x.kind === 'deadline') return t('calendar.status.stillOpen')
  return t('calendar.status.' + s)
}
export const statusTone = (s) => ({ done: 'ok', overdue: 'bad', open: 'info', applied: 'ok' })[s] || ''
// the name first: a posting's title for its deadline, a card's title otherwise; the company under it (not again when
// the title already is it)
export const titleOf = (x) => x.title || x.company || kindName(x)
export const companyOf = (x) => (x.company && x.company !== x.title ? x.company : '')
// one line where there is room for one: the company says more than a posting's title on a crowded grid
export const shortName = (x) => x.company || x.title || kindName(x)
export const timeOf = (x) => (x.all_day ? t('calendar.allDay') : clockOf(at(x)))
export const scoreOf = (x) => (x.score == null ? '' : t('calendar.scoreOf', { n: num(x.score, { maximumFractionDigits: 1 }) }))
// the whole line, for a tooltip and for a reader: kind, time, title, company
export const fullName = (x) => [kindName(x), timeOf(x), titleOf(x), companyOf(x)].filter(Boolean).join(t('calendar.sep'))
export const longDay = (d) => new Intl.DateTimeFormat(tag(), { weekday: 'long', month: 'long', day: 'numeric' }).format(d)
export const longDate = (d) => new Intl.DateTimeFormat(tag(), { weekday: 'short', year: 'numeric', month: 'long', day: 'numeric' }).format(d)
