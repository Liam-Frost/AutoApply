// What has been typed and not saved (src/dirty.js).
import { beforeEach, describe, expect, it, vi } from 'vitest'

const picked = { next: 'stay', asked: [] }
vi.mock('../src/ui', () => ({ choose: (text, choices, cancel) => { picked.asked.push({ text, keys: choices.map((c) => c.key), cancel }); return Promise.resolve(picked.next) } }))
vi.mock('vue-router', () => ({ useRoute: () => null }))

const { absorb, changed, clone, installGuards, mayLeave, same, unsaved, useUnsaved } = await import('../src/dirty.js')

describe('same: is this what was saved?', () => {
  it('takes "nothing there" in all its forms for the same thing', () => {
    for (const a of [undefined, null, '', false, []]) for (const b of [undefined, null, '', false, []]) expect(same(a, b)).toBe(true)
    expect(same(0, '')).toBe(false)           // a number that was typed is something
    expect(same({}, undefined)).toBe(false)
  })
  it('does not mind the order of keys, minds the order of a list', () => {
    expect(same({ a: 1, b: [1, 2] }, { b: [1, 2], a: 1 })).toBe(true)
    expect(same([1, 2], [2, 1])).toBe(false)
    expect(same({ on: false, from: '22:00' }, { from: '22:00' })).toBe(true)      // a box that was never ticked and one that was unticked
    expect(same({ a: { b: 1 } }, { a: { b: 2 } })).toBe(false)
    expect(same(7, 7.5)).toBe(false)
    expect(same('7', 7)).toBe(false)
  })
})

describe('changed and absorb', () => {
  it('names the keys that differ', () => {
    expect(changed({ a: 1, b: [], c: 'x' }, { a: 1, b: undefined, c: 'y', d: true }).sort()).toEqual(['c', 'd'])
    expect(changed(null, { a: false })).toEqual([])
  })
  it('reading afresh takes what is new and leaves what is being edited', () => {
    const base = { score: 7, name: 'a', list: [1] }
    const now = clone(base)
    now.score = 7.5                                             // being edited
    absorb(now, base, { score: 8, name: 'b', list: [1, 2], more: 'x' })     // meanwhile saved elsewhere
    expect(now).toEqual({ score: 7.5, name: 'b', list: [1, 2], more: 'x' })
    expect(base).toEqual({ score: 8, name: 'b', list: [1, 2], more: 'x' })
    expect(changed(base, now)).toEqual(['score'])               // and it still counts as changed, against what is saved now
    now.list.push(3)
    expect(base.list).toEqual([1, 2])                           // what was taken is a copy
  })
})

describe('mayLeave: asked before what was typed is lost', () => {
  let area, off
  beforeEach(() => {
    picked.asked.length = 0
    if (off) off()
    area = { id: 'a', label: '设置', dirty: () => area.changed, changed: false, saved: 0, dropped: 0, save: async () => { area.saved++; area.changed = !area.ok; return area.ok }, ok: true, discard: () => { area.dropped++; area.changed = false } }
    off = useUnsaved(area)
  })
  it('asks nothing when nothing was changed', async () => {
    expect(await mayLeave()).toBe(true)
    expect(picked.asked).toEqual([])
    expect(unsaved.value).toEqual([])
  })
  it('stays, discards or saves as chosen', async () => {
    area.changed = true
    picked.next = 'stay'
    expect(await mayLeave()).toBe(false)
    expect(picked.asked[0].keys).toEqual(['stay', 'discard', 'save'])
    expect(picked.asked[0].cancel).toBe('stay')                 // closing the question without choosing is staying
    expect(picked.asked[0].text).toContain('设置')
    picked.next = 'discard'
    expect(await mayLeave()).toBe(true)
    expect(area.dropped).toBe(1)
    area.changed = true
    picked.next = 'save'
    expect(await mayLeave()).toBe(true)
    expect(area.saved).toBe(1)
  })
  it('stays when the save did not succeed', async () => {
    area.changed = true
    area.ok = false
    picked.next = 'save'
    expect(await mayLeave()).toBe(false)
    expect(area.changed).toBe(true)
  })
  it('offers no "save" for an area that cannot be saved from the question', async () => {
    area.changed = true
    area.save = null
    picked.next = 'stay'
    await mayLeave()
    expect(picked.asked[0].keys).toEqual(['stay', 'discard'])
  })
  it('asks only about the areas that would be lost', async () => {
    area.changed = true
    area.scope = '/settings'
    picked.next = 'stay'
    expect(await mayLeave(null, '/settings/system/network')).toBe(true)      // it stays on the page there
    expect(await mayLeave(null, '/settingsx')).toBe(false)                   // not under it
    expect(await mayLeave(['other'])).toBe(true)                             // another area is being left
    expect(await mayLeave(['a'])).toBe(false)
  })
  it('guards the router and the closing of the tab', async () => {
    const guards = []
    const listeners = {}
    globalThis.window.addEventListener = (name, fn) => { listeners[name] = fn }
    installGuards({ beforeEach: (fn) => guards.push(fn) })
    expect(await guards[0]({ path: '/jobs' }, { path: '/jobs' })).toBe(true)        // only the query changed
    area.changed = true
    picked.next = 'stay'
    expect(await guards[0]({ path: '/jobs' }, { path: '/settings' })).toBe(false)
    const ev = { preventDefault: vi.fn() }
    listeners.beforeunload(ev)
    expect(ev.preventDefault).toHaveBeenCalled()
    area.changed = false
    const quiet = { preventDefault: vi.fn() }
    listeners.beforeunload(quiet)
    expect(quiet.preventDefault).not.toHaveBeenCalled()
  })
})
