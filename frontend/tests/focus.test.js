// Where the keyboard is while something is open over the page (src/focus.js).
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { hold, onTop, step } from '../src/focus.js'

// an element, as far as hold() looks at one
function el(name, kids = []) {
  const attrs = {}
  const listeners = {}
  return {
    name, inert: false, isConnected: true, listeners,
    querySelectorAll: () => kids,
    closest: () => null,
    hasAttribute: (k) => k in attrs,
    setAttribute: (k, v) => { attrs[k] = v },
    getAttribute: (k) => attrs[k],
    addEventListener: (n, f) => { listeners[n] = f },
    removeEventListener: (n) => { delete listeners[n] },
    focus() { globalThis.document.activeElement = this },
  }
}
const tab = (layer, shift = false) => { const ev = { key: 'Tab', shiftKey: shift, prevented: false, preventDefault() { this.prevented = true } }; layer.listeners.keydown(ev); return ev }

let page, opener
beforeEach(() => {
  page = el('page')
  opener = el('row')
  globalThis.document = { activeElement: opener, getElementById: (id) => (id === 'app' ? page : null) }
})
afterEach(() => { delete globalThis.document })

describe('Tab inside a layer', () => {
  it('goes on, and round the ends', () => {
    expect(step(0, 3, false)).toBe(1)
    expect(step(2, 3, false)).toBe(0)
    expect(step(0, 3, true)).toBe(2)
    expect(step(1, 3, true)).toBe(0)
  })
  it('enters at the near end when the focus is on none of them, and goes nowhere when there is nothing', () => {
    expect(step(-1, 3, false)).toBe(0)
    expect(step(-1, 3, true)).toBe(2)
    expect(step(-1, 0, false)).toBe(-1)
  })
})

describe('a layer that holds the keyboard', () => {
  it('takes the focus, keeps Tab inside, shuts the page behind, and gives the focus back', () => {
    const a = el('close'), b = el('save')
    const drawer = el('drawer', [a, b])
    const release = hold(drawer)
    expect(document.activeElement).toBe(drawer)             // the layer itself: its name is read out, nothing is one keypress away
    expect(page.inert).toBe(true)
    expect(drawer.getAttribute('tabindex')).toBe('-1')
    expect(tab(drawer).prevented).toBe(true)
    expect(document.activeElement).toBe(a)
    tab(drawer)
    expect(document.activeElement).toBe(b)
    tab(drawer)
    expect(document.activeElement).toBe(a)                  // round the end, not out into the page
    tab(drawer, true)
    expect(document.activeElement).toBe(b)
    release()
    expect(page.inert).toBe(false)
    expect(document.activeElement).toBe(opener)             // back where it was
  })
  it('starts where it is told to', () => {
    const cancel = el('cancel'), del = el('delete')
    const box = el('dialog', [cancel, del])
    hold(box, { first: () => cancel })()
    const release = hold(box, { first: () => cancel })
    expect(document.activeElement).toBe(cancel)             // a question that cannot be undone starts on "cancel"
    release()
  })
  it('a question over a drawer has the keyboard until it is answered', () => {
    const drawer = el('drawer', [el('x')])
    const closeDrawer = hold(drawer)
    const inDrawer = document.activeElement
    const ask = el('dialog', [el('no'), el('yes')])
    const answer = hold(ask)
    expect([onTop(ask), onTop(drawer), drawer.inert, page.inert]).toEqual([true, false, true, true])
    expect(tab(drawer).prevented).toBe(false)               // the layer underneath does not move the focus
    answer()
    expect([onTop(drawer), drawer.inert, page.inert]).toEqual([true, false, true])
    expect(document.activeElement).toBe(inDrawer)
    closeDrawer()
    expect([page.inert, onTop(drawer)]).toEqual([false, false])
  })
  it('does not give the focus back to something that is gone', () => {
    const drawer = el('drawer')
    const release = hold(drawer)
    opener.isConnected = false                               // the row was removed while the drawer was open
    release()
    expect(document.activeElement).toBe(drawer)             // left where it is, rather than thrown at something that is not on the page
  })
})
