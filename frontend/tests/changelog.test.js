// The about page's changelog and licences, as pure functions (src/changelog.js): the accordion (one version open, by a
// press or once by a deep link - never by itself, by a search or by a type; a press is not written into the address),
// what an opened version shows (at most six changes, the highlights first, by type, in the interface's language with
// English as the fallback), the search and the type filter, and the licence table's filter and sort.
import { describe, expect, it } from 'vitest'
import {
  SHOWN, TYPES, anchor, arrival, byType, filterComponents, filterVersions, findVersion, fold, groupByYear, hasAll, inLang, isEnglish, latestOf, licenseOptions,
  linkOf, mark, openFromQuery, pick, plain, releases, safeUrl, sameVersion, shownOf, sortComponents, toggled, typeCounts, typeLabel, unreleasedOf, versionFromQuery,
  withoutVersion, words,
} from '../src/changelog.js'

// made up, in the shape of GET /api/about/changelog's versions (releases.json's ReleaseEntry + unreleased)
const w = (en, zh, fr) => ({ en, ...(zh ? { zh } : {}), ...(fr ? { fr } : {}) })
let n = 0
const ch = (type, summary, { highlight = false, details = '' } = {}) => ({ id: `2031-01-01-c${++n}-ab12`, type, scope: 'ui', summary, details, highlight })
const tag = (v) => `https://github.com/o/r/releases/tag/v${v}`
const V = [
  { version: 'Unreleased', date: '', unreleased: true, title: {}, intro: '', known_limits: [], url: '',
    changes: [ch('fixed', w('Menus stay open', 'Z-menus', 'Les menus restent ouverts'), { details: 'A menu no longer closes at once.' })] },
  { version: '2.0.2', date: '2026-11-22', unreleased: false, title: w('Calendar and phone cards', 'Z-calendar', 'Agenda'), url: tag('2.0.2'),
    intro: '2.0.2 brings a **calendar** with reminders.', known_limits: ['The packages are not code-signed.'],
    changes: [
      ch('changed', w('Postings and applications apart', 'Z-postings', 'Offres et candidatures')),
      ch('fixed', w('Dates one way', 'Z-dates', 'Dates')),
      ch('added', w('Calendar with reminders', 'Z-cal', 'Agenda avec rappels'), { highlight: true, details: 'Every time on one page.\n\n- Reminders of your own\n- A feed for your calendar app' }),
      ch('removed', w('The old importer', 'Z-importer', 'L’ancien importateur')),
      ch('deprecated', w('The old setting', 'Z-setting', 'L’ancien réglage')),
      ch('added', w('Cards on your phone', 'Z-phone', 'Cartes sur le téléphone'), { highlight: true }),
      ch('security', w('Other origins refused', 'Z-origins', 'Autres origines refusées'), { highlight: true }),
      ch('fixed', w('A mail is sent once', undefined, 'Un courriel envoyé une fois')),
    ] },
  { version: '2.0.0', date: '2026-11-21', unreleased: false, title: w('One agent'), intro: '', known_limits: [], url: tag('2.0.0'),
    changes: [ch('changed', w('One agent per application', 'Z-one', 'Un agent par candidature')), ch('fixed', w('Résumé uploads are read', 'Z-resume', 'Les CV sont lus'))] },
  { version: '1.0.1', date: '2025-12-30', unreleased: false, title: w('The analysis page', 'Z-analysis', 'La page d’analyse'), intro: 'Three views over one time range.', known_limits: [], url: tag('1.0.1'),
    changes: [ch('added', w('Applications funnel', 'Z-funnel', 'Entonnoir'))] },
  { version: '0.9.0', date: '', unreleased: false, title: w('Old'), intro: '', known_limits: [], url: '', changes: [] },
]
const names = (list) => list.map((f) => f.v.version)
const ens = (list) => list.map((c) => c.summary.en)

