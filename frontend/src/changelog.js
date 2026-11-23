// The about page's changelog, as pure functions (tests/changelog.test.js): which version is open and how a deep link
// opens one, how the versions are grouped, which changes an opened version shows, and what a search and the type
// filter leave. The data is the server's (backend/autoapply/changelog.py: releases.json, generated from changes/ by
// scripts/release.py, and the pending change fragments), newest first:
//   { version, date, unreleased, title: { en, zh?, fr? }, intro, known_limits: [md], url,
//     changes: [{ id, type, scope, summary: { en, zh?, fr? }, details: md, highlight }] }
// `changes` are in the release's order (its manifest). Summaries are written in every language at development time and
// shown in the interface's language, else in English (said so); intro, details and known limits are English. Nothing
// here makes up a date, a link or a summary, and nothing cuts the details.

// The types of change in the order a release's notes list them (autoapply.release.TYPE_ORDER), and the tone of each
// one's mark (`.cl-dot.tone-<tone>`; '' is the neutral one). Colour is never the only sign: the type always has its words.
export const TYPES = ['added', 'changed', 'deprecated', 'removed', 'fixed', 'security']
export const TONE = { added: 'info', changed: '', deprecated: 'warn', removed: '', fixed: 'ok', security: 'warn' }
// How many changes an opened version shows; the rest are in its full notes.
export const SHOWN = 6

// "v2.0.2" and "2.0.2" are one version; "unreleased" is "Unreleased"
export const sameVersion = (a, b) => norm(a) === norm(b)
const norm = (v) => String(v ?? '').trim().replace(/^v(?=\d)/i, '').toLowerCase()

export const findVersion = (versions, v) => (v ? (versions || []).find((x) => sameVersion(x.version, v)) || null : null)

// The id of a version's element on the page (a version may hold characters an id should not).
export const anchor = (v) => 'cl-v-' + norm(v).replace(/[^a-z0-9]+/g, '-')

