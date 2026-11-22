// The widths of a DataTable's columns (src/tablelayout.js): decided by the column definitions and the box's width alone.
import { describe, expect, it } from 'vitest'
import { MIN_WIDTH, SELECT_WIDTH, layoutColumns } from '../src/tablelayout.js'

const sum = (r) => Object.values(r.widths).reduce((s, v) => s + v, 0)
// a list as the pages write them: who, a state, two dates, a score, the row's actions
const LIST = [
  { id: 'job', min: 220, flex: 2 },
  { id: 'status', width: 140 },
  { id: 'site', min: 120, max: 200, priority: 2 },
  { id: 'applied', min: 110, max: 150, priority: 1 },
  { id: 'score', width: 72, priority: 3 },
  { id: 'actions', width: 56 },
]

describe('layoutColumns: what a column asks for', () => {
  it('gives a fixed column its width at every width of the box', () => {
    for (const box of [500, 800, 1200, 2000]) expect(layoutColumns([{ id: 'a', width: 140 }, { id: 'b', min: 100 }], box).widths.a).toBe(140)
  })
  it('shares what is left after the minimums by flex', () => {
    const r = layoutColumns([{ id: 'a', min: 100, flex: 1 }, { id: 'b', min: 100, flex: 3 }, { id: 'c', width: 100 }], 700)
    expect(r.widths).toEqual({ a: 200, b: 400, c: 100 })
    expect(r).toMatchObject({ visible: ['a', 'b', 'c'], total: 700, scroll: false })
  })
  it('never makes a column narrower than its minimum or wider than its maximum while another can take the room', () => {
    const cols = [{ id: 'a', min: 120, max: 200 }, { id: 'b', min: 80, max: 90, flex: 5 }, { id: 'c', min: 150, flex: 1 }]
    for (let box = 350; box <= 1600; box += 37) {
      const r = layoutColumns(cols, box)
      expect(r.scroll).toBe(false)
      expect(r.widths.a).toBeGreaterThanOrEqual(120)
      expect(r.widths.a).toBeLessThanOrEqual(200)
      expect(r.widths.b).toBeGreaterThanOrEqual(80)
      expect(r.widths.b).toBeLessThanOrEqual(90)
      expect(r.widths.c).toBeGreaterThanOrEqual(150)
      expect(sum(r)).toBe(box)
    }
  })
  it('gives the part of a column that reached its maximum to the others', () => {
    // 600 left: by flex alone a and b would get 300 each; a stops at 150 (+50), b takes the other 550
    const r = layoutColumns([{ id: 'a', min: 100, max: 150, flex: 1 }, { id: 'b', min: 100, flex: 1 }], 800)
    expect(r.widths).toEqual({ a: 150, b: 650 })
    // two stop one after the other: a at 120, then b at 300, c takes all the rest
    const r2 = layoutColumns([{ id: 'a', min: 100, max: 120 }, { id: 'b', min: 100, max: 300 }, { id: 'c', min: 100 }], 1000)
    expect(r2.widths).toEqual({ a: 120, b: 300, c: 580 })
  })
  it('treats a column with only a minimum as flexible, and one that says nothing as flexible from 64px', () => {
    expect(MIN_WIDTH).toBe(64)
    expect(layoutColumns([{ id: 'a', min: 200 }, { id: 'b', min: 100 }], 500).widths).toEqual({ a: 300, b: 200 })
    expect(layoutColumns([{ id: 'a' }, { id: 'b' }], 400).widths).toEqual({ a: 200, b: 200 })
    const tight = layoutColumns([{ id: 'a' }, { id: 'b' }], 100)
    expect(tight).toMatchObject({ widths: { a: 64, b: 64 }, total: 128, scroll: true })
  })
  it('keeps a column with flex 0 at its minimum', () => {
    expect(layoutColumns([{ id: 'a', min: 90, flex: 0 }, { id: 'b', min: 100 }], 600).widths).toEqual({ a: 90, b: 510 })
  })
  it('reads a maximum below the default minimum, and a maximum below the minimum, without breaking', () => {
    expect(layoutColumns([{ id: 'a', max: 40 }, { id: 'b', min: 100 }], 600).widths).toEqual({ a: 40, b: 560 })
    expect(layoutColumns([{ id: 'a', min: 120, max: 80 }, { id: 'b', min: 100 }], 600).widths).toEqual({ a: 120, b: 480 })
  })
  it('fills the box even when every column is fixed or at its maximum', () => {
    // nothing is flexible: the columns that are not fixed take the room, in proportion
    const r = layoutColumns([{ id: 'a', width: 100 }, { id: 'b', min: 50, max: 100 }, { id: 'c', min: 50, max: 200 }], 700)
    expect(r.widths).toEqual({ a: 100, b: 200, c: 400 })
    expect(r.scroll).toBe(false)
    // every column fixed: all of them, in proportion
    expect(layoutColumns([{ id: 'a', width: 100 }, { id: 'b', width: 300 }], 800).widths).toEqual({ a: 200, b: 600 })
  })
})

