// Formatting for the analysis page. The numbers themselves (sums, shares, medians) are computed by the server;
// nothing here adds up money.

export const pct = (a, b) => (b ? Math.round((a / b) * 100) : 0)

// Money arrives as millionths of a dollar (an integer). null means "cannot be told" and is shown as a dash, never as 0.
export function money(micros, approx = false) {
  if (micros == null) return '—'
  const v = micros / 1e6
  const digits = v === 0 ? 2 : v < 0.01 ? 4 : v < 1 ? 3 : 2
  return (approx ? '≥ ' : '') + '$' + v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function compact(n) {
  if (n == null) return '—'
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B'
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'
  if (n >= 1e4) return (n / 1e3).toFixed(1) + 'K'
  return Math.round(n).toLocaleString('en-US')
}

export function dur(s) {
  if (s == null) return '—'
  if (s < 60) return `${Math.max(1, Math.round(s))} 秒`
  s = Math.round(s)        // (rounded first: 719.6 seconds is 12 minutes, not "11 minutes 60 seconds")
  if (s < 3600) return `${Math.floor(s / 60)} 分 ${s % 60} 秒`
  const m = Math.round(s / 60)
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`
}

// a share of a whole (0..1) in words: never "0%" for something that is there
export const share = (v) => (v == null ? '—' : v > 0 && v < 0.005 ? '<1%' : Math.round(v * 100) + '%')

export const ms = (v) => (v == null ? '—' : v < 1000 ? `${Math.round(v)} ms` : `${(v / 1000).toFixed(1)} s`)

// Change against the period before. Only when there is a period before and it was not empty.
export function change(cur, prev) {
  if (prev == null || !prev || cur == null) return ''
  const d = (cur - prev) / prev
  if (Math.abs(d) < 0.005) return '和上一段持平'
  return `比上一段 ${d > 0 ? '+' : '−'}${Math.abs(Math.round(d * 100))}%`
}

// A range chosen in the page head -> query string
export function rangeQuery(range, extra = {}) {
  const q = new URLSearchParams()
  if (range.mode === 'custom') { if (range.start) q.set('start', range.start); if (range.end) q.set('end', range.end) }
  else if (range.mode === 'today') {      // the local calendar day, not the last 24 hours
    const d = new Date(); const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    q.set('start', day); q.set('end', day)
  } else if (+range.mode) q.set('days', range.mode)
  for (const [k, v] of Object.entries(extra)) if (v !== '' && v != null) q.set(k, v)
  const s = q.toString()
  return s ? '?' + s : ''
}

export const SERIES_COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)', 'var(--chart-6)']
export const colorOf = (i, key) => (key === '__other' ? 'var(--chart-other)' : SERIES_COLORS[i % SERIES_COLORS.length])
