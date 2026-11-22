// Where a tooltip, a menu or a popover is put (src/float.js): on the wanted side when it fits, on the other side when
// it does not, and always inside the window. And what the tooltip's directive reads from its binding (src/tip.js).
import { describe, expect, it } from 'vitest'
import { place } from '../src/float.js'
import { read } from '../src/tip.js'

const VP = { width: 1000, height: 600 }
const rect = (left, top, w = 40, h = 20) => ({ left, top, right: left + w, bottom: top + h })
const TIP = { width: 120, height: 30 }
const inside = (p, size, vp = VP, pad = 8) => p.left >= pad && p.top >= pad && p.left + size.width <= vp.width - pad && p.top + size.height <= vp.height - pad

describe('place', () => {
  it('puts the box on the wanted side, centred on the anchor', () => {
    const a = rect(480, 300)
    expect(place(a, TIP, VP, { placement: 'top' })).toEqual({ left: 440, top: 262, placement: 'top' })
    expect(place(a, TIP, VP, { placement: 'bottom' })).toEqual({ left: 440, top: 328, placement: 'bottom' })
    expect(place(a, TIP, VP, { placement: 'left' })).toEqual({ left: 352, top: 295, placement: 'left' })
    expect(place(a, TIP, VP, { placement: 'right' })).toEqual({ left: 528, top: 295, placement: 'right' })
  })
  it('is above by default, 8px away', () => {
    expect(place(rect(480, 300), TIP, VP)).toEqual({ left: 440, top: 262, placement: 'top' })
  })
  it('goes to the other side when the wanted one has no room', () => {
    expect(place(rect(480, 10), TIP, VP, { placement: 'top' }).placement).toBe('bottom')
    expect(place(rect(480, 570), TIP, VP, { placement: 'bottom' }).placement).toBe('top')
    expect(place(rect(20, 300), TIP, VP, { placement: 'left' }).placement).toBe('right')
    expect(place(rect(950, 300), TIP, VP, { placement: 'right' }).placement).toBe('left')
  })
  it('keeps the wanted side when it fits exactly, and leaves it one pixel short of that', () => {
    // above needs height 30 + offset 8 + pad 8 = 46
    expect(place(rect(480, 46), TIP, VP, { placement: 'top' })).toMatchObject({ top: 8, placement: 'top' })
    expect(place(rect(480, 45), TIP, VP, { placement: 'top' }).placement).toBe('bottom')
  })
  it('moves along the other axis to stay inside the window', () => {
    expect(place(rect(0, 300), TIP, VP, { placement: 'top' })).toMatchObject({ left: 8, placement: 'top' })
    expect(place(rect(960, 300), TIP, VP, { placement: 'top' })).toMatchObject({ left: 1000 - 8 - 120, placement: 'top' })
    expect(place(rect(480, 0), TIP, VP, { placement: 'right' })).toMatchObject({ top: 8, placement: 'right' })
    expect(place(rect(480, 580), TIP, VP, { placement: 'right' })).toMatchObject({ top: 600 - 8 - 30, placement: 'right' })
  })
  it('stays inside the window in every corner, whatever side was asked for', () => {
    for (const [x, y] of [[0, 0], [960, 0], [0, 580], [960, 580], [480, 0], [480, 580], [0, 290], [960, 290]]) {
      for (const placement of ['top', 'bottom', 'left', 'right']) {
        for (const align of ['center', 'start', 'end']) {
          const p = place(rect(x, y), TIP, VP, { placement, align })
          expect(inside(p, TIP), `${x},${y} ${placement} ${align} -> ${JSON.stringify(p)}`).toBe(true)
        }
      }
    }
  })
  it('does not cover the anchor when one of the two sides has room', () => {
    const a = rect(960, 0)
    const p = place(a, TIP, VP, { placement: 'top' })
    expect(p.placement).toBe('bottom')
    expect(p.top).toBeGreaterThanOrEqual(a.bottom + 8)
  })
  it('takes the side with more room when neither has enough, and stays in the window', () => {
    const big = { width: 200, height: 400 }
    expect(place(rect(480, 200), big, VP, { placement: 'top' })).toMatchObject({ placement: 'bottom', top: 600 - 8 - 400 })
    expect(place(rect(480, 380), big, VP, { placement: 'bottom' })).toMatchObject({ placement: 'top', top: 8 })
    // equal room: the wanted side stays
    expect(place(rect(480, 290), big, VP, { placement: 'bottom' }).placement).toBe('bottom')
  })
  it('starts at the near edge when the box is larger than the window', () => {
    const p = place(rect(480, 300), { width: 1200, height: 700 }, VP, { placement: 'bottom' })
    expect(p.left).toBe(8)
    expect(p.top).toBe(8)
  })
  it('lines a menu up with the start or the end of its button', () => {
    const a = rect(500, 100, 28, 28)
    const menu = { width: 200, height: 150 }
    expect(place(a, menu, VP, { placement: 'bottom', align: 'start', offset: 4 })).toEqual({ left: 500, top: 132, placement: 'bottom' })
    expect(place(a, menu, VP, { placement: 'bottom', align: 'end', offset: 4 })).toEqual({ left: 328, top: 132, placement: 'bottom' })
    // beside the anchor, start / end are its top / bottom edges
    expect(place(a, menu, VP, { placement: 'right', align: 'start', offset: 4 })).toEqual({ left: 532, top: 100, placement: 'right' })
    expect(place(a, menu, VP, { placement: 'right', align: 'end', offset: 4 })).toMatchObject({ top: 8 })      // 128 - 150 would be above the window
  })
  it('keeps an end-aligned menu inside the window at both edges', () => {
    const menu = { width: 200, height: 150 }
    expect(place(rect(964, 100, 28, 28), menu, VP, { placement: 'bottom', align: 'end' }).left).toBe(792)      // right edges in line
    expect(place(rect(10, 100, 28, 28), menu, VP, { placement: 'bottom', align: 'end' }).left).toBe(8)         // would start left of the window
    expect(place(rect(964, 100, 28, 28), menu, VP, { placement: 'bottom', align: 'start' }).left).toBe(792)    // would end right of it
    expect(place(rect(964, 560, 28, 28), menu, VP, { placement: 'bottom', align: 'end' })).toMatchObject({ placement: 'top', top: 560 - 8 - 150 })
  })
  it('honours the offset and the padding it is given', () => {
    expect(place(rect(480, 300), TIP, VP, { placement: 'bottom', offset: 0 }).top).toBe(320)
    expect(place(rect(0, 300), TIP, VP, { placement: 'bottom', pad: 20 }).left).toBe(20)
  })
  it('falls back to "top" for a side it does not know', () => {
    expect(place(rect(480, 300), TIP, VP, { placement: 'north' }).placement).toBe('top')
  })
  it('gives whole pixels', () => {
    const p = place({ left: 100.4, top: 200.7, right: 133.9, bottom: 221.2 }, { width: 61, height: 27 }, VP)
    expect(Number.isInteger(p.left) && Number.isInteger(p.top)).toBe(true)
  })
})

describe('what v-tip reads from its binding', () => {
  it('takes a string as the text', () => {
    expect(read({ value: 'Show the password', modifiers: {} })).toEqual({ text: 'Show the password', placement: 'top', max: 320, overflow: false, press: false })
  })
  it('takes an object with the text, the side and the width', () => {
    expect(read({ value: { text: 'Why', placement: 'bottom', max: 200 }, modifiers: {} })).toMatchObject({ text: 'Why', placement: 'bottom', max: 200 })
    expect(read({ value: { text: 'Why', placement: 'sideways', max: 'wide' }, modifiers: {} })).toMatchObject({ placement: 'top', max: 320 })
  })
  it('has no text for nothing, an empty string, or blanks', () => {
    for (const value of [undefined, null, '', '   ', {}, { text: null }, false]) expect(read({ value, modifiers: {} }).text).toBe('')
  })
  it('makes a number its text', () => {
    expect(read({ value: 42, modifiers: {} }).text).toBe('42')
  })
  it('knows the modifiers', () => {
    expect(read({ value: undefined, modifiers: { overflow: true } })).toMatchObject({ text: '', overflow: true, press: false })
    expect(read({ value: 'x', modifiers: { press: true } })).toMatchObject({ overflow: false, press: true })
  })
})