describe('the accordion', () => {
  it('opens one version at a time: a press opens it (the other closes), a press on the open one closes it', () => {
    let open = null                                  // nothing is open when the tab is opened - not the newest, not the running one, not Unreleased
    open = toggled(open, '2.0.2')
    expect(open).toBe('2.0.2')
    open = toggled(open, '2.0.0')                    // another one: that one, and only that one
    expect(open).toBe('2.0.0')
    open = toggled(open, 'v2.0.0')                   // the open one again (however it is written): closed
    expect(open).toBe(null)
    expect(toggled(null, 'Unreleased')).toBe('Unreleased')      // the unreleased block is part of the same accordion
    expect(toggled('Unreleased', '2.0.2')).toBe('2.0.2')
  })
  it('a press is not written into the address: the accordion is only the open name, with nothing for the query', () => {
    // (the tab replaces the address only with what arrival() gives, and arrival() is null once `v` is gone)
    expect(typeof toggled(null, '2.0.2')).toBe('string')
    expect(arrival(V, {})).toBe(null)
    expect(arrival(V, { tab: 'x' })).toBe(null)
  })
  it('tells versions apart the way people write them', () => {
    expect(sameVersion('v2.0.2', '2.0.2')).toBe(true)
    expect(sameVersion('unreleased', 'Unreleased')).toBe(true)
    expect(sameVersion('2.0.2', '2.0.20')).toBe(false)
    expect(findVersion(V, 'V2.0.0').version).toBe('2.0.0')
    expect(findVersion(V, '3.0.0')).toBe(null)
    expect(anchor('2.0.2')).toBe('cl-v-2-0-2')
    expect(anchor('Unreleased')).toBe('cl-v-unreleased')
  })
})

describe('the deep link', () => {
  it('opens the version it names once, and is taken out of the address (the rest of the query kept)', () => {
    const a = arrival(V, { v: '2.0.2', from: 'overview' })
    expect(a).toEqual({ open: '2.0.2', missing: '', query: { from: 'overview' } })
    // the address it is replaced with names no version: arriving there again (a refresh, back) opens nothing
    expect(arrival(V, a.query)).toBe(null)
    expect(openFromQuery(V, a.query)).toBe(null)
  })
  it('a refresh after it starts from a first visit: everything closed', () => {
    const first = arrival(V, { v: '2.0.0' })
    let open = first.open
    expect(open).toBe('2.0.0')
    open = null                                      // (a refresh: the component starts again with nothing open)
    const again = arrival(V, first.query)
    if (again && again.open) open = again.open
    expect(open).toBe(null)
  })
  it('names a version as the data writes it, and says when the changelog does not have it', () => {
    expect(arrival(V, { v: 'v2.0.0' }).open).toBe('2.0.0')
    expect(arrival(V, { v: 'unreleased' }).open).toBe('Unreleased')
    expect(arrival(V, { v: '9.9.9' })).toEqual({ open: null, missing: '9.9.9', query: {} })      // nothing opens; a notice; still taken out
    expect(arrival(V, { v: '' })).toEqual({ open: null, missing: '', query: {} })
    expect(arrival([], { v: '2.0.2' })).toEqual({ open: null, missing: '2.0.2', query: {} })
    expect(withoutVersion({ v: '1', x: '2' })).toEqual({ x: '2' })
    expect(withoutVersion(undefined)).toEqual({})
  })
  it('reads the version from the address, whatever was typed there', () => {
    expect(versionFromQuery({ v: '2.0.2' })).toBe('2.0.2')
    expect(versionFromQuery({ v: ['1.0.3', '1.0.4'] })).toBe('1.0.3')
    expect(versionFromQuery({ v: '  ' })).toBe('')
    expect(versionFromQuery({ v: 'x'.repeat(41) })).toBe('')
    expect(versionFromQuery({})).toBe('')
    expect(versionFromQuery(undefined)).toBe('')
  })
})

