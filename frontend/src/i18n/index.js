// Interface language. The source language of the templates is Chinese; other languages are a dictionary
// ({"中文": "English"}, built by scripts/i18n_extract.py + i18n_translate.py) applied to what is on screen.
//
// Why at the DOM and not with keys in every template: one dictionary covers the templates, the script strings and
// the wording that comes from the server, and a new language is a new JSON file. The cost: text that is assembled
// in ways the dictionary has no pattern for stays in Chinese until an entry is added - never garbled, just untranslated.
import { reactive } from 'vue'

export const LANGS = { zh: '中文', en: 'English' }
// one entry per dictionary, so each language is its own file that is only downloaded when chosen
const LOADERS = { en: () => import('./en.json') }
let saved = 'zh'
let chosenHere = false     // has this browser made a choice of its own?
try { const v = localStorage.getItem('lang'); chosenHere = !!v; saved = v || 'zh' } catch (e) { /* private window */ }
export const lang = reactive({ value: LANGS[saved] ? saved : 'zh' })

const CJK = /[一-鿿]/
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
let dict = null
let patterns = []
let segRe = null
let shortRe = null

function build(d) {
  dict = d
  const keys = Object.keys(d)
  patterns = keys.filter((k) => /\{\d+\}/.test(k)).map((k) => ({
    re: new RegExp('^' + esc(k).replace(/\\\{\d+\\\}/g, '([\\s\\S]*?)') + '$'),
    order: [...k.matchAll(/\{(\d+)\}/g)].map((m) => +m[1]),
    out: d[k],
    weight: k.replace(/\{\d+\}/g, '').length,
  })).sort((a, b) => b.weight - a.weight)   // the most specific pattern first
  // whole phrases inside longer text; short words are left alone (replacing them piecemeal would produce nonsense)
  const segs = keys.filter((k) => !/\{\d+\}/.test(k) && k.length >= 4).sort((a, b) => b.length - a.length)
  segRe = segs.length ? new RegExp(segs.map(esc).join('|'), 'g') : null
  // short words (个月, 今天, 截止 ...) only where they stand on their own between non-Chinese characters, e.g. "4 个月"
  const short = keys.filter((k) => !/\{\d+\}/.test(k) && k.length < 4 && CJK.test(k)).sort((a, b) => b.length - a.length)
  shortRe = short.length ? new RegExp('(^|[^\\u4e00-\\u9fff])(' + short.map(esc).join('|') + ')(?![\\u4e00-\\u9fff])', 'g') : null
}

const SEP = /(\s?·\s|；|; |，|, |：|: |（|）| \/ |、|\s?\|\s)/

// a part of a joined string: translated if it can be, kept (as a marker of failure) if not
function part(x, depth) { return CJK.test(x) ? tr(x, depth) : x }
const PUNCT = { '；': '; ', '，': ', ', '：': ': ', '（': ' (', '）': ') ', '、': ', ' }

export function tr(s, depth = 0) {
  if (!dict || !s || !CJK.test(s)) return s
  const lead = s.match(/^\s*/)[0]
  const tail = s.match(/\s*$/)[0]
  const core = s.trim().replace(/\s+/g, ' ')
  let out = dict[core]
  if (out == null) {
    for (const p of patterns) {
      const m = core.match(p.re)
      if (m) { out = p.out.replace(/\{(\d+)\}/g, (_, n) => tr(m[p.order.indexOf(+n) + 1] ?? '', depth + 1)); break }
    }
  }
  if (out == null) {
    // text put together from parts ("今天 15:25 · 298 KB", "已投递；需简历"): translate each part on its own
    const parts = core.split(SEP)
    if (parts.length > 1 && depth < 3) out = parts.map((x, i) => (i % 2 ? PUNCT[x] || x : part(x, depth + 1))).join('')
  }
  if (out == null || CJK.test(out)) {
    let o = out == null ? core : out
    if (segRe) o = o.replace(segRe, (m) => dict[m])
    if (shortRe) o = o.replace(shortRe, (_, pre, w) => pre + dict[w])
    out = o
  }
  // All or nothing. If any Chinese is left, this is not (only) interface text - it is something the user, a website or
  // the AI wrote - and a half-translated sentence is worse than the original. Show it exactly as it was.
  if (CJK.test(out)) return s
  return lead + out + tail
}

const ATTRS = ['placeholder', 'title', 'aria-label']
// what the user or a website wrote is theirs: it is shown as written
const SKIP = 'textarea, pre, code, [data-notr], .md, .pdf, script, style'

function visit(node) {
  if (node.nodeType === 3) {
    if (CJK.test(node.nodeValue) && !(node.parentElement && node.parentElement.closest(SKIP))) {
      const t = tr(node.nodeValue)
      if (t !== node.nodeValue) node.nodeValue = t
    }
    return
  }
  if (node.nodeType !== 1 || node.matches(SKIP)) return
  for (const a of ATTRS) {
    const v = node.getAttribute(a)
    if (v && CJK.test(v)) { const t = tr(v); if (t !== v) node.setAttribute(a, t) }
  }
  for (const c of node.childNodes) visit(c)
}

export async function initI18n() {
  document.documentElement.lang = lang.value === 'zh' ? 'zh-CN' : lang.value
  if (lang.value === 'zh') return
  try {
    build((await LOADERS[lang.value]()).default)
  } catch (e) { return }   // no dictionary for this language yet: stay in Chinese
  new MutationObserver((list) => {
    for (const m of list) {
      if (m.type === 'characterData') visit(m.target)
      else if (m.type === 'attributes') visit(m.target)
      else for (const n of m.addedNodes) visit(n)
    }
  }).observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS })
  visit(document.body)
}

// A browser that has not chosen yet follows what the program was set up with (the installer's language, or the system's).
export async function followServerLang() {
  if (chosenHere) return
  try {
    const r = await fetch('/api/settings')
    const v = (await r.json()).settings['ui.lang']
    if (LANGS[v] && v !== lang.value) { lang.value = v; try { localStorage.setItem('lang', v) } catch (e) { /* ignore */ } await initI18n() }
  } catch (e) { /* the page still works in the default language */ }
}

export function setLang(v) {
  try { localStorage.setItem('lang', v) } catch (e) { /* ignore */ }
  // the server needs to know too: summaries and reasons written by the AI follow the interface language
  fetch('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: { 'ui.lang': v } }) }).finally(() => location.reload())
}
