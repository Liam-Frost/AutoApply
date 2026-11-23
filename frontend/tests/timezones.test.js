// The time zones of the TimeZonePicker (src/timezones.js), from made-up server lists: what each is called in the
// interface language, where it is listed, what finds it (a city in English or Chinese, a country, an IANA id, an
// offset), an old spelling, a saved value that is not a zone, and offsets that are the server's - never the browser's.
import { afterEach, describe, expect, it } from 'vitest'
import { i18n, t } from '../src/i18n/catalog.js'
import { prepare, search } from '../src/combobox.js'
import { COMMON, buildOptions, cityOf, formatOffset, groupOf, isValidZone, offsetWords, readRecent, rememberZone } from '../src/timezones.js'

const ZONES = [
  { id: 'America/Vancouver', offset: -420, country: 'CA' },
  { id: 'America/Los_Angeles', offset: -480, country: 'US' },
  { id: 'US/Pacific', offset: -480, alias_of: 'America/Los_Angeles', country: 'US' },
  { id: 'America/St_Johns', offset: -210, country: 'CA' },
  { id: 'America/Argentina/Buenos_Aires', offset: -180, country: 'AR' },
  { id: 'America/Indiana/Knox', offset: -360, country: 'US' },
  { id: 'America/Bogota', offset: -300, country: 'CO' },
  { id: 'Europe/Paris', offset: 60, country: 'FR' },
  { id: 'Asia/Kolkata', offset: 330, country: 'IN' },
  { id: 'Asia/Calcutta', offset: 330, alias_of: 'Asia/Kolkata', country: 'IN' },
  { id: 'Asia/Kathmandu', offset: 345, country: 'NP' },
  { id: 'Asia/Shanghai', offset: 480, country: 'CN' },
  { id: 'Asia/Hong_Kong', offset: 480, country: 'HK' },
  { id: 'Indian/Maldives', offset: 300, country: 'MV' },
  { id: 'Atlantic/Azores', offset: -60, country: 'PT' },
  { id: 'Africa/Accra', offset: 0, country: 'GH' },
  { id: 'Pacific/Auckland', offset: 780, country: 'NZ' },
  { id: 'Antarctica/Troll', offset: 0, country: 'AQ' },
  { id: 'Etc/UTC', offset: 0 },
  { id: 'Etc/GMT+5', offset: -300 },
  { id: 'CET', offset: 60 },
]
const DATA = { system: 'America/Vancouver', chosen: '', chosen_valid: true, zones: ZONES }

afterEach(() => { i18n.global.locale.value = 'zh'; localStorage.clear() })
function build(lang = 'en', more = {}, data = DATA) {
  i18n.global.locale.value = lang
  return buildOptions(data, { t, locale: lang === 'zh' ? 'zh-CN' : lang, ...more })
}
const opt = (b, id, group) => b.options.find((o) => o.value === id && (!group || o.group === group))
const found = (b, q) => search(prepare(b.options), b.groups, q).items.map((o) => o.value)

describe('an offset', () => {
  it('is written UTC±hh:mm with a real minus sign, half and quarter hours too', () => {
    expect([-420, -480, 330, 345, -210, 0, 780, -60].map(formatOffset)).toEqual(
      ['UTC−07:00', 'UTC−08:00', 'UTC+05:30', 'UTC+05:45', 'UTC−03:30', 'UTC+00:00', 'UTC+13:00', 'UTC−01:00'])
  })
  it('can be typed in the usual ways', () => {
    expect(offsetWords(-420)).toEqual(expect.arrayContaining(['utc-7', 'utc-07', 'utc-07:00', 'gmt-7', '-7', '-07:00']))
    expect(offsetWords(330)).toEqual(expect.arrayContaining(['utc+5:30', 'utc+05:30', '+5:30', '+0530', 'gmt+05:30']))
    expect(offsetWords(0)).toEqual(expect.arrayContaining(['utc', 'gmt', 'utc+0', '+00:00']))
  })
})

