// A deadline as a day and as words; what stays ticked when the list changes (src/dates.js).
import { describe, expect, it } from 'vitest'
import { daysUntil, deadlineLabel, isPast, keepVisible, parseDeadline } from '../src/dates.js'

const at = (h, m = 0, day = 18) => new Date(2026, 10, day, h, m)      // 18 November 2026, local time

describe('a deadline', () => {
  it('is read as it is written, in local time; a day without a time ends at 23:59', () => {
    expect(parseDeadline('2026-11-18 23:59').getHours()).toBe(23)
    expect(parseDeadline('2026-11-18T09:30').getMinutes()).toBe(30)
    const day = parseDeadline('2026-11-18')
    expect([day.getHours(), day.getMinutes()]).toEqual([23, 59])
    expect(parseDeadline('')).toBeNull()
    expect(parseDeadline('rolling')).toBeNull()
    expect(parseDeadline(null)).toBeNull()
  })
  it('later the same day is today - with the time', () => {
    // the case from the audit: noon, due 23:59 the same day. A rounded-up count of 24-hour spans says "tomorrow".
    expect(deadlineLabel('2026-11-18 23:59', at(12))).toEqual({ text: '今天 23:59 截止', tone: 'soon' })
    expect(deadlineLabel('2026-11-18 17:00', at(8))).toEqual({ text: '今天 17:00 截止', tone: 'soon' })
    expect(daysUntil('2026-11-18 23:59', at(0, 1))).toBe(0)
  })
  it('tomorrow is tomorrow, however few hours away', () => {
    expect(deadlineLabel('2026-11-19 00:05', at(23, 55)).text).toBe('明天截止')        // ten minutes from now, on the next day
    expect(deadlineLabel('2026-11-19 23:59', at(0, 1)).text).toBe('明天截止')          // almost two days of hours, one midnight
    expect(daysUntil('2026-11-19', at(12))).toBe(1)
  })
  it('just after midnight the day has changed', () => {
    expect(deadlineLabel('2026-11-18 23:59', at(0, 1, 19))).toEqual({ text: '已截止', tone: 'past' })
    expect(deadlineLabel('2026-11-19 09:00', at(0, 1, 19)).text).toBe('今天 09:00 截止')
  })
  it('what is over is over - also earlier today', () => {
    expect(deadlineLabel('2026-11-18 09:00', at(12))).toEqual({ text: '已截止', tone: 'past' })     // it used to be "due today"
    expect(isPast('2026-11-18 09:00', at(12))).toBe(true)
    expect(isPast('2026-11-18', at(12))).toBe(false)             // a day without a time: until the end of that day
    expect(isPast('2026-11-17', at(12))).toBe(true)
    expect(daysUntil('2026-11-17', at(12))).toBe(-1)
  })
  it('counts days by the calendar', () => {
    expect(deadlineLabel('2026-11-21', at(12))).toEqual({ text: '还有 3 天', tone: '' })
    expect(daysUntil('2026-12-01', at(12))).toBe(13)
    expect(daysUntil('2027-01-01 08:00', new Date(2026, 11, 31, 23, 0))).toBe(1)         // across a year
    // across the day the clocks change, a day is still a day (a difference in hours that is not a multiple of 24)
    expect(daysUntil('2026-03-09', new Date(2026, 2, 8, 12))).toBe(1)
    expect(daysUntil('2026-11-02', new Date(2026, 10, 1, 12))).toBe(1)
  })
  it('says nothing for no deadline', () => {
    expect(deadlineLabel('', at(12))).toEqual({ text: '', tone: '' })
    expect(daysUntil('', at(12))).toBeNull()
    expect(isPast('', at(12))).toBe(false)
  })
})

describe('what is ticked', () => {
  it('is among what is shown', () => {
    const picked = new Set([1, 2, 3])
    expect([...keepVisible(picked, [{ id: 2 }, { id: 3 }, { id: 9 }])]).toEqual([2, 3])
    expect(keepVisible(picked, []).size).toBe(0)
  })
  it('is left alone when nothing was hidden', () => {
    const picked = new Set([1, 2])
    expect(keepVisible(picked, [{ id: 1 }, { id: 2 }, { id: 3 }])).toBe(picked)      // the same set: nothing to re-render
  })
})