describe('what an opened version shows', () => {
  it('at most six changes: the highlights first, then the rest, each in the release order', () => {
    expect(SHOWN).toBe(6)
    const got = pick(V[1].changes)
    expect(ens(got)).toEqual(['Calendar with reminders', 'Cards on your phone', 'Other origins refused', 'Postings and applications apart', 'Dates one way', 'The old importer'])
    expect(got.length).toBe(6)
    expect(pick(V[2].changes).length).toBe(2)
    expect(pick([])).toEqual([])
    const s = shownOf(filterVersions(V)[1])
    expect(s.changes.length).toBe(6)
    expect(s.more).toBe(2)                           // "2 more in the full notes"
    expect(shownOf(filterVersions(V)[2]).more).toBe(0)
  })
  it('grouped by type in the order of the release notes (added, changed, deprecated, removed, fixed, security)', () => {
    expect(TYPES).toEqual(['added', 'changed', 'deprecated', 'removed', 'fixed', 'security'])
    const g = byType(pick(V[1].changes))
    expect(g.map((x) => [x.type, ens(x.items)])).toEqual([
      ['added', ['Calendar with reminders', 'Cards on your phone']], ['changed', ['Postings and applications apart']],
      ['removed', ['The old importer']], ['fixed', ['Dates one way']], ['security', ['Other origins refused']],
    ])
    expect(byType([ch('later-type', w('Something new'))]).map((x) => x.type)).toEqual(['later-type'])      // (a type this interface does not know yet: kept, last)
    expect(byType([])).toEqual([])
  })
  it('says a text in the interface language, else in English, and says when it is English', () => {
    expect(inLang(V[1].title, 'zh')).toBe('Z-calendar')
    expect(inLang(V[1].changes[7].summary, 'zh')).toBe('A mail is sent once')        // no Chinese: English
    expect(isEnglish(V[1].changes[7].summary, 'zh')).toBe(true)                      // (marked as English)
    expect(isEnglish(V[1].changes[7].summary, 'fr')).toBe(false)
    expect(isEnglish(V[2].title, 'fr')).toBe(true)
    expect(isEnglish({ en: 'x' }, 'en')).toBe(false)
    expect(inLang({}, 'zh')).toBe('')
    expect(inLang(undefined, 'zh')).toBe('')
    expect(typeLabel('fixed', (k) => k)).toBe('about.changelog.kind.fixed')
    expect(typeLabel('later-type', (k) => k)).toBe('later-type')
  })
  it('links to the release page only with a web address', () => {
    expect(safeUrl('https://github.com/o/r/releases/tag/v1.0.0')).toBe('https://github.com/o/r/releases/tag/v1.0.0')
    expect(safeUrl('javascript:alert(1)')).toBe('')
    expect(safeUrl('https://x.org/"onmouseover=1')).toBe('')
    const t = (k, p) => k + (p ? JSON.stringify(p) : '')
    expect(linkOf(V[1], t)).toEqual({ url: V[1].url, label: 'about.changelog.release', tip: 'about.changelog.releaseTip{"v":"2.0.2"}' })
    expect(linkOf(V[0], t)).toBe(null)
  })
})

describe('the timeline', () => {
  it('the releases by year, the unreleased entry apart, the newest release', () => {
    expect(releases(V).map((v) => v.version)).toEqual(['2.0.2', '2.0.0', '1.0.1', '0.9.0'])
    expect(unreleasedOf(V).version).toBe('Unreleased')
    expect(unreleasedOf(releases(V))).toBe(null)
    expect(latestOf(V).version).toBe('2.0.2')
    expect(latestOf([V[0]])).toBe(null)
    expect(groupByYear(releases(V)).map((x) => [x.key, x.year, x.versions.map((v) => v.version)])).toEqual([
      ['2026', '2026', ['2.0.2', '2.0.0']], ['2025', '2025', ['1.0.1']], ['undated', '', ['0.9.0']],
    ])
    expect(groupByYear([])).toEqual([])
  })
})

