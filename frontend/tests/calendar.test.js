// The calendar's model (src/calendar.js): where an item stands, what a crowded day shows, how the week's timed items sit
// side by side, the day's groups, the line above the calendar and the quick filters.
import { describe, expect, it } from 'vitest'
import { addMonths, at, dayGroups, iso, lanes, monthGrid, ownTime, plan, pressQuick, quickState, QUICK, rank, SHOWN, status, summary, timed } from '../src/calendar.js'

const now = new Date(2026, 10, 22, 12, 0)          // Sunday 22 November 2026, noon
let n = 0
const item = (kind, start, more = {}) => ({ id: `${kind}:${++n}`, kind, title: `${kind} ${n}`, start, all_day: false, done: false, state: '', score: null, priority: false,
  company: '', about: { todo_id: ['deadline', 'sent', 'reply', 'task'].includes(kind) ? null : n }, ...more })
const deadline = (day, more = {}) => item('deadline', `${day}T23:59`, { state: 'unapplied', ...more })

describe('days', () => {
  it('a month is whole weeks from the first day of the week, and holds every week of its days', () => {
    const [a, b] = monthGrid(new Date(2026, 10, 24), 1)          // weeks from Monday
    expect([iso(a), iso(b)]).toEqual(['2026-10-26', '2026-12-07'])
    const [c, d] = monthGrid(new Date(2026, 10, 24), 0)          // from Sunday
    expect([iso(c), iso(d)]).toEqual(['2026-11-01', '2026-12-06'])
  })
  it('a month later is the same day, or the last day of a shorter month', () => {
    expect(iso(addMonths(new Date(2026, 0, 31), 1))).toBe('2026-02-28')
    expect(iso(addMonths(new Date(2026, 10, 24), -1))).toBe('2026-10-24')
  })
  it("an item's moment is read from its parts, on the local clock", () => {
    const d = at({ start: '2026-11-24T10:30' })
    expect([d.getDate(), d.getHours(), d.getMinutes()]).toEqual([24, 10, 30])
    expect(at({ start: '2026-11-24' }).getHours()).toBe(0)
  })
  it('a deadline is never on the time grid, whatever its time; one that is not 23:59 keeps its own time', () => {
    expect(timed(deadline('2026-11-24'))).toBe(false)
    expect(timed(item('deadline', '2026-11-24T08:00'))).toBe(false)
    expect(ownTime(item('deadline', '2026-11-24T08:00'))).toBe(true)
    expect(ownTime(deadline('2026-11-24'))).toBe(false)
    expect(timed(item('interview', '2026-11-24T10:00'))).toBe(true)
    expect(timed(item('own', '2026-11-24T00:00', { all_day: true }))).toBe(false)
  })
})

describe('where an item stands', () => {
  it('is said apart from its kind', () => {
    expect(status(deadline('2026-11-24'), now)).toBe('open')
    expect(status(deadline('2026-11-21'), now)).toBe('closed')
    expect(status(deadline('2026-11-24', { state: 'sent' }), now)).toBe('applied')
    expect(status(item('interview', '2026-11-22T11:30'), now)).toBe('open')          // (it has begun; it is not over)
    expect(status(item('interview', '2026-11-21T10:00'), now)).toBe('past')
    expect(status(item('info_request', '2026-11-21T10:00'), now)).toBe('overdue')
    expect(status(item('own', '2026-11-22T00:00', { all_day: true }), now)).toBe('open')
    expect(status(item('own', '2026-11-20T09:00', { done: true }), now)).toBe('done')
    expect(status(item('sent', '2026-11-20T09:00'), now)).toBe('record')
  })
  it('orders a crowded day: interviews, then assessments and offers, then things to do, featured deadlines, the others', () => {
    const list = [deadline('2026-11-24'), deadline('2026-11-24', { score: 9 }), item('own', '2026-11-24T09:00'), item('assessment', '2026-11-24T09:00'),
      item('interview', '2026-11-24T15:00'), item('own', '2026-11-24T08:00', { done: true })]
    expect(list.map((x) => rank(x, now))).toEqual([4, 3, 2, 1, 0, 6])
  })
})

