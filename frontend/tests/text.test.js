// What is shown as text: the Markdown of the profile (which must never let markup through), the figures of the
// analytics page, a time as "today 14:05".
import { afterEach, describe, expect, it, vi } from 'vitest'
import { change, compact, dur, money, ms, pct, rangeQuery, share } from '../src/analytics.js'
import { renderMarkdown } from '../src/md.js'
import { fmtTime } from '../src/ui.js'

describe('renderMarkdown', () => {
  it('lets no markup of the text through', () => {
    const html = renderMarkdown('<img src=x onerror=alert(1)>\n\n**bold** and <script>alert(1)</script> and <SCRIPT>alert(2)</SCRIPT> and <IMG SRC=x> and `<b>code</b>`')
    expect(html).not.toMatch(/<img|<script|<b>/i)             // in whatever case it was written
    expect(html).toContain('&lt;SCRIPT&gt;')
    expect(html).toContain('&lt;img')
    expect(html).toContain('<strong>bold</strong>')
    expect(html).toContain('<code>&lt;b&gt;code&lt;/b&gt;</code>')
  })
  it('links only what is an http(s) or mailto address', () => {
    expect(renderMarkdown('[site](https://example.com/a)')).toContain('<a href="https://example.com/a" target="_blank" rel="noopener">site</a>')
    expect(renderMarkdown('[mail](mailto:a@example.com)')).toContain('href="mailto:a@example.com"')
    expect(renderMarkdown('[x](javascript:alert(1))')).not.toContain('<a ')
    expect(renderMarkdown('[x](data:text/html,hi)')).not.toContain('<a ')
    expect(renderMarkdown('a "quoted" [t](https://example.com/?q="x")')).not.toMatch(/href="[^"]*"x"/)
  })
  it('makes headings, lists and the marker for what is still to fill in', () => {
    const html = renderMarkdown('## Education\n- UBC\n  - BASc\n\nThen:\n\n1. one\n\nTODO: phone')
    expect(html).toMatch(/<h\d[^>]*>Education<\/h\d>/)
    expect(html).toMatch(/<ul>.*UBC.*<ul>.*BASc.*<\/ul>.*<\/ul>/s)
    expect(html).toContain('<ol>')
    expect(html).toContain('<span class="tag warn">TODO</span>')
  })
})

describe('figures of the analytics page', () => {
  it('rounds shares and never divides by nothing', () => {
    expect(pct(1, 3)).toBe(33)
    expect(pct(5, 0)).toBe(0)
    expect(share(null)).toBe('—')
    expect(share(0.001)).toBe('<1%')
    expect(share(0)).toBe('0%')
    expect(share(0.126)).toBe('13%')
  })
  it('says durations and sizes in the unit that fits', () => {
    expect(ms(null)).toBe('—')
    expect(ms(950)).toBe('950毫秒')            // (in the interface language, by Intl: 950 ms in English)
    expect(ms(1500)).toBe('1.5秒')
    expect(typeof dur(75)).toBe('string')
    expect(compact(950)).toBe('950')
    expect(compact(12500)).not.toBe('12500')
    expect(money(null)).toBe('—')
    expect(money(2_500_000)).toMatch(/^\$2\.50?$/)
    expect(money(2_500_000, true)).toMatch(/^≥ \$/)
  })
  it('compares with the period before, and says nothing where there is nothing to compare with', () => {
    expect(change(10, 0)).toBe('')
    expect(change(null, 5)).toBe('')
    expect(change(12, 10)).toBe('较上一时段 +20%')
    expect(change(8, 10)).toBe('较上一时段 -20%')
    expect(change(10.01, 10)).toBe('与上一时段持平')
  })
  it('turns a range into a query', () => {
    const q = rangeQuery({ days: 30 }, { kind: 'execute' })
    expect(q).toContain('kind=execute')
  })
})

describe('fmtTime', () => {
  afterEach(() => vi.useRealTimers())
  it('calls a time by its day', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 10, 18, 15, 0, 0))
    const local = (y, m, d, h, min) => new Date(y, m, d, h, min).toISOString()
    expect(fmtTime(local(2026, 10, 18, 9, 5))).toMatch(/^今天 0?9:05$/)
    expect(fmtTime(local(2026, 10, 17, 23, 59))).toMatch(/^昨天 23:59$/)
    expect(fmtTime(local(2026, 10, 3, 8, 0))).toMatch(/^11月3日 0?8:00$/)
    expect(fmtTime('')).toBe('')
    // a time the server wrote without a zone is UTC
    expect(fmtTime('2026-11-18T10:00:00')).toBe(fmtTime('2026-11-18T10:00:00Z'))
  })
})