describe('search and the type filter', () => {
  it('never open anything: they say what is shown, and give no open version', () => {
    for (const f of [{ q: 'calendar' }, { type: 'fixed' }, { q: 'nothing like this' }, { q: '2.0.2', type: 'added' }]) {
      const out = filterVersions(V, { ...f, lang: 'en' })
      expect(out.every((x) => Object.keys(x).sort().join() === 'changes,notes,v')).toBe(true)
    }
    expect(typeCounts(V).every((c) => Object.keys(c).sort().join() === 'n,type')).toBe(true)
  })
  it('shows every version with all its changes when nothing is filtered', () => {
    const all = filterVersions(V)
    expect(names(all)).toEqual(V.map((v) => v.version))
    expect(all[1].changes).toBe(V[1].changes)
    expect(all.every((f) => f.notes === 0)).toBe(true)
  })
  it('a type keeps the versions with changes of that type, and only those changes', () => {
    const f = filterVersions(V, { type: 'fixed' })
    expect(names(f)).toEqual(['Unreleased', '2.0.2', '2.0.0'])
    expect(ens(f[1].changes)).toEqual(['Dates one way', 'A mail is sent once'])
    expect(filterVersions(V, { type: 'deprecated' }).map((x) => [x.v.version, x.changes.length])).toEqual([['2.0.2', 1]])
    expect(filterVersions(V, { type: 'security', q: 'menus' })).toEqual([])
  })
  it('a search reads the summaries in the interface language and in English, and the details', () => {
    expect(words('  Calendar   TIME ')).toEqual(['calendar', 'time'])
    expect(fold('Résumé')).toBe('resume')
    expect(plain('**Calendar** (see [the docs](https://x.org)) `code`')).toBe('Calendar (see the docs) code')
    expect(hasAll('**Calendar** (sidebar): everything with a time.', ['calendar', 'time'])).toBe(true)
    const f = filterVersions(V, { q: 'reminders', lang: 'en' })
    expect(names(f)).toEqual(['2.0.2'])
    expect(f[0]).toMatchObject({ notes: 1 })                                          // the intro, too
    expect(ens(f[0].changes)).toEqual(['Calendar with reminders'])
    expect(names(filterVersions(V, { q: 'z-phone', lang: 'zh' }))).toEqual(['2.0.2'])     // the interface's language
    expect(names(filterVersions(V, { q: 'phone', lang: 'zh' }))).toEqual(['2.0.2'])       // and English
    expect(names(filterVersions(V, { q: 'feed calendar app' }))).toEqual(['2.0.2'])        // the details
    expect(names(filterVersions(V, { q: 'resume' }))).toEqual(['2.0.0'])                   // without accents
    expect(filterVersions(V, { q: 'nothing like this' })).toEqual([])
  })
  it('found only in the intro or a known limit: the version stays, "n matches in the full notes"', () => {
    const f = filterVersions(V, { q: 'code-signed' })
    expect(f.map((x) => [x.v.version, x.changes.length, x.notes])).toEqual([['2.0.2', 0, 1]])
    expect(shownOf(f[0])).toEqual({ changes: [], more: 1 })
    expect(filterVersions(V, { q: 'code-signed', type: 'fixed' })).toEqual([])        // (they have no type)
  })
  it('a release found by its number shows its changes; by its title, those that match, else all', () => {
    expect(filterVersions(V, { q: 'v2.0.0' }).map((f) => [f.v.version, f.changes.length])).toEqual([['2.0.0', 2]])
    expect(names(filterVersions(V, { q: 'unreleased' }))).toEqual(['Unreleased'])
    expect(filterVersions(V, { q: 'phone cards', lang: 'en' }).map((f) => [f.v.version, f.changes.length])).toEqual([['2.0.2', 1]])
    expect(filterVersions(V, { q: 'calendar and', lang: 'en' }).map((f) => [f.v.version, f.changes.length])).toEqual([['2.0.2', 8]])
    // with matches the at most six are still the highlights first
    const s = shownOf(filterVersions(V, { q: 'calendar and', lang: 'en' })[0])
    expect(ens(s.changes).slice(0, 3)).toEqual(['Calendar with reminders', 'Cards on your phone', 'Other origins refused'])
    expect(s.more).toBe(2)
  })
  it('the type menu counts the changes of each type there is, under the search', () => {
    expect(typeCounts(V)).toEqual([
      { type: 'added', n: 3 }, { type: 'changed', n: 2 }, { type: 'deprecated', n: 1 }, { type: 'removed', n: 1 }, { type: 'fixed', n: 4 }, { type: 'security', n: 1 },
    ])
    expect(typeCounts(V, { q: 'menu' }).filter((c) => c.n)).toEqual([{ type: 'fixed', n: 1 }])
    expect(typeCounts([])).toEqual([])
  })
  it('marks what was found in the text of the HTML only', () => {
    expect(mark('<p><strong>Calendar</strong> of a calendar</p>', ['calendar'])).toBe('<p><strong><mark>Calendar</mark></strong> of a <mark>calendar</mark></p>')
    expect(mark('<a href="https://calendar.org">x</a>', ['calendar'])).toBe('<a href="https://calendar.org">x</a>')
    expect(mark('<p>Tom &amp; Jerry</p>', ['amp'])).toBe('<p>Tom &amp; Jerry</p>')
    expect(mark('<p>a &lt;b&gt; c</p>', ['<b>'])).toBe('<p>a <mark>&lt;b&gt;</mark> c</p>')
    expect(mark('<p>a</p>', ['a'])).toBe('<p>a</p>')
    expect(mark('<p>x</p>', [])).toBe('<p>x</p>')
  })
})

