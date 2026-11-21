// The interface's words by key: vue-i18n with message catalogs (src/locales/<language>.json).
//
// English is the source: locales/en.json has every key, locales/notes.json says for each where it is shown and what
// its placeholders are, and every other language is a translation of it. A key a translation does not have yet is
// shown in English - never in Chinese, never as the key's name.
//
// The pages are moving to keys one by one (2.0.1: this base, new and rewritten pages; 2.0.2: the rest). Until a page
// has moved, its Chinese text is translated on the screen by the older dictionary (index.js). Both work side by side:
// text from a key is never Chinese in another language, so the dictionary leaves it alone.
import { reactive } from 'vue'
import { createI18n } from 'vue-i18n'
import manifest from '../locales/languages.json'
import en from '../locales/en.json'
import zh from '../locales/zh.json'

// other languages are downloaded only when chosen
const OTHERS = import.meta.glob(['../locales/*.json', '!../locales/en.json', '!../locales/zh.json', '!../locales/notes.json', '!../locales/languages.json'])

export const LANGUAGES = manifest.languages
export const SOURCE = manifest.source
export const LANGS = Object.fromEntries(LANGUAGES.map((l) => [l.id, l.name]))
// a language whose translation is not complete enough is offered as a test ("测试中")
export const isBeta = (id) => ((LANGUAGES.find((l) => l.id === id) || {}).complete ?? 0) < manifest.beta_below

let saved = 'zh'
let chosenHere = false     // has this browser made a choice of its own?
try { const v = localStorage.getItem('lang'); chosenHere = !!v; saved = v || 'zh' } catch (e) { /* private window, or not a browser */ }
export const lang = reactive({ value: LANGS[saved] ? saved : 'zh' })
export const chosen = () => chosenHere

// The language's tag for Intl (dates, numbers, plural rules): zh -> zh-CN.
export const tagOf = (id) => (LANGUAGES.find((l) => l.id === id) || {}).tag || id
export const tag = () => tagOf(lang.value)

// Plural forms are written in the order of the language's plural categories as CLDR has them (zero, one, two, few,
// many, other - the ones the language uses): "{n} day left | {n} days left" in English, one form in Chinese. A
// translation with fewer forms than its language has categories uses its last form for the rest.
const ORDER = ['zero', 'one', 'two', 'few', 'many', 'other']
export function pluralRule(languageTag) {
  const rules = new Intl.PluralRules(languageTag)
  const cats = ORDER.filter((c) => rules.resolvedOptions().pluralCategories.includes(c))
  return (choice, forms) => {
    const i = cats.indexOf(rules.select(Math.abs(choice)))
    return Math.min(i < 0 ? forms - 1 : i, forms - 1)
  }
}

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,       // $t in templates
  locale: lang.value,
  fallbackLocale: SOURCE,
  messages: { en, zh },
  pluralRules: Object.fromEntries(LANGUAGES.map((l) => [l.id, pluralRule(l.tag)])),
  missingWarn: false,
  fallbackWarn: false,
})

// t('deadline.daysLeft', { n: 3 }, 3): the words of a key, with its values (and the number that picks a plural form)
export const t = (...args) => i18n.global.t(...args)

// The catalog of a language, loaded when it is not one that comes with the page, and made the one in use.
export async function useLanguage(id) {
  if (!i18n.global.availableLocales.includes(id)) {
    const load = OTHERS[`../locales/${id}.json`]
    if (load) i18n.global.setLocaleMessage(id, (await load()).default)
  }
  i18n.global.locale.value = id
}