// A link of the data, only as a web address (the file is ours, but what is put into an href is checked).
export const safeUrl = (u) => (/^https:\/\/[^\s"'<>]+$/i.test(String(u || '')) ? u : '')

// The words of a type, with the catalog's `t` (given, so that this stays pure; each key written out, so that the
// i18n check finds it).
const TYPE_WORDS = {
  added: (t) => t('about.changelog.kind.added'), changed: (t) => t('about.changelog.kind.changed'), deprecated: (t) => t('about.changelog.kind.deprecated'),
  removed: (t) => t('about.changelog.kind.removed'), fixed: (t) => t('about.changelog.kind.fixed'), security: (t) => t('about.changelog.kind.security'),
}
// (a type this interface does not know yet - a newer release's - is named as the data writes it)
export const typeLabel = (k, t) => (TYPE_WORDS[k] ? TYPE_WORDS[k](t) : String(k || ''))
// A version's page on GitHub ("Release page", the long form for a tooltip); null without a web address.
export function linkOf(v, t) {
  const url = safeUrl(v && v.url)
  return url ? { url, label: t('about.changelog.release'), tip: t('about.changelog.releaseTip', { v: v.version }) } : null
}

// A text given in several languages ({ en, zh, fr }) in the interface's language, else English, else any.
export function inLang(words, lang) {
  if (!words || typeof words !== 'object') return ''
  return words[lang] || words.en || Object.values(words).find((x) => typeof x === 'string' && x) || ''
}
// Is that text English where the interface is not? (Not translated yet: said to a reader, and lang="en".)
export const isEnglish = (words, lang) => lang !== 'en' && !!words && !words[lang] && !!words.en

// ── the versions ───────────────────────────────────────────────────────────────────────────────────────────────────
// The releases (what is not released yet is a block of its own, above them), the unreleased entry, the newest release.
export const releases = (versions) => (versions || []).filter((v) => !v.unreleased)
export const unreleasedOf = (versions) => (versions || []).find((v) => v.unreleased) || null
export const latestOf = (versions) => releases(versions)[0] || null

// Releases in runs by the year of their date, in the order given: [{ key, year, versions }]. A version without a
// date is in a run without a year ('undated'); what is not released yet is a run of its own ('unreleased').
export function groupByYear(versions) {
  const groups = []
  for (const v of versions || []) {
    const key = v.unreleased ? 'unreleased' : /^\d{4}/.test(v.date || '') ? v.date.slice(0, 4) : 'undated'
    const last = groups[groups.length - 1]
    if (last && last.key === key) last.versions.push(v)
    else groups.push({ key, year: /^\d{4}$/.test(key) ? key : '', versions: [v] })
  }
  return groups
}

// ── what an opened version shows ───────────────────────────────────────────────────────────────────────────────────
// At most `max` of the changes given: the release's highlights first, then the rest, each in the release's order.
export function pick(changes, max = SHOWN) {
  const list = changes || []
  return [...list.filter((c) => c.highlight), ...list.filter((c) => !c.highlight)].slice(0, max)
}
// Changes grouped by type, the types in TYPES order (one the interface does not know after them), each group in the
// order given: [{ type, items }].
export function byType(changes) {
  const out = TYPES.map((type) => ({ type, items: [] }))
  for (const c of changes || []) {
    let g = out.find((x) => x.type === c.type)
    if (!g) out.push((g = { type: c.type, items: [] }))
    g.items.push(c)
  }
  return out.filter((g) => g.items.length)
}

// ── the accordion and the deep link ────────────────────────────────────────────────────────────────────────────────
// One version open at most: `open` is its name, or null. Pressing a version opens it (and so closes the one that was
// open); pressing the open one closes it. Nothing opens by itself: not the newest release, not the running version,
// not Unreleased, not a search or a type - only a press, or a deep link. A press is not written into the address.
export const toggled = (open, name) => (open != null && sameVersion(open, name) ? null : name)

// /about/changelog?v=2.0.2 (the overview's "What's new in 2.0.2", a link from elsewhere): the version named. Anything
// can be typed there: one short value, or nothing.
export function versionFromQuery(query) {
  let v = query ? query.v : undefined
  if (Array.isArray(v)) v = v[0]
  v = typeof v === 'string' ? v.trim() : ''
  return v.length && v.length <= 40 ? v : ''
}
// The version an address names, as the data writes it ("v1.0.3" names "1.0.3"), or null when it names none or one the
// changelog does not have.
export const openFromQuery = (versions, query) => { const v = findVersion(versions, versionFromQuery(query)); return v ? v.version : null }
// The query with the version taken out (the rest kept).
export function withoutVersion(query) {
  const q = { ...(query || {}) }
  delete q.v
  return q
}
// What a deep link does when it arrives (the versions read): null when the address names no version (`v` absent) -
// nothing to do; else { open: the version to open, or null when the changelog does not have it, missing: what the
// address named then (said in a notice), query: the address's query without `v`, to replace it with }. Taken out of
// the address at once, a link opens its version once: a refresh, back to it, another tab and back show all closed.
export function arrival(versions, query) {
  if (!query || query.v === undefined) return null
  const open = openFromQuery(versions, query)
  return { open, missing: open ? '' : versionFromQuery(query), query: withoutVersion(query) }
}

// ── text ───────────────────────────────────────────────────────────────────────────────────────────────────────────
// The words of a piece of markdown, without its marks: what a search reads.
export function plain(md) {
  return String(md || '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/[*_`>#|]/g, ' ')
    .replace(/^\s*[-+]\s+/gm, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}
// For comparing: lower case, without accents ("Résumé" finds "resume").
export const fold = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase()
// The words of what was typed; every one of them has to be found.
export const words = (q) => fold(q).split(/\s+/).filter(Boolean)
export const hasAll = (text, ws) => { if (!ws.length) return true; const t = fold(plain(text)); return ws.every((w) => t.includes(w)) }

// Marks the words found in HTML that md.js made (escaped text between tags): only in the text, never in a tag or an
// entity, and as typed (without the accent folding, which cannot be undone in place).
export function mark(html, ws) {
  const list = (ws || []).filter((w) => w.length >= 2).map((w) => w.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'))
  if (!list.length) return html
  // (a word is tried first where it begins; else an entity such as &amp; is passed over whole, so "amp" is not found in it)
  const re = new RegExp('(' + list.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).sort((a, b) => b.length - a.length).join('|') + ')|&[a-z#0-9]+;', 'gi')
  return String(html).replace(/(^|>)([^<]+)/g, (m, open, text) => open + text.replace(re, (found, w) => (w ? '<mark>' + w + '</mark>' : found)))
}

// ── search and the type filter ─────────────────────────────────────────────────────────────────────────────────────
// What a search reads of a change: its summary in the interface's language and in English, and its details.
const changeWords = (c, lang) => [inLang(c.summary, lang), c.summary && c.summary.en, c.details].filter(Boolean).join(' ')

// The versions a search and a type leave, each as { v, changes, notes }:
//   changes  its changes that match (of the type; every word in the summary - the interface's language or English -
//            or the details) - all of them (of the type) when its number is what was typed, or when its title has the
//            words and none of its changes has them
//   notes    how many other parts of its full notes match (the intro, a known limit; they have no type)
// A version stays when anything of it matches. Without a search or a type: every version with all its changes.
// It decides what is shown, never what is open.
export function filterVersions(versions, { type = '', q = '', lang = 'en' } = {}) {
  const ws = words(q)
  const list = versions || []
  if (!type && !ws.length) return list.map((v) => ({ v, changes: v.changes || [], notes: 0 }))
  const out = []
  for (const v of list) {
    const ofType = (v.changes || []).filter((c) => !type || c.type === type)
    const number = ws.length === 1 && sameVersion(v.version, ws[0])
    const titled = !number && ws.length > 0 && hasAll([inLang(v.title, lang), v.title && v.title.en].filter(Boolean).join(' '), ws)
    const hit = number || !ws.length ? ofType : ofType.filter((c) => hasAll(changeWords(c, lang), ws))
    const changes = hit.length || !titled ? hit : ofType
    const notes = type || number || !ws.length ? 0 : [v.intro, ...(v.known_limits || [])].filter((x) => x && hasAll(x, ws)).length
    if (!changes.length && !notes && !((number || titled) && !type)) continue
    out.push({ v, changes, notes })
  }
  return out
}

// What an opened version shows of what the filter left ({ changes, notes }): at most SHOWN changes (highlights first),
// and how many more its full notes have of what was left.
export function shownOf(found) {
  const changes = pick(found ? found.changes : [])
  return { changes, more: (found ? found.changes.length - changes.length + found.notes : 0) }
}

// The type filter's choices: every type the changelog has, with how many changes it has of that type under the search
// typed (0: nothing to find there now).
export function typeCounts(versions, { q = '', lang = 'en' } = {}) {
  const present = []
  for (const v of versions || []) for (const c of v.changes || []) if (c.type && !present.includes(c.type)) present.push(c.type)
  const order = [...TYPES.filter((k) => present.includes(k)), ...present.filter((k) => !TYPES.includes(k))]
  return order.map((type) => ({ type, n: filterVersions(versions, { type, q, lang }).reduce((n, f) => n + f.changes.length, 0) }))
}

// ── licences (LicensesTab.vue) ─────────────────────────────────────────────────────────────────────────────────────
// The components the server lists ({ name, version, license, direct, summary, homepage }), narrowed by what was
// typed (name, licence or summary; every word), by direct / all, and by one licence as it is written.
export function filterComponents(rows, { q = '', scope = 'all', license = '' } = {}) {
  const ws = words(q)
  return (rows || []).filter((r) => (scope !== 'direct' || r.direct) && (!license || r.license === license)
    && (!ws.length || hasAll([r.name, r.license, r.summary].join(' '), ws)))
}
// The licences found, each with how many components have it, the most common first.
export function licenseOptions(rows) {
  const n = new Map()
  for (const r of rows || []) if (r.license) n.set(r.license, (n.get(r.license) || 0) + 1)
  return [...n].map(([license, count]) => ({ license, count })).sort((a, b) => b.count - a.count || a.license.localeCompare(b.license))
}
// Sorted by a column ({ by, dir }): names and licences as words, versions as versions (1.10 after 1.9), direct first.
export function sortComponents(rows, sort) {
  const by = (sort && sort.by) || 'name'
  const dir = sort && sort.dir === 'desc' ? -1 : 1
  const key = (r) => (by === 'dependency' ? (r.direct ? 0 : 1) : String(r[by] ?? ''))
  const cmp = (a, b) => {
    const x = key(a), y = key(b)
    const c = typeof x === 'number' ? x - y : x.localeCompare(y, undefined, { numeric: true, sensitivity: 'base' })
    return c || a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
  }
  return [...(rows || [])].sort((a, b) => dir * cmp(a, b))
}
