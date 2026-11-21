// How complete a translation is, against the English source: the share of its keys that are there and carry the same
// placeholders. Used by scripts/i18n-status.mjs (which writes the figure into locales/languages.json) and by the tests
// (which check that the figure written is the one the files give).

// { "a.b": "text" } from a nested catalog
export function leaves(tree, prefix = '') {
  const out = {}
  for (const [k, v] of Object.entries(tree)) {
    if (v && typeof v === 'object') Object.assign(out, leaves(v, prefix + k + '.'))
    else out[prefix + k] = v
  }
  return out
}

export const placeholders = (s) => [...new Set([...String(s).matchAll(/\{(\w+)\}/g)].map((m) => m[1]))].sort().join(',')

// is this translation of the source text usable: there, and with the same placeholders
export const fits = (source, translated) => typeof translated === 'string' && translated !== '' && placeholders(source) === placeholders(translated)

export function completeness(source, translation) {
  const src = leaves(source)
  const tr = leaves(translation)
  const keys = Object.keys(src)
  if (!keys.length) return 100
  return Math.floor((100 * keys.filter((k) => fits(src[k], tr[k])).length) / keys.length)
}