describe('layoutColumns: whole pixels', () => {
  it('returns whole numbers that add up to exactly the box, at every width', () => {
    const cols = [{ id: 'a', min: 100, flex: 1 }, { id: 'b', min: 100, flex: 1 }, { id: 'c', min: 100, flex: 1 }, { id: 'd', min: 71, max: 133, flex: 0.7 }, { id: 'e', width: 57 }]
    for (let box = 428; box <= 1700; box++) {
      const r = layoutColumns(cols, box)
      expect(r.scroll).toBe(false)
      for (const v of Object.values(r.widths)) expect(Number.isInteger(v)).toBe(true)
      expect(sum(r)).toBe(box)
      expect(r.total).toBe(box)
      expect(r.widths.d).toBeLessThanOrEqual(133)
    }
  })
  it('gives the pixels that do not divide to the earlier columns, one each', () => {
    expect(layoutColumns([{ id: 'a', min: 100 }, { id: 'b', min: 100 }, { id: 'c', min: 100 }], 400).widths).toEqual({ a: 134, b: 133, c: 133 })
    expect(layoutColumns([{ id: 'a', min: 100 }, { id: 'b', min: 100 }, { id: 'c', min: 100 }], 401).widths).toEqual({ a: 134, b: 134, c: 133 })
  })
  it('takes a box whose width is not a whole number as the whole pixels inside it', () => {
    const r = layoutColumns([{ id: 'a', min: 100 }, { id: 'b', min: 100 }], 500.75)
    expect(r.total).toBe(500)
    expect(sum(r)).toBe(500)
  })
  it('rounds bounds that are not whole numbers', () => {
    const r = layoutColumns([{ id: 'a', width: 99.6 }, { id: 'b', min: 100.4 }], 500)
    expect(r.widths).toEqual({ a: 100, b: 400 })
  })
})

describe('layoutColumns: optional columns', () => {
  it('shows every column while the minimums fit', () => {
    const least = 220 + 140 + 120 + 110 + 72 + 56
    expect(layoutColumns(LIST, least).visible).toEqual(['job', 'status', 'site', 'applied', 'score', 'actions'])
    expect(layoutColumns(LIST, least).scroll).toBe(false)
    expect(layoutColumns(LIST, 1400).visible).toHaveLength(6)
  })
  it('hides the highest priority number first, one column at a time, only as far as needed', () => {
    const least = 220 + 140 + 120 + 110 + 72 + 56      // 718
    expect(layoutColumns(LIST, least - 1).visible).toEqual(['job', 'status', 'site', 'applied', 'actions'])        // without score (3)
    expect(layoutColumns(LIST, least - 72).visible).toEqual(['job', 'status', 'site', 'applied', 'actions'])       // 646: still fits without score
    expect(layoutColumns(LIST, least - 73).visible).toEqual(['job', 'status', 'applied', 'actions'])               // then site (2)
    expect(layoutColumns(LIST, 526).visible).toEqual(['job', 'status', 'applied', 'actions'])
    expect(layoutColumns(LIST, 525).visible).toEqual(['job', 'status', 'actions'])                                  // then applied (1)
    expect(layoutColumns(LIST, 416).visible).toEqual(['job', 'status', 'actions'])
    expect(layoutColumns(LIST, 416).scroll).toBe(false)
  })
  it('gives the room of a hidden column to the ones that stay', () => {
    const r = layoutColumns(LIST, 600)
    expect(r.visible).toEqual(['job', 'status', 'applied', 'actions'])
    expect(sum(r)).toBe(600)
    expect(r.widths.score).toBeUndefined()
    expect(r.widths.site).toBeUndefined()
    expect(r.widths.status).toBe(140)
    expect(r.widths.actions).toBe(56)
  })
  it('shows a column again when the box is wide enough again', () => {
    const narrow = layoutColumns(LIST, 500)
    const wide = layoutColumns(LIST, 1200)
    expect(narrow.visible).not.toContain('score')
    expect(wide.visible).toEqual(LIST.map((c) => c.id))
    // and it does not remember: the same width gives the same answer whatever was asked before
    expect(layoutColumns(LIST, 500)).toEqual(narrow)
  })
  it('never hides a column without priority: at their minimums the table scrolls inside its box', () => {
    const r = layoutColumns(LIST, 300)
    expect(r.visible).toEqual(['job', 'status', 'actions'])
    expect(r.widths).toEqual({ job: 220, status: 140, actions: 56 })
    expect(r.total).toBe(416)
    expect(r.scroll).toBe(true)
    // priority 0 or less is no priority
    const fixed = layoutColumns([{ id: 'a', min: 200, priority: 0 }, { id: 'b', min: 200, priority: -1 }], 300)
    expect(fixed).toMatchObject({ visible: ['a', 'b'], scroll: true, total: 400 })
  })
  it('hides the later of two columns with the same priority first', () => {
    const cols = [{ id: 'a', min: 100 }, { id: 'b', min: 100, priority: 1 }, { id: 'c', min: 100, priority: 1 }]
    expect(layoutColumns(cols, 250).visible).toEqual(['a', 'b'])
    expect(layoutColumns(cols, 150).visible).toEqual(['a'])
  })
  it('keeps the order of the definitions whatever was hidden', () => {
    const cols = [{ id: 'x', min: 100, priority: 1 }, { id: 'a', min: 100 }, { id: 'y', min: 100, priority: 5 }, { id: 'b', min: 100 }, { id: 'z', min: 100, priority: 3 }]
    expect(layoutColumns(cols, 450).visible).toEqual(['x', 'a', 'b', 'z'])
    expect(layoutColumns(cols, 350).visible).toEqual(['x', 'a', 'b'])
    expect(layoutColumns(cols, 250).visible).toEqual(['a', 'b'])
  })
})

