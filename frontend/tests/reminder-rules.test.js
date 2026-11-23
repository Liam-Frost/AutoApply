// The reminders of a kind of calendar item as the settings keep them (src/reminders.js): minutes before the item, whole,
// each once, the largest first - what the backend keeps (alarms.py, put_settings: 0 to sixty days) - and what one of
// them is called ("1 day before", "At the start", the morning of a whole-day item).
import { afterEach, describe, expect, it } from 'vitest'
import { i18n } from '../src/i18n/catalog.js'
import { DAY, MOST, PRESETS, UNITS, WEEK, formatReminder, has, normalize, parseAmount, presetsFor, toggled, withAdded, without } from '../src/reminders.js'

afterEach(() => { i18n.global.locale.value = 'zh' })
const inEnglish = () => { i18n.global.locale.value = 'en' }

describe('a list of reminders', () => {
  it('is whole minutes, each once, the largest first; what is not a reminder is dropped', () => {
    expect(normalize([30, 1440, 30, '60', 2.4, -5, MOST + 1, null, '', 'x', true, NaN])).toEqual([1440, 60, 30, 2])
    expect(normalize([0, MOST])).toEqual([MOST, 0])
    expect(normalize([])).toEqual([])
    expect(normalize(undefined)).toEqual([])
    expect(normalize('1440, 30')).toEqual([])          // (the old text field's form is not a list)
  })
  it('takes one more, gives one up, and a preset pressed again takes it away', () => {
    expect(withAdded([30], 1440)).toEqual([1440, 30])
    expect(withAdded([1440, 30], 30)).toEqual([1440, 30])
    expect(withAdded([], 0)).toEqual([0])
    expect(without([1440, 30], 30)).toEqual([1440])
    expect(without([1440], 30)).toEqual([1440])
    expect(toggled([1440], 30)).toEqual([1440, 30])
    expect(toggled([1440, 30], 1440)).toEqual([30])
    expect(has([1440, '30'], 30)).toBe(true)
  })
  it('the presets are the start, minutes, hours, days and a week - for a whole-day item only whole days', () => {
    expect(PRESETS).toEqual([0, 15, 30, 60, 120, DAY, 2 * DAY, WEEK])
    expect(presetsFor(true)).toEqual([0, DAY, 2 * DAY, WEEK])
    expect(presetsFor(false)).toBe(PRESETS)
  })
})

describe('an amount typed into the "+"', () => {
  it('is turned into minutes by its unit', () => {
    expect(UNITS).toEqual({ minutes: 1, hours: 60, days: 1440 })
    expect(parseAmount('45', 'minutes')).toEqual({ minutes: 45 })
    expect(parseAmount(' 2 ', 'hours')).toEqual({ minutes: 120 })
    expect(parseAmount('3', 'days')).toEqual({ minutes: 4320 })
    expect(parseAmount('0', 'hours')).toEqual({ minutes: 0 })
  })
  it('says why it cannot be one: not a whole number, below zero, further than sixty days, there already', () => {
    expect(parseAmount('', 'minutes')).toEqual({ empty: true })
    expect(parseAmount('1.5', 'hours')).toEqual({ error: 'notWhole' })
    expect(parseAmount('1,5', 'hours')).toEqual({ error: 'notWhole' })
    expect(parseAmount('abc', 'minutes')).toEqual({ error: 'notWhole' })
    expect(parseAmount('1e3', 'minutes')).toEqual({ error: 'notWhole' })
    expect(parseAmount('-3', 'days')).toEqual({ error: 'negative' })
    expect(parseAmount('-1.5', 'days')).toEqual({ error: 'negative' })
    expect(parseAmount('60', 'days')).toEqual({ minutes: MOST })
    expect(parseAmount('61', 'days')).toEqual({ error: 'tooFar' })
    expect(parseAmount('1441', 'hours')).toEqual({ error: 'tooFar' })
    expect(parseAmount('86401', 'minutes')).toEqual({ error: 'tooFar' })
    expect(parseAmount('30', 'minutes', [1440, 30])).toEqual({ error: 'duplicate', minutes: 30 })
    expect(parseAmount('1', 'days', [1440])).toEqual({ error: 'duplicate', minutes: 1440 })
    expect(MOST).toBe(86400)
  })
})

describe('a reminder in words', () => {
  it('in whole weeks, days, hours, else minutes; 0 is the start', () => {
    inEnglish()
    expect([0, 15, 30, 60, 90, 120, 1440, 1500, 2880, WEEK, 2 * WEEK, 10 * DAY].map((m) => formatReminder(m))).toEqual([
      'At the start', '15 minutes before', '30 minutes before', '1 hour before', '90 minutes before', '2 hours before', '1 day before',
      '25 hours before', '2 days before', '1 week before', '2 weeks before', '10 days before'])
  })
  it('for an item of a whole day: its morning, or whole days before (part of a day is the morning before)', () => {
    inEnglish()
    expect([0, 30, 120, 1440, 1441, 2880, WEEK].map((m) => formatReminder(m, { allDay: true }))).toEqual([
      'Morning of the day', '1 day before', '1 day before', '1 day before', '2 days before', '2 days before', '1 week before'])
  })
  it('in the interface language', () => {
    i18n.global.locale.value = 'zh'
    expect([0, 30, 60, 1440, WEEK].map((m) => formatReminder(m))).toEqual(['开始时', '30 分钟前', '1 小时前', '1 天前', '1 周前'])
    expect(formatReminder(0, { allDay: true })).toBe('当天早上')
  })
})
