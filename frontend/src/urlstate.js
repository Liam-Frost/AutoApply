// What a page is showing, in its address.
//
// A filter, a sort order, the tab that is open: they were kept in the page and gone with it - reload, come back from
// a posting, send someone the address, and the list was the default one again. The state that says "what am I
// looking at" goes into the query; what is the default is left out, so the plain address stays the plain page.

// The state as a query: only what differs from the defaults. Numbers and booleans are written as text; `true` as "1".
export function toQuery(state, defaults) {
  const q = {}
  for (const k of Object.keys(defaults)) {
    const v = state[k], d = defaults[k]
    if (v === d || (v === '' && d === '') || v === undefined || v === null) continue
    q[k] = typeof d === 'boolean' ? (v ? '1' : '0') : String(v)
  }
  return q
}

// The state a query describes, on top of the defaults. A value takes the type of its default; what is not among the
// defaults is not taken (an address can be typed by anyone), and a number that is not one stays the default.
export function fromQuery(query, defaults, allowed = {}) {
  const out = { ...defaults }
  for (const k of Object.keys(defaults)) {
    let v = query ? query[k] : undefined
    if (Array.isArray(v)) v = v[0]
    if (v === undefined || v === null) continue
    const d = defaults[k]
    if (typeof d === 'boolean') out[k] = v === '1' || v === 'true'
    else if (typeof d === 'number') { const n = Number(v); if (Number.isFinite(n)) out[k] = n }
    else out[k] = String(v)
    if (allowed[k] && !allowed[k].includes(out[k])) out[k] = d       // one of a known list, or the default
  }
  return out
}

// Are two queries the same, as far as the address goes?
export function sameQuery(a, b) {
  const ka = Object.keys(a || {}).sort(), kb = Object.keys(b || {}).sort()
  return ka.length === kb.length && ka.every((k, i) => k === kb[i] && String(a[k]) === String(b[k]))
}
