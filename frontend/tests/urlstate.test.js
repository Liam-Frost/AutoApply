// What a page is showing, in its address (src/urlstate.js).
import { describe, expect, it } from 'vitest'
import { fromQuery, sameQuery, toQuery } from '../src/urlstate.js'

const DEFAULTS = { group: 'todo', q: '', minScore: 0, link: false, sort: 'score', dir: -1 }

describe('the state as a query', () => {
  it('leaves out what is the default: the plain page has the plain address', () => {
    expect(toQuery({ ...DEFAULTS }, DEFAULTS)).toEqual({})
  })
  it('writes what differs', () => {
    expect(toQuery({ ...DEFAULTS, group: 'applied', q: 'analyst', minScore: 7.5, link: true, dir: 1 }, DEFAULTS))
      .toEqual({ group: 'applied', q: 'analyst', minScore: '7.5', link: '1', dir: '1' })
  })
  it('does not write what the page does not keep there', () => {
    expect(toQuery({ ...DEFAULTS, picked: [1, 2], q: null }, DEFAULTS)).toEqual({})
  })
})

describe('the state a query describes', () => {
  it('is the defaults for an empty address', () => {
    expect(fromQuery({}, DEFAULTS)).toEqual(DEFAULTS)
    expect(fromQuery(undefined, DEFAULTS)).toEqual(DEFAULTS)
  })
  it('gives each value the type of its default', () => {
    const st = fromQuery({ group: 'applied', minScore: '7.5', link: '1', dir: '1', q: 'data analyst' }, DEFAULTS)
    expect(st).toEqual({ group: 'applied', q: 'data analyst', minScore: 7.5, link: true, sort: 'score', dir: 1 })
  })
  it('comes back the same after a round trip', () => {
    const st = { ...DEFAULTS, group: 'progress', q: 'ML', minScore: 8, link: true, sort: 'deadline', dir: 1 }
    expect(fromQuery(toQuery(st, DEFAULTS), DEFAULTS)).toEqual(st)
  })
  it('takes nothing an address has no business saying', () => {
    const st = fromQuery({ group: 'nonsense', sort: '__proto__', minScore: 'abc', evil: '1', dir: ['1', '2'] }, DEFAULTS, { group: ['todo', 'applied'], sort: ['score', 'deadline'] })
    expect(st).toEqual({ ...DEFAULTS, dir: 1 })
    expect('evil' in st).toBe(false)
  })
})

describe('two queries', () => {
  it('are the same whatever the order of their keys, and not when a value differs', () => {
    expect(sameQuery({ a: '1', b: '2' }, { b: '2', a: '1' })).toBe(true)
    expect(sameQuery({ a: '1' }, { a: 1 })).toBe(true)
    expect(sameQuery({ a: '1' }, { a: '2' })).toBe(false)
    expect(sameQuery({ a: '1' }, { a: '1', b: '2' })).toBe(false)
    expect(sameQuery({}, undefined)).toBe(true)
  })
})
