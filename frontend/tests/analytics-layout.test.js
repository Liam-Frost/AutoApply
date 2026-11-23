// How the analysis page composes its cards (src/views/analytics/layout.js): which cards share a row, how many kinds of
// to-do are shown before the rest goes behind a control, and where an open to-do stands.
import { describe, expect, it } from 'vitest'
import { H, LEAST, bars, pairs, reasons, splitTop, standing, table } from '../src/views/analytics/layout.js'

const rows = (n) => Array.from({ length: n }, (_, i) => ({ kind: 'k' + i, n: 100 - i }))

describe('splitTop', () => {
  it('shows every kind when there are few, and never hides a single one', () => {
    for (const n of [0, 1, 5, 6]) {
      const s = splitTop(rows(n), 5)
      expect(s.shown).toHaveLength(n)
      expect(s.rest).toEqual([])
    }
  })
  it('shows the first five of more, in their order, and keeps the rest whole', () => {
    const all = rows(9)
    const s = splitTop(all, 5)
    expect(s.shown.map((r) => r.kind)).toEqual(['k0', 'k1', 'k2', 'k3', 'k4'])
    expect(s.rest.map((r) => r.kind)).toEqual(['k5', 'k6', 'k7', 'k8'])
    expect([...s.shown, ...s.rest]).toEqual(all)      // nothing merged, nothing dropped, no count changed
  })
  it('takes nothing for an empty or missing list', () => {
    expect(splitTop(undefined)).toEqual({ shown: [], rest: [] })
    expect(splitTop(null, 3)).toEqual({ shown: [], rest: [] })
  })
})

describe('pairs', () => {
  it('puts two cards side by side only when the shorter holds most of the taller', () => {
    expect(pairs(300, 300)).toBe(true)
    expect(pairs(300, 300 * LEAST)).toBe(true)
    expect(pairs(300, 300 * LEAST - 1)).toBe(false)
    expect(pairs(120, 400)).toBe(false)
    expect(pairs(400, 120)).toBe(false)      // either order
  })
  it('never pairs with a card that is not there', () => {
    expect(pairs(0, 300)).toBe(false)
    expect(pairs(300, undefined)).toBe(false)
    expect(pairs(NaN, NaN)).toBe(false)
  })
  it('estimates heights from what a card holds', () => {
    expect(bars(5)).toBe(H.card + 5 * H.bar)
    expect(bars(4, { foot: H.hint })).toBe(H.card + 4 * H.bar + H.hint)
    expect(reasons(3, { foot: H.foot })).toBe(H.card + 3 * H.reason + H.foot)
    expect(table(2, { row: H.row2, extra: 10 })).toBe(H.card + H.thead + 2 * H.row2 + 10)
    // the to-dos by kind (five rows and a control) beside the five that waited longest: one row
    expect(pairs(table(5, { foot: H.foot }), table(5, { row: H.entity }))).toBe(true)
    // one kind beside five long-waiting ones: each its own row
    expect(pairs(table(1), table(5, { row: H.entity }))).toBe(false)
    // bars of two channels beside eight directions: not side by side
    expect(pairs(bars(2), bars(8))).toBe(false)
  })
})

describe('standing', () => {
  const today = '2026-11-23'
  it('says a snoozed to-do is put off, until when', () => {
    expect(standing({ snoozed_until: '2026-11-25T09:00:00', due_at: '2026-11-20T10:00:00' }, today)).toEqual({ key: 'snoozed', tone: '', day: '2026-11-25' })
  })
  it('reads a date of its own before the posting\'s deadline', () => {
    expect(standing({ due_at: '2026-11-22T14:00:00', deadline: '2026-12-31' }, today)).toEqual({ key: 'datePassed', tone: 'bad', day: '2026-11-22' })
    expect(standing({ due_at: '2026-11-24T14:00:00' }, today)).toEqual({ key: 'on', tone: 'warn', day: '2026-11-24' })
    expect(standing({ due_at: '2026-11-30T14:00:00' }, today)).toEqual({ key: 'on', tone: '', day: '2026-11-30' })
  })
  it('falls back on the deadline of the posting it is about', () => {
    expect(standing({ deadline: '2026-11-20 23:59' }, today)).toEqual({ key: 'closed', tone: 'bad', day: '2026-11-20' })
    expect(standing({ deadline: '2026-11-23' }, today)).toEqual({ key: 'closes', tone: 'warn', day: '2026-11-23' })
    expect(standing({ deadline: '2026-11-26' }, today)).toEqual({ key: 'closes', tone: 'warn', day: '2026-11-26' })
    expect(standing({ deadline: '2026-12-15' }, today)).toEqual({ key: 'closes', tone: '', day: '2026-12-15' })
  })
  it('is simply open without a date, and ignores what is not a date', () => {
    expect(standing({}, today)).toEqual({ key: 'open', tone: '', day: '' })
    expect(standing({ deadline: 'rolling', due_at: null, snoozed_until: null }, today)).toEqual({ key: 'open', tone: '', day: '' })
  })
  it('takes today as a Date as well', () => {
    expect(standing({ deadline: '2026-11-22' }, new Date(2026, 10, 23, 23, 30))).toEqual({ key: 'closed', tone: 'bad', day: '2026-11-22' })
    expect(standing({ deadline: '2026-11-23' }, new Date(2026, 10, 23, 0, 5))).toEqual({ key: 'closes', tone: 'warn', day: '2026-11-23' })
  })
})
