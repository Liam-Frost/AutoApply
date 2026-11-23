// The about page's changelog and licences, as pure functions (src/changelog.js): the accordion (one version open, by
// a press or by the address - never by itself or by a filter), grouping, the search and the type filter over the
// highlights and the full notes, the words in the interface's language, and the licence table's filter and sort.
import { describe, expect, it } from 'vitest'
import {
  anchor, byKind, filterComponents, filterVersions, findVersion, fold, groupByYear, hasAll, inLang, isEnglish, kindLabel, latestOf, licenseOptions, linkKind,
  linkOf, mark, openFromQuery, plain, queryWith, releases, safeUrl, sameVersion, sortComponents, toggled, typeCounts, unreleasedOf, versionFromQuery, words,
} from '../src/changelog.js'

const sec = (kind, items, title = kind[0].toUpperCase() + kind.slice(1), text = '') => ({ kind, title, items, text })
const w = (en, zh, fr) => ({ en, zh, fr })
const V = [
  { version: 'Unreleased', date: '', unreleased: true, summary: '', url: 'https://github.com/o/r/compare/v2.0.2...HEAD', title: w('Work in progress', 'Z-progress', 'En cours'),
    highlights: [{ kind: 'fixed', title: w('Menus stay open', 'Z-menus', 'Les menus restent ouverts') }],
    sections: [sec('fixed', ['A menu no longer closes at once.'])] },
  { version: '2.0.2', date: '2026-11-22', unreleased: false, summary: '2.0.2 brings a **calendar** with reminders.', url: 'https://github.com/o/r/compare/v2.0.0...v2.0.2',
    title: w('Calendar and phone cards', 'Z-calendar', 'Agenda'),
    highlights: [
      { kind: 'added', title: w('Calendar with reminders', 'Z-cal', 'Agenda avec rappels'), text: w('Every time on one page.', 'Z-every', 'Chaque heure sur une page.') },
      { kind: 'changed', title: w('Postings and applications apart', 'Z-postings', 'Offres et candidatures') },
      { kind: 'added', title: w('Cards on your phone', 'Z-phone', 'Cartes sur le téléphone') },
    ],
    sections: [sec('added', ['**Calendar** (sidebar): everything with a time.', 'Reminders of your own.', 'A feed for your calendar app.']), sec('changed', ['Postings and applications, each one thing.']), sec('known', ['The packages are not code-signed.'], 'Known limits')] },
  { version: '2.0.0', date: '2026-11-21', unreleased: false, summary: '', url: '', title: w('One agent', 'Z-agent', 'Un agent'),
    highlights: [{ kind: 'changed', title: w('One agent per application', 'Z-one', 'Un agent par candidature') }, { kind: 'removed', title: w('The drivers are gone', 'Z-drivers', 'Les pilotes') }],
    sections: [sec('changed', ['One agent works an application.']), sec('removed', ['The drivers.']), sec('fixed', ['A mail is sent once.', 'Résumé uploads are read.'])] },
  { version: '1.0.1', date: '2025-12-30', unreleased: false, summary: '', url: '', title: {},
    highlights: [{ kind: 'other', title: { en: 'Applications' }, derived: true }],
    sections: [sec('other', ['**Applications.** The funnel.'], 'The analysis page', 'Three views over one time range.'), sec('other', ['Every request is recorded.'], 'Recording what the AI costs')] },
  { version: '0.9.0', date: '', unreleased: false, summary: 'No date written.', url: '', title: {}, highlights: [], sections: [] },
]
const names = (list) => list.map((f) => f.v.version)

