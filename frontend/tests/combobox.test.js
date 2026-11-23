// The search of a Combobox and how its keyboard moves the mark (src/combobox.js): what a search finds and in which order,
// which headings stay, an option in two groups found once, and the keys. (The component around it - focus, placing,
// Escape and Tab - is walked through in a browser: the lab section 50-Combobox.)
import { describe, expect, it } from 'vitest'
import { fold, indexOf, prepare, rank, same, search, step } from '../src/combobox.js'

const values = (r) => r.items.map((o) => o.value)
const find = (options, q, groups = []) => search(prepare(options), groups, q)

describe('what is compared', () => {
  it('is folded: no case, no accents, one minus, words apart; signs and colons stay in a word', () => {
    expect(fold('São Paulo')).toBe('sao paulo')
    expect(fold('  Zürich  ')).toBe('zurich')
    expect(fold('UTC−07:00 · America/Vancouver')).toBe('utc-07:00 america vancouver')
    expect(fold('UTC+05:30')).toBe('utc+05:30')
    expect(fold('温哥华（加拿大）')).toBe('温哥华 加拿大')
    expect(fold('Los_Angeles')).toBe('los angeles')
    expect(fold(null)).toBe('')
  })
})

describe('a search', () => {
  const OPTS = [
    { value: 'ny', label: 'New York' },
    { value: 'oy', label: 'Old Yorker' },
    { value: 'ys', label: 'Yorkshire Dales' },
    { value: 'y', label: 'York' },
    { value: 'sp', label: 'São Paulo', hint: 'UTC−03:00', keywords: ['Brazil', 'Brasil'] },
    { value: 'x', label: 'Elsewhere', hint: 'nothing here', disabled: true },
  ]
  it('finds labels that start with it first, then a whole word, then the start of a word, then anywhere', () => {
    expect(values(find(OPTS, 'york'))).toEqual(['ys', 'y', 'ny', 'oy'])
    expect(values(find(OPTS, 'ork'))).toEqual(['ny', 'oy', 'ys', 'y'])         // (inside words only: as they were given)
    const p = prepare(OPTS)
    expect([rank(p[3], 'york'), rank(p[0], 'york'), rank(p[1], 'york'), rank(p[0], 'ork'), rank(p[4], 'york')]).toEqual([0, 1, 2, 3, -1])
  })
  it('is blind to case and accents and looks at the hint, the value and the keywords too', () => {
    expect(values(find(OPTS, 'SAO'))).toEqual(['sp'])
    expect(values(find(OPTS, 'brasil'))).toEqual(['sp'])
    expect(values(find(OPTS, 'utc-03'))).toEqual(['sp'])          // a hyphen finds the minus sign of the hint
    expect(values(find(OPTS, 'ny'))).toEqual(['ny'])              // the value
    expect(values(find(OPTS, 'paulo sao'))).toEqual(['sp'])       // every word, in any order
    expect(values(find(OPTS, 'nothing'))).toEqual(['x'])          // (a disabled option is found; it cannot be picked)
    expect(find(OPTS, 'zzz').items).toEqual([])
  })
  it('with nothing typed, shows everything in its own order', () => {
    expect(values(find(OPTS, ''))).toEqual(OPTS.map((o) => o.value))
    expect(values(find(OPTS, '   '))).toEqual(OPTS.map((o) => o.value))
  })
})

