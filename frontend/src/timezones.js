// The time zones of the TimeZonePicker (components/TimeZonePicker.vue): what each is called in the interface language,
// under which heading it is listed, and what it can be found by. Built from the server's list (GET /api/time/zones),
// which also gives every zone's offset from UTC now from the program's own rules - the browser's may be old (British
// Columbia has kept UTC-7 all year since 2026), so no offset is worked out here, and none is taken from Intl.
import en from './locales/en.json'

// a short list of widely used zones, under "Common" after the computer's own and the ones chosen lately
export const COMMON = ['America/Vancouver', 'America/Los_Angeles', 'America/Denver', 'America/Chicago', 'America/Toronto', 'America/New_York',
  'Europe/London', 'Europe/Paris', 'Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Tokyo', 'Asia/Singapore', 'Asia/Kolkata', 'Australia/Sydney', 'Etc/UTC']

// Cities with a name of their own in the catalog (tz.city.<key>): the zone's label in every language.
export const CITIES = {
  'America/Vancouver': 'vancouver', 'America/Los_Angeles': 'losAngeles', 'America/Edmonton': 'edmonton', 'America/Denver': 'denver',
  'America/Phoenix': 'phoenix', 'America/Chicago': 'chicago', 'America/Winnipeg': 'winnipeg', 'America/Toronto': 'toronto',
  'America/New_York': 'newYork', 'America/Halifax': 'halifax', 'America/St_Johns': 'stJohns', 'America/Anchorage': 'anchorage',
  'Pacific/Honolulu': 'honolulu', 'America/Mexico_City': 'mexicoCity', 'America/Sao_Paulo': 'saoPaulo',
  'America/Argentina/Buenos_Aires': 'buenosAires', 'America/Bogota': 'bogota', 'America/Lima': 'lima', 'America/Santiago': 'santiago',
  'Europe/London': 'london', 'Europe/Dublin': 'dublin', 'Europe/Lisbon': 'lisbon', 'Europe/Paris': 'paris', 'Europe/Berlin': 'berlin',
  'Europe/Madrid': 'madrid', 'Europe/Rome': 'rome', 'Europe/Amsterdam': 'amsterdam', 'Europe/Zurich': 'zurich',
  'Europe/Stockholm': 'stockholm', 'Europe/Moscow': 'moscow', 'Europe/Istanbul': 'istanbul', 'Africa/Cairo': 'cairo',
  'Africa/Johannesburg': 'johannesburg', 'Africa/Lagos': 'lagos', 'Africa/Nairobi': 'nairobi', 'Asia/Dubai': 'dubai',
  'Asia/Kolkata': 'kolkata', 'Asia/Karachi': 'karachi', 'Asia/Dhaka': 'dhaka', 'Asia/Bangkok': 'bangkok',
  'Asia/Ho_Chi_Minh': 'hoChiMinh', 'Asia/Jakarta': 'jakarta', 'Asia/Singapore': 'singapore', 'Asia/Kuala_Lumpur': 'kualaLumpur',
  'Asia/Manila': 'manila', 'Asia/Shanghai': 'shanghai', 'Asia/Urumqi': 'urumqi', 'Asia/Hong_Kong': 'hongKong', 'Asia/Taipei': 'taipei',
  'Asia/Macau': 'macau', 'Asia/Tokyo': 'tokyo', 'Asia/Seoul': 'seoul', 'Australia/Perth': 'perth', 'Australia/Adelaide': 'adelaide',
  'Australia/Brisbane': 'brisbane', 'Australia/Sydney': 'sydney', 'Australia/Melbourne': 'melbourne', 'Pacific/Auckland': 'auckland',
}
// Other places on a zone's clock (tz.city.<key>): found by a search in English and in the interface language.
export const ALSO = {
  'Asia/Shanghai': ['beijing', 'shenzhen', 'guangzhou'], 'America/Los_Angeles': ['seattle', 'sanFrancisco'],
  'America/Vancouver': ['victoria', 'surrey'], 'America/Edmonton': ['calgary'], 'America/Toronto': ['montreal', 'ottawa'],
  'America/New_York': ['boston', 'washington'], 'Asia/Kolkata': ['mumbai', 'newDelhi', 'bangalore'],
}

