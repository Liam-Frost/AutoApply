// The keyed half of the interface's languages (src/i18n/catalog.js, src/locales/): every key the code uses is in the
// English source, every key has a note for translators, translations carry the same placeholders, the completeness
// written in the manifest is what the files give, and dates and numbers follow the language.
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { completeness, fits, leaves, placeholders } from '../src/i18n/completeness.js'
import { i18n, isBeta, pluralRule, t } from '../src/i18n/catalog.js'
import { dayOf, duration, usd, when } from '../src/i18n/format.js'
import { deadlineLabel } from '../src/dates.js'
import { change, money } from '../src/analytics.js'

const dir = new URL('../src/locales/', import.meta.url)
const read = (f) => JSON.parse(readFileSync(new URL(f, dir), 'utf-8'))
const manifest = read('languages.json')
const source = leaves(read('en.json'))
const notes = read('notes.json')

function files(d) {
  return readdirSync(d).flatMap((f) => { const p = join(d, f); return statSync(p).isDirectory() ? files(p) : /\.(vue|js)$/.test(f) ? [p] : [] })
}
const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

describe('the catalogs', () => {
  it('have every key the code uses', () => {
    const used = new Set()
    for (const f of files(SRC)) {
      for (const m of readFileSync(f, 'utf-8').matchAll(/\$?\bt\(\s*'([a-z][\w]*(?:\.[\w]+)+)'/g)) used.add(m[1])
    }
    expect(used.size).toBeGreaterThan(5)
    expect([...used].filter((k) => !(k in source))).toEqual([])
  })
  it('have a note for every key, and no note without its key', () => {
    expect(Object.keys(source).filter((k) => !notes[k])).toEqual([])
    expect(Object.keys(notes).filter((k) => !(k in source))).toEqual([])
  })
  it('translate with the same placeholders and nothing the source does not have', () => {
    for (const l of manifest.languages.filter((x) => x.id !== manifest.source)) {
      const tr = leaves(read(l.id + '.json'))
      expect(Object.keys(tr).filter((k) => !(k in source)), l.id).toEqual([])
      expect(Object.keys(tr).filter((k) => !fits(source[k], tr[k])), l.id).toEqual([])
    }
  })
  it('are as complete as the manifest says (npm run i18n:status)', () => {
    for (const l of manifest.languages) {
      const both = (id) => ({ ...read(id + '.json'), server: read('server/' + id + '.json') })
      expect(l.complete, l.id).toBe(l.id === manifest.source ? 100 : completeness(both('en'), both(l.id)))
    }
    expect(isBeta('zh')).toBe(false)
    expect(placeholders('{n} day | {n} days, {time}')).toBe('n,time')
    expect(completeness({ a: 'x {n}', b: 'y' }, { a: 'z' })).toBe(0)                 // a placeholder lost is not a translation
    expect(completeness({ a: 'x {n}', b: 'y' }, { a: 'z {n}' })).toBe(50)
  })
})

describe('plural forms', () => {
  it('follow the language: one form in Chinese, one | other in English, French 0 and 1 singular', () => {
    expect([0, 1, 2].map((n) => pluralRule('en')(n, 2))).toEqual([1, 0, 1])
    expect([0, 1, 2].map((n) => pluralRule('fr')(n, 2))).toEqual([0, 0, 1])
    expect([0, 1, 5].map((n) => pluralRule('zh-CN')(n, 1))).toEqual([0, 0, 0])
  })
})

describe('in English', () => {
  afterEach(() => { i18n.global.locale.value = 'zh' })
  const at = (h, m = 0, day = 18) => new Date(2026, 10, day, h, m)
  it('a deadline, a moment, an amount and a duration are written the English way', () => {
    i18n.global.locale.value = 'en'
    // (the tag Intl is given follows lang, which a test does not change: what is checked here is the words)
    expect(deadlineLabel('2026-11-18 23:59', at(12)).text).toMatch(/^Due today 23:59$/)
    expect(deadlineLabel('2026-11-19 23:59', at(12)).text).toBe('Due tomorrow')
    expect(deadlineLabel('2026-11-21', at(12)).text).toBe('3 days left')
    expect(deadlineLabel('2026-11-17', at(12)).text).toBe('Closed')
    expect(t('todos.deadline.left', { n: 1 }, 1)).toBe('1 day left')
    expect(when(at(9, 5), at(15))).toMatch(/^Today 09:05$/)
    expect(change(12, 10)).toBe('+20% on the period before')
  })
  it('a key a translation lacks is shown in English, not as its name', () => {
    i18n.global.setLocaleMessage('xx', { time: {} })
    i18n.global.locale.value = 'xx'
    expect(t('time.today', { time: '09:05' })).toBe('Today 09:05')
  })
})

describe('in Chinese (the default)', () => {
  it('reads as before', () => {
    expect(deadlineLabel('2026-11-21', new Date(2026, 10, 18, 12)).text).toBe('还有 3 天')
    expect(dayOf(new Date(2026, 10, 3))).toBe('11月3日')
    expect(usd(2.5)).toBe('$2.50')
    expect(money(2_500_000)).toBe('$2.50')
    expect(duration({ minutes: 12, seconds: 5 })).toMatch(/12.*分.*5.*秒/)
  })
})

// The pages moved to keys (C2): no Chinese is written in them any more, outside comments. A page is added here when
// it moves; the on-screen dictionary has nothing left to do on it.
const MIGRATED = ['views/TodosView.vue', 'views/CalendarView.vue', 'views/AnalyticsView.vue', 'views/analytics/CostPanel.vue', 'views/analytics/AutoPanel.vue',
  'views/analytics/AppsPanel.vue', 'views/analytics/RunDetail.vue', 'views/analytics/SitesPanel.vue', 'views/SettingsView.vue', 'components/AiPanel.vue',
  'components/MailboxPanel.vue', 'components/AccessPanel.vue', 'components/NetworkPanel.vue', 'components/BrowserPanel.vue', 'components/PromptsPanel.vue',
  'components/EmployersPanel.vue', 'views/ProfileView.vue', 'views/WelcomeView.vue', 'views/RunsView.vue', 'views/AccountsView.vue', 'views/FilesView.vue',
  'views/HomeView.vue', 'views/SourcesView.vue', 'App.vue', 'views/MailOut.vue', 'views/ContactsView.vue', 'views/RemoteView.vue', 'views/LoginView.vue']
// HTML and block comments cut out by position (not by a pattern a nested or broken one could slip through)
function withoutComments(text) {
  let out = ''
  let at = 0
  for (;;) {
    const html = text.indexOf('<!--', at)
    const block = text.indexOf('/*', at)
    const start = [html, block].filter((x) => x >= 0).sort((a, b) => a - b)[0]
    if (start === undefined) return out + text.slice(at)
    const close = start === html ? '-->' : '*/'
    const stop = text.indexOf(close, start + 2)
    out += text.slice(at, start)
    at = stop < 0 ? text.length : stop + close.length
  }
}
describe('pages moved to keys', () => {
  it('have no text of their own in Chinese', () => {
    for (const f of MIGRATED) {
      const src = withoutComments(readFileSync(new URL('../src/' + f, import.meta.url), 'utf-8'))
        .replace(/^\s*\/\/.*$/gm, '').replace(/\s\/\/ .*$/gm, '')
      const lines = src.split('\n').filter((l) => /[一-鿿]/.test(l))
      expect(lines, f).toEqual([])
    }
  })
})
