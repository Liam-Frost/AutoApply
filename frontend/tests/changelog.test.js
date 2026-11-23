// The about page's timeline and licences, as pure functions (src/changelog.js): grouping, filters, search, which
// versions start open, the version kept in the address, and the licence table's filter and sort.
import { describe, expect, it } from 'vitest'
import {
  anchor, counts, filterComponents, filterVersions, findVersion, fold, groupByYear, hasAll, initialOpen, kindTotals, licenseOptions, linkKind,
  mark, plain, queryWith, safeUrl, sameVersion, sortComponents, versionFromQuery, words,
} from '../src/changelog.js'

const sec = (kind, items, title = kind[0].toUpperCase() + kind.slice(1), text = '') => ({ kind, title, items, text })
const V = [
  { version: 'Unreleased', date: '', unreleased: true, summary: '', url: '', sections: [sec('fixed', ['A menu no longer closes at once.'])] },
  { version: '2.0.2', date: '2026-11-22', unreleased: false, summary: '2.0.2 brings a **calendar** with reminders.', url: 'https://github.com/o/r/compare/v2.0.0...v2.0.2',
    sections: [sec('added', ['**Calendar** (sidebar): everything with a time.', 'Reminders of your own.']), sec('changed', ['Postings and applications, each one thing.']), sec('known', ['The packages are not code-signed.'], 'Known limits')] },
  { version: '2.0.0', date: '2026-11-21', unreleased: false, summary: '', url: '', sections: [sec('changed', ['One agent works an application.']), sec('removed', ['The drivers.']), sec('fixed', ['A mail is sent once.', 'Résumé uploads are read.'])] },
  { version: '1.0.1', date: '2025-12-30', unreleased: false, summary: '', url: '', sections: [sec('other', ['**Applications.** The funnel.'], 'The analysis page', 'Three views over one time range.'), sec('other', ['Every request is recorded.'], 'Recording what the AI costs')] },
  { version: '0.9.0', date: '', unreleased: false, summary: 'No date written.', url: '', sections: [] },
]

describe('versions and their address', () => {
  it('tells versions apart the way people write them', () => {
    expect(sameVersion('v2.0.2', '2.0.2')).toBe(true)
    expect(sameVersion('unreleased', 'Unreleased')).toBe(true)
    expect(sameVersion('2.0.2', '2.0.20')).toBe(false)
    expect(findVersion(V, 'V2.0.0').version).toBe('2.0.0')
    expect(findVersion(V, '3.0.0')).toBe(null)
    expect(findVersion(V, '')).toBe(null)
    expect(anchor('2.0.2')).toBe('cl-v-2-0-2')
    expect(anchor('Unreleased')).toBe('cl-v-unreleased')
  })
  it('reads the version from the address and writes it with the rest of the query kept', () => {
    expect(versionFromQuery({ v: '2.0.2' })).toBe('2.0.2')
    expect(versionFromQuery({ v: ['1.0.3', '1.0.4'] })).toBe('1.0.3')
    expect(versionFromQuery({ v: '  ' })).toBe('')
    expect(versionFromQuery({ v: 'x'.repeat(41) })).toBe('')          // (an address can say anything: not this)
    expect(versionFromQuery({})).toBe('')
    expect(versionFromQuery(undefined)).toBe('')
    expect(queryWith({ only: 'Changelog' }, '2.0.2')).toEqual({ only: 'Changelog', v: '2.0.2' })
    expect(queryWith({ v: '2.0.2', x: '1' }, '')).toEqual({ x: '1' })
  })
  it('opens the latest release, the running version and the one the address names', () => {
    expect([...initialOpen(V, '2.0.2', '')]).toEqual(['2.0.2'])                 // (the unreleased entry starts closed)
    expect([...initialOpen(V, '2.0.0', '')].sort()).toEqual(['2.0.0', '2.0.2'])
    expect([...initialOpen(V, '2.0.2', 'v1.0.1')].sort()).toEqual(['1.0.1', '2.0.2'])
    expect([...initialOpen(V, '9.9.9', 'nope')]).toEqual(['2.0.2'])           // what is not in the file opens nothing
    expect([...initialOpen([V[0]], '', '')]).toEqual(['Unreleased'])           // nothing released yet: the first entry
    expect(initialOpen([], '2.0.2', '').size).toBe(0)
  })
  it('only links to a web address', () => {
    expect(safeUrl('https://github.com/o/r/compare/v1...v2')).toBe('https://github.com/o/r/compare/v1...v2')
    expect(safeUrl('javascript:alert(1)')).toBe('')
    expect(safeUrl('https://x.org/"onmouseover=1')).toBe('')
    expect(safeUrl('')).toBe('')
    expect(linkKind('https://github.com/o/r/compare/v1...v2')).toBe('compare')
    expect(linkKind('https://github.com/o/r/releases/tag/v1.0.0')).toBe('release')
    expect(linkKind('https://example.com/notes')).toBe('other')
  })
})