describe('the list', () => {
  it('starts with "follow this computer", with the computer zone and its offset from the server', () => {
    const b = build()
    expect(b.options[0]).toMatchObject({ value: '', label: 'Follow this computer', hint: 'UTC−07:00 · America/Vancouver' })
    const unknown = build('en', {}, { ...DATA, system: '' })
    expect(unknown.options[0]).toMatchObject({ value: '', hint: '' })
  })
  it('has the headings in their order: common, the regions, other names', () => {
    expect(build().groups.map((g) => g.id)).toEqual(['common', 'americas', 'europe', 'asia', 'africa', 'pacific', 'atlantic', 'indian', 'polar', 'other'])
    expect(build().groups[0].label).toBe('Common')
    expect(build('zh').groups.map((g) => g.label).slice(0, 3)).toEqual(['常用', '美洲', '欧洲'])
  })
  it('lists a zone under its region by the first part of its id; fixed offsets, old spellings and names of no place under other names', () => {
    const g = (id) => groupOf(ZONES.find((z) => z.id === id))
    expect(['America/Vancouver', 'Europe/Paris', 'Asia/Kolkata', 'Africa/Accra', 'Pacific/Auckland', 'Atlantic/Azores', 'Indian/Maldives', 'Antarctica/Troll'].map(g))
      .toEqual(['americas', 'europe', 'asia', 'africa', 'pacific', 'atlantic', 'indian', 'polar'])
    expect(['US/Pacific', 'Asia/Calcutta', 'Etc/UTC', 'Etc/GMT+5', 'CET'].map(g)).toEqual(['other', 'other', 'other', 'other', 'other'])
  })
  it('has under Common the computer zone, then the ones chosen lately, then the usual ones the server knows', () => {
    rememberZone('Europe/Paris')
    rememberZone('Asia/Kathmandu')
    expect(readRecent()).toEqual(['Asia/Kathmandu', 'Europe/Paris'])
    const common = build('en', { recent: readRecent() }).options.filter((o) => o.group === 'common').map((o) => o.value)
    expect(common).toEqual(['America/Vancouver', 'Asia/Kathmandu', 'Europe/Paris', ...COMMON.filter((id) => ZONES.some((z) => z.id === id) && !['America/Vancouver', 'Europe/Paris'].includes(id))])
    expect(common.filter((v) => v === 'America/Vancouver')).toHaveLength(1)
  })
  it('sorts a region by offset, then by name', () => {
    const am = build().options.filter((o) => o.group === 'americas').map((o) => o.value)
    expect(am).toEqual(['America/Los_Angeles', 'America/Vancouver', 'America/Indiana/Knox', 'America/Bogota', 'America/St_Johns', 'America/Argentina/Buenos_Aires'])
  })
})

describe('a zone', () => {
  it('is called by its city and country in the interface language, its offset and id beside it', () => {
    expect(opt(build(), 'America/Vancouver', 'americas')).toMatchObject({ label: 'Vancouver, Canada', hint: 'UTC−07:00 · America/Vancouver' })
    expect(opt(build('zh'), 'America/Vancouver', 'americas').label).toBe('温哥华（加拿大）')
    expect(opt(build('zh'), 'Asia/Kolkata', 'asia')).toMatchObject({ label: '加尔各答（印度）', hint: 'UTC+05:30 · Asia/Kolkata' })
    expect(opt(build('fr'), 'Europe/Paris', 'europe').label).toBe('Paris, France')
    expect(opt(build(), 'America/Argentina/Buenos_Aires').label).toBe('Buenos Aires, Argentina')
    expect(opt(build(), 'America/Indiana/Knox').label).toBe('Knox (Indiana), United States')
    expect(opt(build(), 'Asia/Kathmandu').label).toBe('Kathmandu, Nepal')                // (no name in the catalog: the id's)
    expect(opt(build(), 'Asia/Hong_Kong', 'asia').label).toBe('Hong Kong')                // (a city that is its country once)
    expect(opt(build('zh'), 'Asia/Hong_Kong', 'asia').label).toBe('香港')
  })
  it('of fixed offset, or UTC, says so', () => {
    expect(opt(build(), 'Etc/UTC', 'other')).toMatchObject({ label: 'Coordinated Universal Time', hint: 'UTC+00:00 · Etc/UTC' })
    expect(opt(build(), 'Etc/GMT+5')).toMatchObject({ label: 'Fixed offset UTC−05:00', hint: 'UTC−05:00 · Etc/GMT+5' })
    expect(opt(build(), 'CET')).toMatchObject({ label: 'CET', hint: 'UTC+01:00 · CET' })
  })
  it('of an old spelling is shown as written, with what it stands for', () => {
    expect(opt(build(), 'US/Pacific')).toMatchObject({ label: 'US/Pacific', hint: 'UTC−08:00 · same as America/Los_Angeles', group: 'other' })
    expect(opt(build('zh'), 'Asia/Calcutta').hint).toBe('UTC+05:30 · 同 Asia/Kolkata')
    expect(isValidZone('US/Pacific', { ...DATA, chosen: 'US/Pacific' })).toBe(true)
  })
})

