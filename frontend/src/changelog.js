// The about page's version timeline, as pure functions (tests/changelog.test.js): which versions show, which start
// open, how they are grouped, filtered and searched, and how the version that was looked for is kept in the address.
// The data is the server's parse of CHANGELOG.md (backend/autoapply/changelog.py): { version, date, unreleased,
// summary, sections: [{ kind, title, items, text }], url }, newest first. Nothing here makes up a date or a link.

// The kinds of change in the order a version lists them, and the tone of each one's label (`.tag.<tone>`; '' is the
// neutral one). Colour is never the only sign: the label always has its words.
export const KINDS = ['breaking', 'added', 'changed', 'fixed', 'security', 'deprecated', 'removed', 'known', 'other']
export const TONE = { added: 'info', changed: '', fixed: 'ok', security: 'warn', breaking: 'bad', removed: '', deprecated: 'warn', known: 'warn', other: '' }

// "v2.0.2" and "2.0.2" are one version; "unreleased" is "Unreleased"
export const sameVersion = (a, b) => norm(a) === norm(b)
const norm = (v) => String(v ?? '').trim().replace(/^v(?=\d)/i, '').toLowerCase()

export const findVersion = (versions, v) => (v ? (versions || []).find((x) => sameVersion(x.version, v)) || null : null)

// The id of a version's element on the page (a version may hold characters an id should not).
export const anchor = (v) => 'cl-v-' + norm(v).replace(/[^a-z0-9]+/g, '-')

// A link of the file's link references, only as a web address (the file is ours, but what is put into an href is checked).
export const safeUrl = (u) => (/^https:\/\/[^\s"'<>]+$/i.test(String(u || '')) ? u : '')
export const linkKind = (u) => (/\/compare\//.test(u) ? 'compare' : /\/releases(\/|$)/.test(u) ? 'release' : 'other')

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

// ── counts and filters ─────────────────────────────────────────────────────────────────────────────────────────────
// How many items a version has of each kind, in the order of KINDS (sections of the same kind added up).
export function counts(v) {
  const n = {}
  for (const s of v.sections || []) n[s.kind] = (n[s.kind] || 0) + s.items.length
  return KINDS.filter((k) => n[k]).map((k) => ({ kind: k, n: n[k] }))
}
// The kinds found in the whole changelog, with how many items each has: the filter's chips.
export function kindTotals(versions) {
  const n = {}
  for (const v of versions || []) for (const c of counts(v)) n[c.kind] = (n[c.kind] || 0) + c.n
  return KINDS.filter((k) => n[k]).map((k) => ({ kind: k, n: n[k] }))
}

// The versions that match a filter, each with only what matches: { ...version, sections (narrowed), hits }.
//   kinds  the kinds chosen (none: every kind)
//   q      what was typed: every word in an item (or its section's title, or the version's number or summary)
// A version whose number is what was typed ("1.0.3", "v1.0.3") is shown whole. Without a filter, everything, as it is.
export function filterVersions(versions, { kinds = [], q = '' } = {}) {
  const ks = new Set(kinds)
  const ws = words(q)
  const list = versions || []
  if (!ks.size && !ws.length) return list.map((v) => ({ ...v, hits: counts(v).reduce((a, c) => a + c.n, 0) }))
  const out = []
  for (const v of list) {
    const whole = ws.length === 1 && sameVersion(v.version, q)
    // (found in the summary: the version is shown with it, and of its items those that match too)
    const inHead = !whole && ws.length > 0 && hasAll(v.version + ' ' + v.summary, ws)
    const sections = []
    for (const s of v.sections || []) {
      if (ks.size && !ks.has(s.kind)) continue
      const all = whole || !ws.length || hasAll(s.title, ws)
      const items = all ? s.items : s.items.filter((it) => hasAll(it, ws))
      const text = all || hasAll(s.text, ws) ? s.text : ''
      if (items.length || (text && !ks.size)) sections.push({ ...s, items, text })
    }
    const hits = sections.reduce((a, s) => a + s.items.length, 0)
    if (sections.length || (inHead && !ks.size)) out.push({ ...v, sections, hits })
  }
  return out
}

// ── the timeline ───────────────────────────────────────────────────────────────────────────────────────────────────
// Versions in runs by the year of their date, in the order given: [{ key, year, versions }]. What is not released
// yet is a group of its own ('unreleased'); a version without a written date is in a group without a year ('undated').
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

// The versions open when the page is opened: the latest release, the one that is running, and the one the address
// names. (What is not released yet starts closed: the latest release is what people come for. With no release at
// all, the first entry is open.)
export function initialOpen(versions, current, wanted) {
  const list = versions || []
  const open = new Set()
  const latest = list.find((v) => !v.unreleased) || list[0]
  if (latest) open.add(latest.version)
  for (const name of [current, wanted]) { const v = findVersion(list, name); if (v) open.add(v.version) }
  return open
}

// ── the address ────────────────────────────────────────────────────────────────────────────────────────────────────
// /about/changelog?v=2.0.2: the version that was looked for. Read from the query (anything can be typed there: one
// short value, or nothing), and written into it with the rest of the query kept.
export function versionFromQuery(query) {
  let v = query ? query.v : undefined
  if (Array.isArray(v)) v = v[0]
  v = typeof v === 'string' ? v.trim() : ''
  return v.length && v.length <= 40 ? v : ''
}
export function queryWith(query, v) {
  const q = { ...(query || {}) }
  if (v) q.v = String(v)
  else delete q.v
  return q
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