describe('a crowded day on the month grid', () => {
  const day = '2026-11-24'
  const many = Array.from({ length: 11 }, () => deadline(day))
  it('shows the interview and counts the deadlines as one line', () => {
    const iv = item('interview', `${day}T10:00`)
    const p = plan([...many, iv], 4, now)
    expect(p.top).toEqual([iv])
    expect(p.deadlines.length).toBe(11)
    expect(p.more).toBe(0)
  })
  it('gives a featured deadline a line of its own when there is room, and does not count it again', () => {
    const star = deadline(day, { priority: true })
    const p = plan([...many, star], 4, now)
    expect(p.top).toEqual([star])
    expect(p.deadlines.length).toBe(11)
    expect(plan([...many, star], 1, now)).toMatchObject({ top: [], more: 0 })       // (no room: it is counted with the others)
    expect(plan([...many, star], 1, now).deadlines.length).toBe(12)
  })
  it('says how many others did not fit, every item in exactly one place', () => {
    const others = [item('interview', `${day}T09:00`), item('assessment', `${day}T10:00`), item('own', `${day}T11:00`), item('contact', `${day}T12:00`, { all_day: true })]
    const p = plan([...others, ...many], 4, now)
    expect(p.top.length + p.rest.length + p.more).toBe(4)
    expect(p.top.length + (p.deadlines.length ? 1 : 0) + (p.more ? 1 : 0)).toBeLessThanOrEqual(4)
    expect(p.top.map((x) => x.kind)).toEqual(['interview', 'assessment'])
    expect(p.more).toBe(2)
  })
  it('short of room, keeps the interview on its line and counts the deadlines with the rest', () => {
    const iv = item('interview', `${day}T10:00`)
    const others = [iv, item('assessment', `${day}T10:30`), item('own', `${day}T14:00`), item('info_request', `${day}T00:00`, { all_day: true })]
    expect(plan([...others, ...many], 2, now)).toEqual({ top: [iv], deadlines: [], rest: [], more: 14 })
    expect(plan([...others, ...many], 3, now)).toMatchObject({ top: [iv], more: 3 })
    expect(plan([...others, ...many], 3, now).deadlines.length).toBe(11)
    expect(plan([...others, ...many], 1, now)).toEqual({ top: [], deadlines: [], rest: [], more: 15 })
    expect(plan([iv, ...many], 2, now)).toMatchObject({ top: [iv], more: 0 })                 // (room for both lines)
  })
  it('an empty day is empty', () => { expect(plan([], 3, now)).toEqual({ top: [], deadlines: [], rest: [], more: 0 }) })
})

describe("the week's time grid", () => {
  it('puts what meets side by side and what does not in one column', () => {
    const a = item('interview', '2026-11-24T10:00')
    const b = item('assessment', '2026-11-24T10:30')
    const c = item('own', '2026-11-24T14:00')
    const out = lanes([c, b, a], 60)
    const of = (x) => out.find((o) => o.item === x)
    expect([of(a).col, of(a).cols, of(b).col, of(b).cols]).toEqual([0, 2, 1, 2])
    expect([of(c).col, of(c).cols, of(c).top, of(c).height]).toEqual([0, 1, 840, 60])
  })
  it('keeps an item late in the day inside it', () => {
    const [o] = lanes([item('own', '2026-11-24T23:40')], 60)
    expect(o.top + o.height).toBe(1440)
  })
})

describe("the day's agenda", () => {
  it('puts each item in one group: timed, deadlines (to act on first), other things to do, done and past', () => {
    const iv = item('interview', '2026-11-22T15:00')
    const dl1 = deadline('2026-11-22', { score: 5 })
    const dl2 = deadline('2026-11-22', { state: 'sent', score: 9 })
    const dl3 = deadline('2026-11-22', { score: 8 })
    const own = item('own', '2026-11-22T00:00', { all_day: true })
    const done = item('own', '2026-11-22T09:00', { done: true })
    const g = dayGroups([dl1, dl2, own, iv, done, dl3], now)
    expect(g).toEqual({ timed: [iv], deadlines: [dl3, dl1, dl2], other: [own], past: [done] })
  })
})

describe('the line above the calendar', () => {
  it('counts deadlines to act on today and in the next 7 days (today included), interviews to come, and what is late', () => {
    const list = [deadline('2026-11-22'), deadline('2026-11-22', { state: 'sent' }), deadline('2026-11-28'), deadline('2026-11-29'), deadline('2026-11-21'),
      item('interview', '2026-11-24T10:00'), item('interview', '2026-11-20T10:00'), item('info_request', '2026-11-21T10:00'), item('offer', '2026-11-25T10:00')]
    const s = summary(list, now)
    expect([s.today, s.week, s.interviews, s.overdue.length]).toEqual([1, 2, 1, 1])
    expect(s.next.start).toBe('2026-11-24T10:00')
  })
})

describe('the quick filters', () => {
  const todo = QUICK.find((q) => q.id === 'todo')
  const iv = QUICK.find((q) => q.id === 'interview')
  it('from everything, show only the one pressed; then add and take away; nothing left is everything again', () => {
    let k = [...SHOWN, 'sent']
    k = pressQuick(k, iv)
    expect(k).toEqual(['interview', 'sent'])
    k = pressQuick(k, todo)
    expect(quickState(k, todo)).toBe('on')
    k = pressQuick(k, todo)
    expect(k).toEqual(['interview', 'sent'])
    k = pressQuick(k, iv)
    expect(k).toEqual([...SHOWN, 'sent'])
  })
  it('say when only some of their kinds are on (chosen one by one in the full filter)', () => {
    expect(quickState(['deadline', 'own'], todo)).toBe('some')
  })
})