// The headings, in this order: the first part of an id says the region; a fixed offset (Etc/…), an old spelling
// (US/Pacific) and a name of no place (CET, EST5EDT) are "Other names".
export const GROUPS = ['common', 'americas', 'europe', 'asia', 'africa', 'pacific', 'atlantic', 'indian', 'polar', 'other']
const REGION = { America: 'americas', Europe: 'europe', Asia: 'asia', Africa: 'africa', Australia: 'pacific', Pacific: 'pacific',
  Atlantic: 'atlantic', Indian: 'indian', Antarctica: 'polar', Arctic: 'polar' }
export function groupOf(z) {
  if (z.alias_of || !z.id.includes('/') || z.id.startsWith('Etc/')) return 'other'
  return REGION[z.id.split('/')[0]] || 'other'
}

// "UTC−07:00", "UTC+05:30", "UTC+00:00" (the minus sign, not a hyphen) from minutes east of UTC.
const two = (n) => String(n).padStart(2, '0')
export function formatOffset(min) {
  const v = Math.round(Number(min) || 0)
  const a = Math.abs(v)
  return 'UTC' + (v < 0 ? '−' : '+') + two(Math.floor(a / 60)) + ':' + two(a % 60)
}
// The ways an offset is typed into a search: "UTC-7", "utc-07", "GMT-7", "-7", "-07:00", "+5:30", "+0530".
export function offsetWords(min) {
  const v = Math.round(Number(min) || 0)
  const a = Math.abs(v), sg = v < 0 ? '-' : '+', h = Math.floor(a / 60), m = a % 60
  const hm = m ? [`${h}:${two(m)}`, `${two(h)}:${two(m)}`, `${two(h)}${two(m)}`] : [String(h), two(h), `${two(h)}:00`]
  const out = []
  for (const x of hm) out.push('utc' + sg + x, 'gmt' + sg + x, sg + x)
  if (!v) out.push('utc', 'gmt')
  return out
}

// The place in the id: its last part with spaces ("Buenos Aires"), and the part before it where that is a state and
// not the country ("Knox (Indiana)").
export function cityOf(id, countryEn = '') {
  const parts = id.split('/')
  const last = parts[parts.length - 1].replace(/_/g, ' ')
  const mid = parts.length > 2 ? parts[1].replace(/_/g, ' ') : ''
  return mid && mid.toLowerCase() !== countryEn.toLowerCase() ? `${last} (${mid})` : last
}

// The English of a catalog key (a search in English finds a city whatever the interface language is).
export function english(key) {
  let v = en
  for (const p of key.split('.')) v = v && typeof v === 'object' ? v[p] : undefined
  return typeof v === 'string' ? v : ''
}

// The names of a country (ISO code) in a language: the short one where it is a name ("Hong Kong", 香港), the long one
// where the short is an abbreviation ("United States", not "US"). [shown, every name] - both are searched.
const regionCache = new Map()
export function countryNames(code, locale) {
  if (!code) return ['', []]
  const k = locale + ':' + code
  if (!regionCache.has(k)) {
    let long = '', short = ''
    try { long = new Intl.DisplayNames([locale], { type: 'region' }).of(code) || '' } catch (e) { /* no such names here */ }
    try { short = new Intl.DisplayNames([locale], { type: 'region', style: 'short' }).of(code) || '' } catch (e) { /* idem */ }
    if (long === code) long = ''
    if (short === code) short = ''
    const shown = short && !/^[A-Z.]{1,4}$/.test(short) ? short : long || short
    regionCache.set(k, [shown, [...new Set([long, short].filter(Boolean))]])
  }
  return regionCache.get(k)
}

