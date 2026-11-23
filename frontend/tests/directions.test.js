// A posting's field (src/directions.js): a key of the fixed list, named in the reader's language; the filter lists the
// fields with their specialties under them, and what is not sorted yet last.
import { afterEach, describe, expect, it } from 'vitest'
import { UNSORTED, dirLabel, fieldOf, filterOptions, isKey, under } from '../src/directions.js'
import { i18n } from '../src/i18n/catalog'

afterEach(() => { i18n.global.locale.value = 'zh' })

describe('a field', () => {
  it('is a key of the list, named in the language of the page', () => {
    expect(isKey('software.backend')).toBe(true)
    expect(isKey('civil')).toBe(true)
    expect(isKey('other')).toBe(true)
    expect(isKey('后端')).toBe(false)
    expect(isKey('other (mining engineering)')).toBe(false)
    expect(isKey('software.nothing')).toBe(false)
    expect(dirLabel('software.backend')).toBe('后端')
    expect(dirLabel('software.backend', { whole: true })).toBe('软件工程 · 后端')
    expect(dirLabel('civil')).toBe('土木、建筑与矿业')
    i18n.global.locale.value = 'en'
    expect(dirLabel('software.backend', { whole: true })).toBe('Software engineering · Back end')
    expect(fieldOf('software.backend')).toBe('software')
  })
  it('from before the list is shown as it was, and filtered as not sorted yet', () => {
    expect(dirLabel('全栈/后端')).toBe('全栈/后端')
    expect(dirLabel('')).toBe('')
    expect(under('全栈/后端', UNSORTED)).toBe(true)
    expect(under('software.backend', UNSORTED)).toBe(false)
    expect(under('', UNSORTED)).toBe(false)
  })
  it('takes in its specialties when the filter asks for it', () => {
    expect(under('software.backend', 'software')).toBe(true)
    expect(under('software', 'software')).toBe(true)
    expect(under('software.backend', 'software.backend')).toBe(true)
    expect(under('software.fullstack', 'software.backend')).toBe(false)
    expect(under('data.science', 'software')).toBe(false)
    expect(under('anything', '')).toBe(true)
  })
})

describe('the filter', () => {
  it('lists each field with how many, its specialties under it, the largest first, and what is not sorted yet last', () => {
    const values = ['software.backend', 'software.backend', 'software.fullstack', 'software', 'civil.mining', '其他', '', 'other']
    const opts = filterOptions(values)
    expect(opts.map((o) => [o.value, o.n, o.sub])).toEqual([
      ['software', 4, false], ['software.backend', 2, true], ['software.fullstack', 1, true],
      ['civil', 1, false], ['civil.mining', 1, true],
      ['other', 1, false],
      [UNSORTED, 1, false],
    ])
    expect(opts[0].label).toBe('软件工程')
    expect(opts.at(-1).label).toBe('尚未归类')
  })
})
