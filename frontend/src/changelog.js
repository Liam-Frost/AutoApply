// The about page's changelog, as pure functions (tests/changelog.test.js): which version is open, how the versions are
// grouped, filtered and searched, and how the open one is kept in the address. The data is the server's
// (backend/autoapply/changelog.py), newest first: { version, date, unreleased, summary, sections: [{ kind, title, items,
// text }], url } - the full notes of CHANGELOG.md, as written - and { title, highlights: [{ kind, title, text?,
// derived? }] } - the short name of the release and what to look at in it, in every language of the interface
// (highlights.json), or, for a version the file has no entry for yet, the bold leads of its notes in English
// (`derived`). Nothing here makes up a date, a link or a summary.

// The kinds of change in the order the type filter lists them, and the tone of each one's mark (`.cl-dot.tone-<tone>`;
// '' is the neutral one). Colour is never the only sign: the kind always has its words.
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

// The words of a kind and of a version's link, with the catalog's `t` (given, so that this stays pure).
const KIND_WORDS = {
  added: (t) => t('about.changelog.kind.added'), changed: (t) => t('about.changelog.kind.changed'), fixed: (t) => t('about.changelog.kind.fixed'),
  security: (t) => t('about.changelog.kind.security'), breaking: (t) => t('about.changelog.kind.breaking'), removed: (t) => t('about.changelog.kind.removed'),
  deprecated: (t) => t('about.changelog.kind.deprecated'), known: (t) => t('about.changelog.kind.known'), other: (t) => t('about.changelog.kind.other'),
}
export const kindLabel = (k, t) => (KIND_WORDS[k] || KIND_WORDS.other)(t)
// "Code changes" for a compare page, "Release page" for a release, with the long form for a tooltip; null without a
// web address.
export function linkOf(v, t) {
  const url = safeUrl(v && v.url)
  if (!url) return null
  const kind = linkKind(url)
  if (kind === 'compare') return { url, label: t('about.changelog.compare'), tip: v.unreleased ? t('about.changelog.compareUnreleased') : t('about.changelog.compareTip', { v: v.version }) }
  if (kind === 'release') return { url, label: t('about.changelog.release'), tip: t('about.changelog.releaseTip', { v: v.version }) }
  return { url, label: t('about.changelog.link'), tip: '' }
}

// A text given in several languages ({ en, zh, fr }) in the interface's language, else English, else any.
export function inLang(words, lang) {
  if (!words || typeof words !== 'object') return ''
  return words[lang] || words.en || Object.values(words).find((x) => typeof x === 'string' && x) || ''
}
// Is that text English where the interface is not? (A derived highlight, or a title not translated: said to a reader.)
export const isEnglish = (words, lang) => lang !== 'en' && !!words && !words[lang] && !!words.en

// ── the versions ───────────────────────────────────────────────────────────────────────────────────────────────────
// The releases (what is not released yet is a block of its own, above them), the unreleased entry, the newest release.
export const releases = (versions) => (versions || []).filter((v) => !v.unreleased)
export const unreleasedOf = (versions) => (versions || []).find((v) => v.unreleased) || null
export const latestOf = (versions) => releases(versions)[0] || null

// Releases in runs by the year of their date, in the order given: [{ key, year, versions }]. A version without a
// written date is in a run without a year ('undated'); what is not released yet is a run of its own ('unreleased').
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

// A version's highlights by kind, the kinds in the order they first come (the order the release's author chose):
// [{ kind, items }].
export function byKind(highlights) {
  const out = []
  for (const h of highlights || []) {
    const g = out.find((x) => x.kind === h.kind)
    if (g) g.items.push(h)
    else out.push({ kind: h.kind, items: [h] })
  }
  return out
}

// ── the accordion ──────────────────────────────────────────────────────────────────────────────────────────────────
// One version open at most: `open` is its name, or null. Pressing a version opens it (and so closes the one that was
// open); pressing the open one closes it. Nothing opens by itself: not the newest release, not the running version,
// not a search - only a press, or an address that names a version.
export const toggled = (open, name) => (open != null && sameVersion(open, name) ? null : name)

// /about/changelog?v=2.0.2: the open version. Read from the query (anything can be typed there: one short value, or
// nothing), and written into it with the rest of the query kept; no version open, no `v`.
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
// The version an address opens: its name as the data writes it ("v1.0.3" opens "1.0.3"), or null when it names none
// or one the changelog does not have.
export const openFromQuery = (versions, query) => { const v = findVersion(versions, versionFromQuery(query)); return v ? v.version : null }

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
// What a search reads of a highlight: its title and sentence in the interface's language and in English.
const highlightWords = (h, lang) => [inLang(h.title, lang), h.title && h.title.en, inLang(h.text, lang), h.text && h.text.en].filter(Boolean).join(' ')

// How many entries of a version's full notes match: each bullet and each section's paragraphs of the kind (all of a
// section whose title has the words), and the summary (it has no kind).
function notesMatching(v, kind, ws) {
  let n = !kind && ws.length && hasAll(v.summary, ws) ? 1 : 0
  for (const s of v.sections || []) {
    if (kind && s.kind !== kind) continue
    const entries = [...(s.items || []), ...(s.text ? [s.text] : [])]
    n += !ws.length || hasAll(s.title, ws) ? entries.length : entries.filter((e) => hasAll(e, ws)).length
  }
  return n
}

// The versions a search and a type leave, each as { v, highlights, notes, more }:
//   highlights  its highlights that match (of the type; every word in the title or the sentence, in the interface's
//               language or English) - all of them when its number is what was typed, or when its title has the
//               words and none of its highlights has them
//   notes       how many entries of its full notes match
//   more        how many more the full notes have than the highlights shown ("n more in the full notes")
// A version stays when anything of it matches. Without a search or a type: every version, with all its highlights.
export function filterVersions(versions, { kind = '', q = '', lang = 'en' } = {}) {
  const ws = words(q)
  const list = versions || []
  if (!kind && !ws.length) return list.map((v) => ({ v, highlights: v.highlights || [], notes: 0, more: 0 }))
  const out = []
  for (const v of list) {
    const ofKind = (v.highlights || []).filter((h) => !kind || h.kind === kind)
    const number = ws.length === 1 && sameVersion(v.version, q)
    const titled = !number && ws.length > 0 && hasAll([inLang(v.title, lang), v.title && v.title.en].filter(Boolean).join(' '), ws)
    const hit = number || !ws.length ? ofKind : ofKind.filter((h) => hasAll(highlightWords(h, lang), ws))
    const highlights = hit.length || !titled ? hit : ofKind
    const notes = notesMatching(v, kind, number ? [] : ws)
    if (!highlights.length && !notes && !((number || titled) && !kind)) continue
    out.push({ v, highlights, notes, more: Math.max(0, notes - highlights.length) })
  }
  return out
}

// The type filter's choices: every kind the changelog has (in its highlights or its notes), with how many versions
// choosing it would leave under the search typed (0: nothing to find there now).
export function typeCounts(versions, { q = '', lang = 'en' } = {}) {
  const present = new Set()
  for (const v of versions || []) {
    for (const h of v.highlights || []) present.add(h.kind)
    for (const s of v.sections || []) present.add(s.kind)
  }
  return KINDS.filter((k) => present.has(k)).map((kind) => ({ kind, n: filterVersions(versions, { kind, q, lang }).length }))
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