describe('groups', () => {
  const GROUPS = [{ id: 'common', label: 'Common' }, { id: 'americas', label: 'Americas' }, { id: 'europe', label: 'Europe' }]
  const OPTS = [
    { value: 'paris', label: 'Paris', group: 'europe' },
    { value: 'van', label: 'Vancouver', group: 'americas' },
    { value: 'van', label: 'Vancouver', group: 'common' },
    { value: 'lon', label: 'London', group: 'europe' },
    { value: '', label: 'Follow this computer' },
    { value: 'odd', label: 'Odd one', group: 'nowhere' },
  ]
  it('come in the order given, after the options without one; a heading is kept only where something matches', () => {
    const all = find(OPTS, '', GROUPS)
    expect(all.sections.map((s) => (s.group ? s.group.id : null))).toEqual([null, 'common', 'americas', 'europe'])
    expect(all.sections[0].rows.map((r) => r.option.value)).toEqual(['', 'odd'])
    expect(values(all)).toEqual(['', 'odd', 'van', 'van', 'paris', 'lon'])     // (with nothing typed, a zone is under Common and its region)
    expect(all.sections.flatMap((s) => s.rows.map((r) => r.at))).toEqual([0, 1, 2, 3, 4, 5])
    const lo = find(OPTS, 'lond', GROUPS)
    expect(lo.sections.map((s) => (s.group ? s.group.id : null))).toEqual(['europe'])
    expect(values(lo)).toEqual(['lon'])
  })
  it('show an option that is in two of them once while searching, under the first', () => {
    const v = find(OPTS, 'vanc', GROUPS)
    expect(values(v)).toEqual(['van'])
    expect(v.sections.map((s) => s.group.id)).toEqual(['common'])
  })
})

describe('the keyboard', () => {
  const items = [{ value: 1 }, { value: 2, disabled: true }, { value: 3 }, { value: 4 }, { value: 5, disabled: true }]
  it('arrows go round the ends and pass over what is disabled', () => {
    expect(step(items, 0, 'ArrowDown')).toBe(2)
    expect(step(items, 3, 'ArrowDown')).toBe(0)
    expect(step(items, 0, 'ArrowUp')).toBe(3)
    expect(step(items, -1, 'ArrowDown')).toBe(0)
    expect(step(items, -1, 'ArrowUp')).toBe(3)
  })
  it('Home and End go to the first and last that can be chosen; the page keys stop at the ends', () => {
    expect(step(items, 2, 'Home')).toBe(0)
    expect(step(items, 0, 'End')).toBe(3)
    expect(step(items, 0, 'PageDown', 2)).toBe(2)
    expect(step(items, 0, 'PageDown', 10)).toBe(3)
    expect(step(items, 3, 'PageUp', 10)).toBe(0)
    const many = Array.from({ length: 30 }, (_, i) => ({ value: i }))
    expect(step(many, 4, 'PageDown', 8)).toBe(12)
    expect(step(many, 4, 'PageUp', 8)).toBe(0)
  })
  it('has nothing to mark in an empty list, and other keys leave the mark', () => {
    expect(step([], -1, 'ArrowDown')).toBe(-1)
    expect(step([{ value: 1, disabled: true }], -1, 'Home')).toBe(-1)
    expect(step(items, 2, 'a')).toBe(2)
  })
  it('finds the chosen option by its value as text', () => {
    expect(indexOf(items, '3')).toBe(2)
    expect(same(3, '3') && !same(null, 'null') && same('', '')).toBe(true)
  })
})

describe('six hundred options', () => {
  it('are searched without a noticeable delay', () => {
    const opts = Array.from({ length: 600 }, (_, i) => ({ value: 'Zone/' + i, label: 'City ' + i, hint: 'UTC+0' + (i % 10) + ':00 · Zone/' + i, group: ['a', 'b', 'c'][i % 3], keywords: ['Country ' + (i % 40), 'utc+' + (i % 10)] }))
    const t0 = performance.now()
    const p = prepare(opts)
    for (const q of ['c', 'ci', 'cit', 'city 1', 'utc+5', 'country 3', '']) search(p, [{ id: 'a' }, { id: 'b' }, { id: 'c' }], q)
    expect(performance.now() - t0).toBeLessThan(150)
    const r = search(p, [{ id: 'a' }, { id: 'b' }, { id: 'c' }], 'city 59')
    const starts = (o) => o.label.startsWith('City 59')
    expect(r.items.filter(starts)).toHaveLength(11)                     // City 59, City 590 … City 599
    expect(r.sections.map((s) => s.group.id)).toEqual(['a', 'b', 'c'])
    expect(r.sections[0].rows.slice(0, 3).map((x) => x.option.value)).toEqual(['Zone/591', 'Zone/594', 'Zone/597'])
    for (const s of r.sections) {          // in each group the labels that start with it first, then those that only hold both words
      const k = s.rows.map((x) => starts(x.option))
      expect(k).toEqual([...k].sort((x, y) => Number(y) - Number(x)))
    }
  })
})