describe('the timeline', () => {
  it('groups by year in the order given, the unreleased and the undated apart', () => {
    const g = groupByYear(V)
    expect(g.map((x) => [x.key, x.year, x.versions.map((v) => v.version)])).toEqual([
      ['unreleased', '', ['Unreleased']], ['2026', '2026', ['2.0.2', '2.0.0']], ['2025', '2025', ['1.0.1']], ['undated', '', ['0.9.0']],
    ])
    expect(groupByYear([])).toEqual([])
  })
  it('counts the changes of each kind, the same kind added up, in a fixed order', () => {
    expect(counts(V[1])).toEqual([{ kind: 'added', n: 2 }, { kind: 'changed', n: 1 }, { kind: 'known', n: 1 }])
    expect(counts(V[3])).toEqual([{ kind: 'other', n: 2 }])
    expect(counts(V[4])).toEqual([])
    expect(kindTotals(V)).toEqual([{ kind: 'added', n: 2 }, { kind: 'changed', n: 2 }, { kind: 'fixed', n: 3 }, { kind: 'removed', n: 1 }, { kind: 'known', n: 1 }, { kind: 'other', n: 2 }])
  })
})

describe('filters and search', () => {
  it('shows everything, as it is, without a filter', () => {
    const all = filterVersions(V)
    expect(all.map((v) => v.version)).toEqual(V.map((v) => v.version))
    expect(all[1].sections).toBe(V[1].sections)
    expect(all.map((v) => v.hits)).toEqual([1, 4, 4, 2, 0])
  })
  it('narrows to the kinds chosen, and leaves out the versions without them', () => {
    const f = filterVersions(V, { kinds: ['fixed'] })
    expect(f.map((v) => [v.version, v.hits])).toEqual([['Unreleased', 1], ['2.0.0', 2]])
    expect(f[1].sections.map((s) => s.kind)).toEqual(['fixed'])
    expect(filterVersions(V, { kinds: ['added', 'removed'] }).map((v) => v.version)).toEqual(['2.0.2', '2.0.0'])
    expect(filterVersions(V, { kinds: ['security'] })).toEqual([])
  })
  it('searches every word, without case, accents or markdown marks', () => {
    expect(words('  Calendar   TIME ')).toEqual(['calendar', 'time'])
    expect(fold('Résumé')).toBe('resume')
    expect(plain('**Calendar** (see [the docs](https://x.org)) `code`')).toBe('Calendar (see the docs) code')
    expect(hasAll('**Calendar** (sidebar): everything with a time.', ['calendar', 'time'])).toBe(true)
    const f = filterVersions(V, { q: 'calendar time' })
    expect(f.map((v) => [v.version, v.hits])).toEqual([['2.0.2', 1]])
    expect(f[0].sections.map((s) => s.items)).toEqual([['**Calendar** (sidebar): everything with a time.']])
    expect(filterVersions(V, { q: 'resume' })[0].sections[0].items).toEqual(['Résumé uploads are read.'])
    expect(filterVersions(V, { q: 'nothing like this' })).toEqual([])
  })
  it('a version found by its summary is shown with it; its items only where they match too', () => {
    const f = filterVersions(V, { q: 'reminders' })
    expect(f.map((v) => [v.version, v.hits])).toEqual([['2.0.2', 1]])
    const g = filterVersions(V, { q: 'brings' })
    expect(g.map((v) => [v.version, v.hits, v.sections.length])).toEqual([['2.0.2', 0, 0]])
  })
  it('a version number shows that version whole; a section title shows its items', () => {
    expect(filterVersions(V, { q: 'v2.0.0' }).map((v) => [v.version, v.hits])).toEqual([['2.0.0', 4]])
    expect(filterVersions(V, { q: 'unreleased' }).map((v) => v.version)).toEqual(['Unreleased'])
    const f = filterVersions(V, { q: 'analysis page' })
    expect(f.map((v) => [v.version, v.hits])).toEqual([['1.0.1', 1]])
    expect(f[0].sections[0].text).toBe('Three views over one time range.')
    expect(filterVersions(V, { q: 'time range' })[0].sections[0]).toMatchObject({ items: [], text: 'Three views over one time range.' })
  })
  it('a kind and a search at once', () => {
    expect(filterVersions(V, { kinds: ['fixed'], q: 'menu' }).map((v) => [v.version, v.hits])).toEqual([['Unreleased', 1]])
    expect(filterVersions(V, { kinds: ['changed'], q: 'menu' })).toEqual([])
  })
  it('marks what was found in the text of the HTML only', () => {
    expect(mark('<p><strong>Calendar</strong> of a calendar</p>', ['calendar'])).toBe('<p><strong><mark>Calendar</mark></strong> of a <mark>calendar</mark></p>')
    expect(mark('<a href="https://calendar.org">x</a>', ['calendar'])).toBe('<a href="https://calendar.org">x</a>')
    expect(mark('<p>Tom &amp; Jerry</p>', ['amp'])).toBe('<p>Tom &amp; Jerry</p>')
    expect(mark('<p>a &lt;b&gt; c</p>', ['<b>'])).toBe('<p>a <mark>&lt;b&gt;</mark> c</p>')
    expect(mark('<p>1.0 (x)</p>', ['(x)'])).toBe('<p>1.0 <mark>(x)</mark></p>')
    expect(mark('<p>a</p>', ['a'])).toBe('<p>a</p>')        // (one letter marks everything: not marked)
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
    expect(sortComponents(C, { by: 'version', dir: 'desc' }).map((r) => r.version)[0]).toBe('13.0.0')
    expect(sortComponents(C, { by: 'dependency', dir: 'asc' }).map((r) => r.name)).toEqual(['fastapi', 'Pillow', 'anyio', 'starlette'])
    expect(sortComponents(C, null).map((r) => r.name)[0]).toBe('anyio')
  })
})
