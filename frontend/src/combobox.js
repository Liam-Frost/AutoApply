// The search of a Combobox (components/Combobox.vue) and how its keyboard moves the mark. Pure - no document - so that
// both can be tested (tests/combobox.test.js); the component draws what `search` returns.

// What a search compares: lower case, without accents, one kind of minus, the words apart. `+`, `-` and `:` stay inside
// a word ("utc-7", "+05:30"): an offset from UTC is written with them.
const APART = /[\s/,()（），、·_.;|]+/g
export function fold(s) {
  return String(s == null ? '' : s).normalize('NFD').replace(/\p{M}/gu, '').toLowerCase()
    .replace(/[−‐‑–]/g, '-').replace(APART, ' ').trim()
}

// Each option once, folded: what its words are (label, hint, value, keywords), and its label on its own (an option
// whose label starts with the search comes first).
export function prepare(options) {
  return (options || []).map((o, i) => {
    const label = fold(o.label)
    const words = [label, fold(o.hint), fold(o.value), ...(o.keywords || []).map(fold)].filter(Boolean).join(' ')
    return { o, i, label, text: ' ' + words + ' ' }
  })
}

// How well an option matches (lower is better; -1: not at all): its label starts with the search, a whole word is the
// search, a word starts with it, it is somewhere inside, every word of the search is somewhere inside.
export function rank(p, q, parts = q ? q.split(' ') : []) {
  if (!q) return 0
  if (p.label.startsWith(q)) return 0
  if (p.text.includes(' ' + q + ' ')) return 1
  if (p.text.includes(' ' + q)) return 2
  if (p.text.includes(q)) return 3
  if (parts.length > 1 && parts.every((w) => p.text.includes(w))) return 4
  return -1
}

// What the list shows for a search: `sections` in the order of `groups` (the options without a group, or with one that
// is not named in `groups`, first), each with the options that match, best first - a group with none is left out; and
// `items`, the options in the order shown (what the keyboard walks through; `at` of a row is its place there). While
// something is searched, an option that is in two groups (a zone under "Common" and under its region) is shown once.
export function search(prepared, groups = [], query = '') {
  const q = fold(query)
  const parts = q ? q.split(' ') : []
  const place = new Map(groups.map((g, i) => [g.id, i + 1]))
  const buckets = Array.from({ length: groups.length + 1 }, () => [])
  for (const p of prepared) {
    const r = rank(p, q, parts)
    if (r >= 0) buckets[place.get(p.o.group) || 0].push({ p, r })
  }
  const seen = new Set()
  const sections = [], items = []
  buckets.forEach((b, gi) => {
    if (q) b.sort((x, y) => x.r - y.r || x.p.i - y.p.i)
    const rows = []
    for (const { p } of b) {
      if (q) {
        const k = String(p.o.value)
        if (seen.has(k)) continue
        seen.add(k)
      }
      rows.push({ option: p.o, at: items.length })
      items.push(p.o)
    }
    if (rows.length) sections.push({ group: gi ? groups[gi - 1] : null, rows })
  })
  return { sections, items }
}

// Where a key moves the mark among `items` from `i` (-1: none yet): the arrows go round the ends, Home / End to the first
// / last, the page keys `page` options on (and stop at the ends). A disabled option is passed over. -1: nothing to mark.
export function step(items, i, key, page = 8) {
  const n = items.length
  const ok = (k) => k >= 0 && k < n && !items[k].disabled
  const first = () => { for (let k = 0; k < n; k++) if (ok(k)) return k; return -1 }
  const last = () => { for (let k = n - 1; k >= 0; k--) if (ok(k)) return k; return -1 }
  if (!n) return -1
  if (key === 'Home') return first()
  if (key === 'End') return last()
  if (key === 'ArrowDown' || key === 'ArrowUp') {
    const d = key === 'ArrowDown' ? 1 : -1
    if (i < 0 || i >= n) return d > 0 ? first() : last()
    for (let s = 1; s <= n; s++) { const k = (((i + d * s) % n) + n) % n; if (ok(k)) return k }
    return ok(i) ? i : -1
  }
  if (key === 'PageDown' || key === 'PageUp') {
    const d = key === 'PageDown' ? 1 : -1
    let k = Math.max(0, Math.min(n - 1, (i < 0 ? (d > 0 ? -1 : n) : i) + d * page))
    while (k >= 0 && k < n && !ok(k)) k += d
    return ok(k) ? k : d > 0 ? last() : first()
  }
  return i
}

// The option a value is (values are compared as text: 3 and "3" are one), its place among `items` or -1.
export const same = (a, b) => a === b || (a != null && b != null && String(a) === String(b))
export const indexOf = (items, value) => items.findIndex((o) => same(o.value, value))