describe('a search', () => {
  it('finds a city in English and in Chinese, also a city of the zone that is not its name', () => {
    expect(found(build(), 'vancouver')).toEqual(['', 'America/Vancouver'])      // (and "follow this computer", which is Vancouver here)
    expect(found(build('zh'), '温哥华')).toEqual(['America/Vancouver'])
    expect(found(build('zh'), 'vancouver')).toEqual(['', 'America/Vancouver'])   // English in the Chinese interface
    expect(found(build('zh'), '北京')).toEqual(['Asia/Shanghai'])
    expect(found(build(), 'beijing')).toEqual(['Asia/Shanghai'])
    expect(found(build(), 'seattle')).toEqual(['America/Los_Angeles'])
    expect(found(build(), 'bogota')).toEqual(['America/Bogota'])                // (Bogotá: accents do not matter)
  })
  it('finds a country in either language, and an IANA id', () => {
    expect(found(build(), 'canada')).toEqual(['America/Vancouver', 'America/St_Johns'])
    expect(found(build('zh'), '加拿大')).toEqual(['America/Vancouver', 'America/St_Johns'])
    expect(found(build(), 'America/Los_Angeles')).toEqual(['America/Los_Angeles', 'US/Pacific'])
    expect(found(build(), 'calcutta')).toEqual(['Asia/Calcutta'])
    expect(found(build(), 'Etc/GMT+5')).toEqual(['Etc/GMT+5'])
  })
  it('finds an offset however it is typed, exact ones first', () => {
    expect(found(build(), 'UTC-7')).toEqual(['', 'America/Vancouver'])
    expect(found(build(), 'utc -7')).toEqual(['', 'America/Vancouver'])
    expect(found(build(), 'UTC−07:00')).toEqual(['', 'America/Vancouver'])
    expect(found(build(), '-8')).toEqual(['America/Los_Angeles', 'US/Pacific'])
    expect(found(build(), '+05:30')).toEqual(['Asia/Kolkata', 'Asia/Calcutta'])
    expect(found(build(), '+0530')).toEqual(['Asia/Kolkata', 'Asia/Calcutta'])
    // (by heading; the id of Etc/GMT+5 has "+5" in it, last - its label says what it is: UTC−05:00)
    expect(found(build(), '+5')).toEqual(['Asia/Kolkata', 'Asia/Kathmandu', 'Indian/Maldives', 'Asia/Calcutta', 'Etc/GMT+5'])
    expect(found(build(), '+08')).toEqual(['Asia/Shanghai', 'Asia/Hong_Kong'])
    expect(found(build(), '-3:30')).toEqual(['America/St_Johns'])
  })
  it('finds the generic name of a zone where the browser has one', () => {
    const b = build('en', { generic: new Map([['America/Los_Angeles', ['Pacific Time']], ['America/Vancouver', ['Pacific Time']]]) })
    expect(found(b, 'pacific time')).toEqual(['America/Vancouver', 'America/Los_Angeles'])
  })
})

describe('offsets', () => {
  it('are the server’s: British Columbia at UTC-7 all year, Los Angeles at -8 in winter and -7 in summer', () => {
    const winter = build('en', {}, { ...DATA, zones: [{ id: 'America/Vancouver', offset: -420, country: 'CA' }, { id: 'America/Los_Angeles', offset: -480, country: 'US' }] })
    const summer = build('en', {}, { ...DATA, zones: [{ id: 'America/Vancouver', offset: -420, country: 'CA' }, { id: 'America/Los_Angeles', offset: -420, country: 'US' }] })
    expect([opt(winter, 'America/Vancouver', 'americas').hint, opt(winter, 'America/Los_Angeles', 'americas').hint]).toEqual(['UTC−07:00 · America/Vancouver', 'UTC−08:00 · America/Los_Angeles'])
    expect(opt(summer, 'America/Los_Angeles', 'americas').hint).toBe('UTC−07:00 · America/Los_Angeles')
    expect(found(winter, 'utc-8')).toEqual(['America/Los_Angeles'])
    expect(found(summer, 'utc-8')).toEqual([])
    expect(found(summer, 'utc-7')).toEqual(['', 'America/Vancouver', 'America/Los_Angeles'])
    // whatever the server says is what is shown - an offset is never worked out in the browser, whose rules may be old
    const old = build('en', {}, { ...DATA, zones: [{ id: 'America/Vancouver', offset: -480, country: 'CA' }] })
    expect(opt(old, 'America/Vancouver', 'americas').hint).toBe('UTC−08:00 · America/Vancouver')
  })
})

describe('a saved value', () => {
  it('that is not a zone is not valid - unless the server read it as one; nothing and a listed zone are', () => {
    expect(isValidZone('', DATA)).toBe(true)
    expect(isValidZone('Asia/Kolkata', DATA)).toBe(true)
    expect(isValidZone('Mars/Olympus', { ...DATA, chosen: 'Mars/Olympus', chosen_valid: false })).toBe(false)
    expect(isValidZone('Vancouver time', DATA)).toBe(false)
    expect(isValidZone('Factory', { ...DATA, chosen: 'Factory', chosen_valid: true })).toBe(true)
    expect(isValidZone('Mars/Olympus', null)).toBe(true)          // (not known yet: nothing is said)
  })
  it('that is not a zone is in no option: the field shows it as itself', () => {
    expect(build().options.some((o) => o.value === 'Mars/Olympus')).toBe(false)
  })
})

describe('the city of an id', () => {
  it('is its last part with spaces, with the state where it is not the country', () => {
    expect(cityOf('America/Los_Angeles', 'United States')).toBe('Los Angeles')
    expect(cityOf('America/Argentina/Buenos_Aires', 'Argentina')).toBe('Buenos Aires')
    expect(cityOf('America/North_Dakota/New_Salem', 'United States')).toBe('New Salem (North Dakota)')
  })
})