describe('licences', () => {
  const C = [
    { name: 'fastapi', version: '0.162.5', license: 'MIT', direct: true, summary: 'FastAPI framework' },
    { name: 'starlette', version: '1.10.0', license: 'BSD-3-Clause', direct: false, summary: 'The little ASGI library' },
    { name: 'anyio', version: '4.9.0', license: 'MIT', direct: false, summary: 'Concurrency' },
    { name: 'Pillow', version: '13.0.0', license: '', direct: true, summary: 'Imaging' },
  ]
  it('filters by words, direct or all, and one licence', () => {
    expect(filterComponents(C).length).toBe(4)
    expect(filterComponents(C, { q: 'mit' }).map((r) => r.name)).toEqual(['fastapi', 'anyio'])
    expect(filterComponents(C, { q: 'asgi little' }).map((r) => r.name)).toEqual(['starlette'])
    expect(filterComponents(C, { scope: 'direct' }).map((r) => r.name)).toEqual(['fastapi', 'Pillow'])
    expect(filterComponents(C, { license: 'MIT', scope: 'direct' }).map((r) => r.name)).toEqual(['fastapi'])
  })
  it('lists the licences, the most common first', () => {
    expect(licenseOptions(C)).toEqual([{ license: 'MIT', count: 2 }, { license: 'BSD-3-Clause', count: 1 }])
  })
  it('sorts names without case, versions as versions, direct first', () => {
    expect(sortComponents(C, { by: 'name', dir: 'asc' }).map((r) => r.name)).toEqual(['anyio', 'fastapi', 'Pillow', 'starlette'])
    expect(sortComponents(C, { by: 'version', dir: 'asc' }).map((r) => r.version)).toEqual(['0.162.5', '1.10.0', '4.9.0', '13.0.0'])
    expect(sortComponents(C, { by: 'dependency', dir: 'asc' }).map((r) => r.name)).toEqual(['fastapi', 'Pillow', 'anyio', 'starlette'])
  })
})