describe('layoutColumns: the checkbox column', () => {
  it('keeps 40px for it when the table is selectable', () => {
    expect(SELECT_WIDTH).toBe(40)
    const r = layoutColumns([{ id: 'a', min: 100 }, { id: 'b', width: 100 }], 500, { selectable: true })
    expect(r.select).toBe(40)
    expect(r.widths).toEqual({ a: 360, b: 100 })
    expect(r.total).toBe(500)
    expect(layoutColumns([{ id: 'a', min: 100 }], 500).select).toBe(0)
  })
  it('counts it when deciding what fits', () => {
    const cols = [{ id: 'a', min: 200 }, { id: 'b', min: 100, priority: 1 }]
    expect(layoutColumns(cols, 320).visible).toEqual(['a', 'b'])
    expect(layoutColumns(cols, 320, { selectable: true }).visible).toEqual(['a'])
    expect(layoutColumns(cols, 220, { selectable: true })).toMatchObject({ visible: ['a'], total: 240, scroll: true })
  })
})

describe('layoutColumns: what it cannot be moved by', () => {
  it('never sees the rows: the same definitions and width give the same widths, whatever else a column object carries', () => {
    const long = 'x'.repeat(5000)
    const plain = layoutColumns(LIST, 1000)
    const noisy = layoutColumns(LIST.map((c) => ({ ...c, header: long, headerTip: long, class: long, sortable: true, align: 'end' })), 1000)
    expect(noisy).toEqual(plain)
    expect(layoutColumns.length).toBeLessThanOrEqual(3)      // (columns, width, opts): there is no way to pass it data
  })
  it('does not change the definitions it was given', () => {
    const cols = LIST.map((c) => Object.freeze({ ...c }))
    const before = JSON.stringify(cols)
    layoutColumns(Object.freeze(cols), 300)
    expect(JSON.stringify(cols)).toBe(before)
  })
  it('answers for a box that is not there yet (no width, zero, nonsense) without failing', () => {
    for (const box of [0, undefined, null, NaN, -50, 'wide']) {
      const r = layoutColumns(LIST, box)
      expect(r.scroll).toBe(true)
      expect(r.visible).toEqual(['job', 'status', 'actions'])
      expect(r.total).toBe(416)
    }
    expect(layoutColumns([], 500)).toEqual({ visible: [], widths: {}, total: 0, scroll: false, select: 0 })
    expect(layoutColumns(undefined, 500).visible).toEqual([])
  })
})