describe('the accordion and the address', () => {
  it('opens one version at a time: a press opens it (the other closes), a press on the open one closes it', () => {
    let open = null                                  // nothing is open when the tab is opened - not the newest, not the running one
    open = toggled(open, '2.0.2')
    expect(open).toBe('2.0.2')
    open = toggled(open, '2.0.0')                    // another one: that one, and only that one
    expect(open).toBe('2.0.0')
    open = toggled(open, 'v2.0.0')                   // the open one again (however it is written): closed
    expect(open).toBe(null)
    expect(toggled(null, 'Unreleased')).toBe('Unreleased')      // the unreleased block is part of the same accordion
    expect(toggled('Unreleased', '2.0.2')).toBe('2.0.2')
  })
  it('the address opens a version (a link, a refresh), and closing removes it', () => {
    expect(openFromQuery(V, { v: '2.0.2' })).toBe('2.0.2')
    expect(openFromQuery(V, { v: 'v2.0.0' })).toBe('2.0.0')             // written as the data writes it
    expect(openFromQuery(V, { v: 'unreleased' })).toBe('Unreleased')
    expect(openFromQuery(V, {})).toBe(null)                              // no ?v: all closed (another tab and back)
    expect(openFromQuery(V, { v: '9.9.9' })).toBe(null)                  // not in the changelog: nothing opens
    expect(openFromQuery([], { v: '2.0.2' })).toBe(null)
    // what a press writes: the version, or no `v` at all - the rest of the query kept
    expect(queryWith({ only: 'Changelog' }, toggled(null, '2.0.2'))).toEqual({ only: 'Changelog', v: '2.0.2' })
    expect(queryWith({ v: '2.0.2', x: '1' }, toggled('2.0.2', '2.0.2'))).toEqual({ x: '1' })
    // and a refresh reads back what was written
    expect(openFromQuery(V, queryWith({}, toggled(null, '2.0.0')))).toBe('2.0.0')
  })
  it('reads the version from the address, whatever was typed there', () => {
    expect(versionFromQuery({ v: '2.0.2' })).toBe('2.0.2')
    expect(versionFromQuery({ v: ['1.0.3', '1.0.4'] })).toBe('1.0.3')
    expect(versionFromQuery({ v: '  ' })).toBe('')
    expect(versionFromQuery({ v: 'x'.repeat(41) })).toBe('')
    expect(versionFromQuery({})).toBe('')
    expect(versionFromQuery(undefined)).toBe('')
  })
  it('a search or a type never opens anything: the filter only says what is shown', () => {
    // (filterVersions is the whole of what a filter does: it takes no open version and gives none)
    const before = toggled(null, '2.0.0')
    for (const f of [{ q: 'calendar' }, { kind: 'fixed' }, { q: 'nothing like this' }]) {
      const out = filterVersions(V, { ...f, lang: 'en' })
      expect(out.every((x) => Object.keys(x).sort().join() === 'highlights,more,notes,v')).toBe(true)
    }
    expect(before).toBe('2.0.0')
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
  it('only links to a web address', () => {
    expect(safeUrl('https://github.com/o/r/compare/v1...v2')).toBe('https://github.com/o/r/compare/v1...v2')
    expect(safeUrl('javascript:alert(1)')).toBe('')
    expect(safeUrl('https://x.org/"onmouseover=1')).toBe('')
    expect(linkKind('https://github.com/o/r/compare/v1...v2')).toBe('compare')
    expect(linkKind('https://github.com/o/r/releases/tag/v1.0.0')).toBe('release')
    expect(linkKind('https://example.com/notes')).toBe('other')
    const t = (k, p) => k + (p ? JSON.stringify(p) : '')
    expect(linkOf(V[1], t)).toEqual({ url: V[1].url, label: 'about.changelog.compare', tip: 'about.changelog.compareTip{"v":"2.0.2"}' })
    expect(linkOf(V[0], t).tip).toBe('about.changelog.compareUnreleased')
    expect(linkOf(V[2], t)).toBe(null)
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
  it('groups the highlights by kind, in the order the release names them first', () => {
    expect(byKind(V[1].highlights).map((g) => [g.kind, g.items.map((h) => h.title.en)])).toEqual([
      ['added', ['Calendar with reminders', 'Cards on your phone']], ['changed', ['Postings and applications apart']],
    ])
    expect(byKind([])).toEqual([])
  })
  it('says a title in the interface language, else in English, and says when it is English', () => {
    expect(inLang(V[1].title, 'zh')).toBe('Z-calendar')
    expect(inLang({ en: 'Only English' }, 'fr')).toBe('Only English')
    expect(inLang({}, 'zh')).toBe('')
    expect(inLang(undefined, 'zh')).toBe('')
    expect(isEnglish({ en: 'Only English' }, 'zh')).toBe(true)              // (a derived highlight: lang="en")
    expect(isEnglish(V[1].title, 'zh')).toBe(false)
    expect(isEnglish({ en: 'x' }, 'en')).toBe(false)
    expect(kindLabel('fixed', (k) => k)).toBe('about.changelog.kind.fixed')
    expect(kindLabel('something new', (k) => k)).toBe('about.changelog.kind.other')
  })
})

describe('search and the type filter', () => {
  it('shows every version with all its highlights when nothing is filtered', () => {
    const all = filterVersions(V)
    expect(names(all)).toEqual(V.map((v) => v.version))
    expect(all[1].highlights).toBe(V[1].highlights)
    expect(all.every((f) => f.notes === 0 && f.more === 0)).toBe(true)
  })
  it('a type keeps the versions with that kind - in their highlights or their notes - and only those highlights', () => {
    const f = filterVersions(V, { kind: 'fixed' })
    expect(names(f)).toEqual(['Unreleased', '2.0.0'])
    expect(f[0]).toMatchObject({ notes: 1, more: 0 })
    expect(f[0].highlights.map((h) => h.title.en)).toEqual(['Menus stay open'])
    // 2.0.0 has no fixed highlight, but two fixes in its notes: shown, with "2 matches in the full notes"
    expect(f[1]).toMatchObject({ highlights: [], notes: 2, more: 2 })
    const a = filterVersions(V, { kind: 'added' })
    expect(names(a)).toEqual(['2.0.2'])
    expect(a[0].highlights.map((h) => h.title.en)).toEqual(['Calendar with reminders', 'Cards on your phone'])
    expect(a[0]).toMatchObject({ notes: 3, more: 1 })                   // "1 more in the full notes"
    expect(filterVersions(V, { kind: 'security' })).toEqual([])
  })
  it('a search reads the highlights in the interface language and in English, and the full notes', () => {
    expect(words('  Calendar   TIME ')).toEqual(['calendar', 'time'])
    expect(fold('Résumé')).toBe('resume')
    expect(plain('**Calendar** (see [the docs](https://x.org)) `code`')).toBe('Calendar (see the docs) code')
    expect(hasAll('**Calendar** (sidebar): everything with a time.', ['calendar', 'time'])).toBe(true)
    const f = filterVersions(V, { q: 'reminders', lang: 'en' })
    expect(names(f)).toEqual(['2.0.2'])
    expect(f[0].highlights.map((h) => h.title.en)).toEqual(['Calendar with reminders'])
    expect(f[0]).toMatchObject({ notes: 2, more: 1 })                    // the summary and one bullet
    expect(names(filterVersions(V, { q: 'z-phone', lang: 'zh' }))).toEqual(['2.0.2'])     // the interface's language
    expect(names(filterVersions(V, { q: 'phone', lang: 'zh' }))).toEqual(['2.0.2'])       // and English, which the notes are in
    expect(names(filterVersions(V, { q: 'resume' }))).toEqual(['2.0.0'])                  // without accents
    const n = filterVersions(V, { q: 'resume' })[0]
    expect(n).toMatchObject({ highlights: [], notes: 1 })                // found only in the full notes
    expect(filterVersions(V, { q: 'nothing like this' })).toEqual([])
  })
  it('a release found by its number shows all its highlights; by its title, those that match, else all', () => {
    expect(filterVersions(V, { q: 'v2.0.0' }).map((f) => [f.v.version, f.highlights.length])).toEqual([['2.0.0', 2]])
    expect(names(filterVersions(V, { q: 'unreleased' }))).toEqual(['Unreleased'])
    expect(filterVersions(V, { q: 'phone cards', lang: 'en' }).map((f) => [f.v.version, f.highlights.length])).toEqual([['2.0.2', 1]])
    expect(filterVersions(V, { q: 'calendar and', lang: 'en' }).map((f) => [f.v.version, f.highlights.length])).toEqual([['2.0.2', 3]])
    // a section's own heading finds its bullets and paragraphs
    expect(filterVersions(V, { q: 'analysis page' }).map((f) => [f.v.version, f.notes])).toEqual([['1.0.1', 2]])
  })
  it('a type and a search at once', () => {
    expect(names(filterVersions(V, { kind: 'fixed', q: 'menu' }))).toEqual(['Unreleased'])
    expect(filterVersions(V, { kind: 'changed', q: 'menu' })).toEqual([])
    expect(filterVersions(V, { kind: 'added', q: 'phone', lang: 'en' }).map((f) => f.highlights.map((h) => h.title.en))).toEqual([['Cards on your phone']])
  })
  it('the type menu lists the kinds there are, each with how many versions it leaves under the search', () => {
    expect(typeCounts(V)).toEqual([
      { kind: 'added', n: 1 }, { kind: 'changed', n: 2 }, { kind: 'fixed', n: 2 }, { kind: 'removed', n: 1 }, { kind: 'known', n: 1 }, { kind: 'other', n: 1 },
    ])
    expect(typeCounts(V, { q: 'menu' }).filter((c) => c.n)).toEqual([{ kind: 'fixed', n: 1 }])
    expect(typeCounts([])).toEqual([])
  })
  it('derived highlights are English and are searched as such', () => {
    const f = filterVersions(V, { q: 'applications', lang: 'zh' })
    expect(f.find((x) => x.v.version === '1.0.1').highlights).toEqual([{ kind: 'other', title: { en: 'Applications' }, derived: true }])
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
