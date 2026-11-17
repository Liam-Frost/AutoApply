// The state of something a page reads from the server (src/data.js).
import { describe, expect, it } from 'vitest'
import { after, clock, dataState } from '../src/data.js'

describe('after a read', () => {
  it('is ready when it worked, with the moment it was read', () => {
    expect(after({ phase: 'loading', error: '', at: null }, true, '', 1000)).toEqual({ phase: 'ready', error: '', at: 1000 })
    expect(after({ phase: 'stale', error: 'x', at: 500 }, true, '', 2000)).toEqual({ phase: 'ready', error: '', at: 2000 })
  })
  it('is an error when nothing was ever read, and stale when something was', () => {
    expect(after({ phase: 'loading', error: '', at: null }, false, 'boom', 1000)).toEqual({ phase: 'error', error: 'boom', at: null })
    expect(after({ phase: 'ready', error: '', at: 500 }, false, 'boom', 1000)).toEqual({ phase: 'stale', error: 'boom', at: 500 })      // what is shown keeps the time it was read
    expect(after({ phase: 'error', error: 'a', at: null }, false, '', 1000).error).toBeTruthy()                                       // an error always says something
  })
})

describe('dataState', () => {
  it('starts as "loading", not as an empty list', () => {
    const { st } = dataState(async () => {})
    expect(st.phase).toBe('loading')
    expect(st.at).toBeNull()
  })
  it('follows the reads, and never throws', async () => {
    let fail = false
    const { st, load } = dataState(async () => { if (fail) throw new Error('the server is not there') })
    expect(await load()).toBe(true)
    expect(st.phase).toBe('ready')
    const at = st.at
    fail = true
    expect(await load()).toBe(false)
    expect([st.phase, st.error, st.at, st.busy]).toEqual(['stale', 'the server is not there', at, false])
    fail = false
    expect(await load()).toBe(true)
    expect([st.phase, st.error]).toEqual(['ready', ''])
  })
  it('is an error when the first read fails', async () => {
    const { st, load } = dataState(async () => { throw new Error('no') })
    await load()
    expect([st.phase, st.at]).toEqual(['error', null])
  })
  it('an answer that a later request overtook says nothing about now', async () => {
    const waits = []
    const { st, load } = dataState(() => new Promise((resolve, reject) => waits.push({ resolve, reject })))
    const first = load()
    const second = load()
    waits[1].resolve()
    await second
    expect(st.phase).toBe('ready')
    waits[0].reject(new Error('late and failed'))      // the earlier request fails after the later one succeeded
    await first
    expect([st.phase, st.error, st.busy]).toEqual(['ready', '', false])
  })
  it('passes its arguments on to the page\'s own function', async () => {
    const got = []
    const { load } = dataState(async (...a) => { got.push(a) })
    await load('x', 2)
    expect(got).toEqual([['x', 2]])
  })
})

describe('clock', () => {
  it('is hours and minutes, and nothing for no time', () => {
    expect(clock(new Date(2026, 10, 18, 9, 5).getTime())).toMatch(/^0?9:05$/)
    expect(clock(null)).toBe('')
  })
})
