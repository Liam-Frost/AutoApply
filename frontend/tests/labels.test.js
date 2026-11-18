// A label belongs to the control it names (src/labels.js).
import { describe, expect, it } from 'vitest'
import { pair } from '../src/labels.js'

// elements, as far as pair() looks at them
function node(tag, opts = {}) {
  const attrs = { ...(opts.attrs || {}) }
  const n = {
    tagName: tag.toUpperCase(), id: opts.id || '', htmlFor: opts.for || '', kids: opts.kids || [], parent: null, control: !!opts.control, wrapped: !!opts.wrapped,
    get children() { return this.kids },
    get nextElementSibling() { const sibs = this.parent ? this.parent.kids : []; return sibs[sibs.indexOf(this) + 1] || null },
    all() { return this.kids.flatMap((k) => [k, ...k.all()]) },
    matches() { return this.control },
    querySelector() { return this.all().find((k) => k.control) || null },
    querySelectorAll() { return this.all().filter((k) => k.control) },
    closest(sel) { return sel === 'label' && this.wrapped ? {} : null },
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    setAttribute: (k, v) => { attrs[k] = v },
    attrs,
  }
  for (const k of n.kids) k.parent = n
  return n
}
const label = (o) => node('label', o)
const input = (o) => node('input', { control: true, ...o })
const div = (...kids) => node('div', { kids })

describe('pairing the labels of a form grid', () => {
  it('ties a label to the control that follows it', () => {
    const l = label(), c = input()
    const grid = div(l, div(c))
    expect(pair(grid)).toBe(1)
    expect(c.id).toBeTruthy()
    expect(l.htmlFor).toBe(c.id)
  })
  it('ties it to the control itself when that is what follows', () => {
    const l = label(), c = input({ id: 'port' })
    pair(div(l, c))
    expect(l.htmlFor).toBe('port')            // an id that is there is kept
  })
  it('names a row of several controls as a group', () => {
    const l = label(), a = input(), b = input()
    const row = div(a, b)
    pair(div(l, row))
    expect(l.htmlFor).toBe('')
    expect([row.attrs.role, row.attrs['aria-labelledby']]).toEqual(['group', l.id])
  })
  it('a field followed by a small option of its own is the field', () => {
    const l = label(), field = input(), option = input({ wrapped: true })     // "<input> <label><input type=checkbox> also ...</label>"
    pair(div(l, div(field, option)))
    expect(l.htmlFor).toBe(field.id)
  })
  it('names a choice made with buttons as a group', () => {
    const l = label(), seg = node('div', { kids: [node('button'), node('button')] })
    seg.querySelector = (sel) => (sel === 'button' ? seg.kids[0] : null)
    const grid = div(l, seg)
    expect(pair(grid)).toBe(1)
    expect([seg.attrs.role, seg.attrs['aria-labelledby']]).toEqual(['group', l.id])
    expect(pair(grid)).toBe(0)
  })
  it('leaves alone what already says what it is for', () => {
    const tied = label({ for: 'x' }), c1 = input({ id: 'x' })
    const wrapping = label({ kids: [input()] }), text = div()
    const lonely = label(), nothing = div()
    expect(pair(div(tied, c1, wrapping, text, lonely, nothing))).toBe(0)
    expect(tied.htmlFor).toBe('x')
    expect(lonely.htmlFor).toBe('')
  })
  it('does not take the next label for a value', () => {
    const a = label(), b = label(), c = input()
    pair(div(a, b, c))
    expect(a.htmlFor).toBe('')
    expect(b.htmlFor).toBe(c.id)
  })
  it('is done once: a second pass changes nothing', () => {
    const l = label(), c = input()
    const grid = div(l, div(c))
    pair(grid)
    const id = c.id
    expect(pair(grid)).toBe(0)
    expect(c.id).toBe(id)
  })
})