// The generic names of a zone ("Pacific Time", 北美太平洋时间) in the given languages, for the search only. Never an
// offset: Intl writes "GMT-08:00" where it has no name, and its offsets may be old.
export function genericNames(id, locales) {
  const out = []
  for (const l of locales) {
    try {
      const part = new Intl.DateTimeFormat(l, { timeZone: id, timeZoneName: 'longGeneric' }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName')
      if (part && !/^(GMT|UTC)([+\-−]|$)/.test(part.value) && !out.includes(part.value)) out.push(part.value)
    } catch (e) { /* a zone this browser does not know: its other words still find it */ }
  }
  return out
}

// The zones chosen lately in this browser (a convenience for this viewer only; a private window has none).
const RECENT = 'aa.tz.recent'
export function readRecent() {
  try { const v = JSON.parse(localStorage.getItem(RECENT) || '[]'); return Array.isArray(v) ? v.filter((x) => typeof x === 'string').slice(0, 5) : [] } catch (e) { return [] }
}
export function rememberZone(id) {
  const now = [id, ...readRecent().filter((x) => x !== id)].slice(0, 5)
  try { if (id) localStorage.setItem(RECENT, JSON.stringify(now)) } catch (e) { /* not kept: nothing else depends on it */ }
  return id ? now : readRecent()
}

// One option of the picker for a zone of the server's list.
//   ctx: { t, locale (an Intl tag: "zh-CN"), generic?: Map id -> names }
export function optionOf(z, group, ctx) {
  const { t, locale } = ctx
  const off = formatOffset(z.offset)
  const words = offsetWords(z.offset)
  const id = z.id
  let label, hint = `${off} · ${id}`
  if (z.alias_of) {
    label = id                                                   // an old spelling is a name, shown as it is written
    hint = `${off} · ${t('tz.sameAs', { zone: z.alias_of })}`
    words.push(z.alias_of, ...z.alias_of.split('/'))
  } else if (id.startsWith('Etc/')) {
    label = z.offset ? t('tz.fixed', { offset: off }) : t('tz.utc')
  } else if (group === 'other') {
    label = id
  }
  const [countryEn, countryEnAll] = countryNames(z.country, 'en')
  const [country, countryAll] = countryNames(z.country, locale)
  const key = CITIES[id]
  const cityEn = key ? english('tz.city.' + key) : cityOf(id, countryEn)
  const city = key ? t('tz.city.' + key) : cityEn
  if (!label) {
    const fold = (s) => s.toLowerCase().replace(/\s+/g, '')
    label = country && fold(country) !== fold(city) ? t('tz.place', { city, country }) : city
  }
  const also = (ALSO[id] || []).flatMap((k) => [english('tz.city.' + k), t('tz.city.' + k)])
  const generic = (ctx.generic && ctx.generic.get(id)) || []
  const keywords = [...new Set([cityEn, city, ...also, ...countryEnAll, ...countryAll, ...generic, ...words].filter(Boolean))]
  return { value: id, label, hint, group, keywords, offset: z.offset }
}

// Every option of the picker, and its headings. `data`: what GET /api/time/zones gave ({ system, zones }).
//   ctx: { t, locale, recent?: [ids], generic?: Map }
// First "Follow this computer" ('' - the setting left empty), with the computer's zone and its offset; then Common
// (the computer's zone, the ones chosen lately, COMMON), the regions (each by its offset, then its name), Other names.
export function buildOptions(data, ctx) {
  const { t } = ctx
  const zones = (data && data.zones) || []
  const byId = new Map(zones.map((z) => [z.id, z]))
  const sys = data && data.system ? byId.get(data.system) : null
  const follow = { value: '', label: t('tz.followComputer'), hint: sys ? `${formatOffset(sys.offset)} · ${sys.id}` : data && data.system ? data.system : '',
    keywords: sys ? offsetWords(sys.offset) : [] }
  const common = []
  for (const id of [sys && sys.id, ...(ctx.recent || []), ...COMMON]) {
    if (id && byId.has(id) && !common.some((o) => o.value === id)) common.push(optionOf(byId.get(id), 'common', ctx))
  }
  const by = Object.fromEntries(GROUPS.map((g) => [g, []]))
  for (const z of zones) { const g = groupOf(z); by[g].push(optionOf(z, g, ctx)) }
  const collator = new Intl.Collator(ctx.locale)
  for (const g of GROUPS) {
    if (g === 'other') by[g].sort((a, b) => a.value.localeCompare(b.value))
    else if (g !== 'common') by[g].sort((a, b) => a.offset - b.offset || collator.compare(a.label, b.label))
  }
  by.common = common
  const groups = GROUPS.filter((g) => by[g].length).map((g) => ({ id: g, label: t('tz.group.' + g) }))
  return { options: [follow, ...GROUPS.flatMap((g) => by[g])], groups }
}

// Is a value one the program can use? '' is (the computer's zone); a zone of the list is; one the server says it can
// read although it is not listed is (the server read the saved value: `chosen` / `chosen_valid`); anything else is not.
export function isValidZone(value, data) {
  if (!value || !data) return true
  if ((data.zones || []).some((z) => z.id === value)) return true
  return value === data.chosen && !!data.chosen_valid
}
