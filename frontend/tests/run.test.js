// Carrying out an action (ui.run): once is enough, what failed is told from what could not be shown, queued work
// says where it stands, a form keeps its error.
import { afterEach, describe, expect, it } from 'vitest'
import { busy, formErrors, run, toasts } from '../src/ui.js'

const later = () => { let done, fail; const p = new Promise((res, rej) => { done = res; fail = rej }); return { p, done, fail } }
const said = () => toasts.map((t) => [t.text, t.tone])
afterEach(() => { toasts.splice(0); for (const k of Object.keys(formErrors)) delete formErrors[k]; globalThis.window.event = undefined })

// a button, as far as run() looks at one
const button = () => { const attrs = new Set(); return { isConnected: true, attrs, setAttribute: (k) => attrs.add(k), removeAttribute: (k) => attrs.delete(k) } }
const click = (el) => { globalThis.window.event = { type: 'click', target: { closest: () => el } } }

describe('run', () => {
  it('says the outcome and reads the page afresh', async () => {
    const order = []
    const r = await run(async () => { order.push('do'); return { id: 3 } }, (x) => `made ${x.id}`, async () => { order.push('refresh') })
    expect(r).toEqual({ id: 3 })
    expect(order).toEqual(['do', 'refresh'])
    expect(said()).toEqual([['made 3', '']])
    expect(await run(async () => {}, 'ok')).toBe(true)          // an action that returns nothing still "worked"
  })
  it('an action with a name runs once at a time', async () => {
    const gate = later()
    let n = 0
    const first = run(async () => { n++; await gate.p }, 'done', null, { name: 'approve' })
    expect(busy('approve')).toBe(true)
    expect(await run(async () => { n++ }, 'done', null, { name: 'approve' })).toBe(false)      // pressed again while it runs
    gate.done()
    await first
    expect([n, busy('approve')]).toEqual([1, false])
    expect(await run(async () => { n++ }, 'done', null, { name: 'approve' })).toBe(true)       // and again when it is over
    expect(n).toBe(2)
  })
  it('the button that was pressed is marked until the action is over, and a second press does nothing', async () => {
    const el = button()
    const gate = later()
    let n = 0
    click(el)
    const first = run(async () => { n++; await gate.p }, 'done')
    expect([...el.attrs].sort()).toEqual(['aria-busy', 'data-busy'])
    click(el)
    expect(await run(async () => { n++ }, 'done')).toBe(false)
    click(button())                                              // another button is another action
    expect(await run(async () => { n++ }, 'done')).toBe(true)
    gate.done()
    await first
    expect([n, el.attrs.size]).toEqual([2, 0])
  })
  it('the mark comes off when the action fails, too', async () => {
    const el = button()
    click(el)
    expect(await run(async () => { throw new Error('refused') }, 'done')).toBe(false)
    expect(el.attrs.size).toBe(0)
    expect(said()).toEqual([['refused', 'bad']])
  })
  it('tells "it failed" from "it is done, and the page could not be read afresh"', async () => {
    let refreshed = 0
    expect(await run(async () => { throw new Error('the draft is not approved') }, 'done', async () => { refreshed++ })).toBe(false)
    expect(said()).toEqual([['the draft is not approved', 'bad']])
    expect(refreshed).toBe(1)                                    // the page is read afresh all the same: it may be what is out of date
    toasts.splice(0)
    expect(await run(async () => 'x', 'saved', async () => { throw new Error('no answer') })).toBe('x')
    expect(said().map((x) => x[1])).toEqual(['', 'warn'])       // the success is said; then that it could not be shown
    expect(said()[1][0]).toContain('no answer')
    toasts.splice(0)
    // a page that keeps its own state of what it reads (data.js) says so itself: its load resolves to false, nothing more is said here
    expect(await run(async () => 'x', 'saved', async () => false)).toBe('x')
    expect(said()).toEqual([['saved', '']])
  })
  it('queued work says where to look for it', async () => {
    await run(async () => ({ task_id: 12 }), 'started')
    expect(toasts[0].to).toEqual({ path: '/runs', query: { tab: 'plan' } })
    expect(toasts[0].link).toBeTruthy()
    toasts.splice(0)
    await run(async () => ({ ok: true }), 'saved')
    expect(toasts[0].to).toBeUndefined()
  })
  it('the error of a form stays on the form, until it is sent again', async () => {
    expect(await run(async () => { throw new Error('unknown setting x') }, 'saved', null, { form: 'settings' })).toBe(false)
    expect(formErrors.settings).toBe('unknown setting x')
    expect(said()).toEqual([])                                   // not in a message that is gone in nine seconds
    const gate = later()
    const again = run(async () => { await gate.p }, 'saved', null, { form: 'settings' })
    expect(formErrors.settings).toBeUndefined()                  // cleared as soon as it is sent again
    gate.done()
    await again
    expect(said()).toEqual([['saved', '']])
  })
})
