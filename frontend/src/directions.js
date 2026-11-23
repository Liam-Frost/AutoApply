// A posting's field ("direction"): a key of the fixed list (backend/autoapply/directions.py) - "software.backend", or a
// field alone ("civil"), or "other" - said in the reader's language from the catalog (direction.<field>._ and
// direction.<field>.<specialty>). A label from before the list is "not sorted yet": shown as it was until the program
// has sorted it.
import { i18n, t as T } from './i18n/catalog'

export const UNSORTED = 'unsorted'
const nameKey = (v) => 'direction.' + (v.includes('.') ? v : v + '._')
const named = (k) => i18n.global.te(k) || i18n.global.te(k, 'en')      // (English comes with the page, and has every key)
export const isKey = (v) => typeof v === 'string' && /^[a-z]+(\.[a-z]+)?$/.test(v) && named(nameKey(v))
export const fieldOf = (v) => (isKey(v) ? v.split('.')[0] : '')

// The name of a field or a specialty; `whole`: a specialty with its field ("Software engineering · Back end")
export function dirLabel(v, { whole = false } = {}) {
  if (!v) return ''
  if (!isKey(v)) return v
  if (!v.includes('.') || !whole) return T(nameKey(v))
  return `${T(nameKey(fieldOf(v)))} · ${T(nameKey(v))}`
}

// Does a posting's field fall under what the filter asks for (a field takes in its specialties)?
export function under(v, wanted) {
  if (!wanted) return true
  if (wanted === UNSORTED) return !!v && !isKey(v)
  return v === wanted || (isKey(v) && v.startsWith(wanted + '.'))
}

// The filter's options for the fields in `values`: each field (with how many), its specialties under it, then what is
// not sorted yet - the largest first. [{ value, label, n, sub }]
export function filterOptions(values) {
  const fields = new Map()
  let unsorted = 0
  for (const v of values) {
    if (!v) continue
    if (!isKey(v)) { unsorted++; continue }
    const f = fieldOf(v)
    const e = fields.get(f) || { n: 0, specs: new Map() }
    e.n++
    if (v.includes('.')) e.specs.set(v, (e.specs.get(v) || 0) + 1)
    fields.set(f, e)
  }
  const out = []
  for (const [f, e] of [...fields].sort((a, b) => b[1].n - a[1].n || a[0].localeCompare(b[0]))) {
    out.push({ value: f, label: dirLabel(f), n: e.n, sub: false })
    for (const [k, n] of [...e.specs].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))) out.push({ value: k, label: dirLabel(k), n, sub: true })
  }
  if (unsorted) out.push({ value: UNSORTED, label: T('direction.unsorted'), n: unsorted, sub: false })
  return out
}
