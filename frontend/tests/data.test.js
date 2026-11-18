// The state of something a page reads from the server (src/data.js).
import { describe, expect, it } from 'vitest'
import { after, clock, dataState, mayRefresh, signature, typingIn } from '../src/data.js'

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

describe('reading a list again', () => {
  it('the counts of the sidebar say when something changed', () => {
    const a = { open_todos: 3, pending_drafts: 2, queued_tasks: 0, running: [], paused: false }
    expect(signature(a)).toBe(signature({ ...a, mail_recent: ['x'], drivers: [1] }))        // what is not a count of work does not matter
    expect(signature(a)).not.toBe(signature({ ...a, open_todos: 2 }))
    expect(signature(a)).not.toBe(signature({ ...a, pending_drafts: 3 }))
    expect(signature(a)).not.toBe(signature({ ...a, queued_tasks: 1 }))
    expect(signature(a)).not.toBe(signature({ ...a, running: [{ id: 7, label: 'x' }] }))
    expect(signature({ ...a, running: [{ id: 7 }] })).not.toBe(signature({ ...a, running: [{ id: 8 }] }))      // another task took its place
    expect(signature(a)).not.toBe(signature({ ...a, paused: true }))
    expect(signature(null)).toBe('')
    // where the applications stand is part of it: one that was confirmed elsewhere changes no count of work
    const b = { ...a, stage_counts: { submitted: 3, confirmed: 1 } }
    expect(signature(b)).not.toBe(signature({ ...a, stage_counts: { submitted: 2, confirmed: 2 } }))
    expect(signature(b)).toBe(signature({ ...a, stage_counts: { confirmed: 1, submitted: 3 } }))      // the order they are listed in does not matter
  })
  it('not while a question is open, not in a window nobody looks at, not twice in a moment', () => {
    expect(mayRefresh(10_000, 0, false, false)).toBe(true)
    expect(mayRefresh(10_000, 0, true, false)).toBe(false)
    expect(mayRefresh(10_000, 0, false, true)).toBe(false)
    expect(mayRefresh(10_000, 0, false, false, true)).toBe(false)       // something is being typed
    expect(mayRefresh(10_000, 9_000, false, false)).toBe(false)
    expect(mayRefresh(10_000, 8_500, false, false)).toBe(true)
  })
})

describe('something is being typed', () => {
  const field = (value, more = {}) => ({ tagName: 'INPUT', type: 'number', value, ...more })
  it('when the field the keyboard is in no longer holds what it held', () => {
    const f = field('30')
    const held = { el: f, value: '30' }
    expect(typingIn(f, held)).toBe(false)              // clicked into, nothing typed
    f.value = '4'
    expect(typingIn(f, held)).toBe(true)               // "45" half typed: reading again now would put "30" back
    expect(typingIn(field('4'), held)).toBe(false)     // the keyboard is somewhere else
    expect(typingIn(null, held)).toBe(false)
    expect(typingIn(f, null)).toBe(false)
  })
  it('in a text box, a list or a number - not in a tick box or a button', () => {
    for (const el of [{ tagName: 'TEXTAREA', value: 'b' }, { tagName: 'SELECT', value: 'b' }, field('b', { type: 'text' }), field('b', { type: 'search' })]) expect(typingIn(el, { el, value: 'a' })).toBe(true)
    for (const el of [field('b', { type: 'checkbox' }), field('b', { type: 'radio' }), { tagName: 'BUTTON', value: 'b' }, { tagName: 'DIV', value: 'b' }]) expect(typingIn(el, { el, value: 'a' })).toBe(false)
  })
})
