// The colours of text against what it stands on, read from the stylesheet itself.
//
// Small text has to reach 4.5:1 (WCAG 2.2, contrast minimum). The weak text of the light theme was at 2.9:1, and the
// dark theme put white on a pale red. A colour is easily changed by eye; this holds every pair to the number, in both
// themes, so that the next change of a token shows here.
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8')

// the tokens of a block of the stylesheet: { '--text': '#14233b', ... }
function tokens(block) {
  const out = {}
  for (const m of block.matchAll(/(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\s*;/g)) out[m[1]] = m[2]
  return out
}
const light = tokens(css.slice(css.indexOf(':root'), css.indexOf('color-scheme: light')))
const darkAt = css.indexOf(':root[data-theme="dark"]')
const dark = { ...light, ...tokens(css.slice(darkAt, css.indexOf('color-scheme: dark;', darkAt))) }
// the dark theme is written twice (when the system is dark, and when it was chosen): both have to say the same
const sysAt = css.indexOf(':root:not([data-theme="light"])')
const darkSys = { ...light, ...tokens(css.slice(sysAt, css.indexOf('color-scheme: dark;', sysAt))) }

const lum = (hex) => {
  const h = hex.replace('#', '')
  const full = h.length === 3 ? [...h].map((c) => c + c).join('') : h.slice(0, 6)
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
export const contrast = (a, b) => { const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x); return (hi + 0.05) / (lo + 0.05) }

// text / what it stands on. Everything here is text that is read: 4.5:1.
const PAIRS = [
  ['--text', '--bg'], ['--text', '--surface'], ['--text', '--surface-2'],
  ['--text-2', '--bg'], ['--text-2', '--surface'], ['--text-2', '--surface-2'],
  ['--text-3', '--bg'], ['--text-3', '--surface'], ['--text-3', '--surface-2'],
  ['--primary', '--surface'], ['--primary', '--bg'], ['--on-primary', '--primary'],
  ['--primary', '--primary-soft'],      // the chosen item of the sidebar, an emphasised secondary button (.tonal)
  ['--ok', '--ok-soft'], ['--warn', '--warn-soft'], ['--bad', '--bad-soft'], ['--info', '--info-soft'],
  ['--ok', '--surface'], ['--warn', '--surface'], ['--bad', '--surface'],
  ['--on-bad', '--bad'],
  ['--tip-fg', '--tip-bg'],      // the tooltip: the reverse of the page
  // the calendar's kinds of item: the text on its pale ground, and on the page where it stands without one
  ...['deadline', 'interview', 'assessment', 'offer', 'follow', 'own', 'system'].flatMap((k) => [[`--ev-${k}-fg`, `--ev-${k}-bg`], [`--ev-${k}-fg`, '--surface']]),
]

describe('the arithmetic', () => {
  it('is the WCAG one', () => {
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 5)
    expect(contrast('#8b98ab', '#ffffff')).toBeCloseTo(2.93, 1)        // the weak text of the light theme as the audit measured it
    expect(contrast('#ffffff', '#f29b94')).toBeCloseTo(2.12, 1)        // white on the dark theme's red
  })
})

for (const [name, theme] of [['light', light], ['dark (chosen)', dark], ['dark (system)', darkSys]]) {
  describe(`${name} theme`, () => {
    it('has every token the pairs name', () => {
      for (const [fg, bg] of PAIRS) { expect(theme[fg], fg).toBeTruthy(); expect(theme[bg], bg).toBeTruthy() }
    })
    for (const [fg, bg] of PAIRS) {
      it(`${fg} on ${bg} is at least 4.5:1`, () => {
        expect(contrast(theme[fg], theme[bg]), `${theme[fg]} on ${theme[bg]}`).toBeGreaterThanOrEqual(4.5)
      })
    }
    it('the weak text is still weaker than the secondary text', () => {
      expect(contrast(theme['--text-3'], theme['--surface'])).toBeLessThan(contrast(theme['--text-2'], theme['--surface']))
    })
  })
}

describe('the two ways the dark theme is written', () => {
  it('say the same', () => { expect(darkSys).toEqual(dark) })
})

describe('text on the colour for "bad"', () => {
  it('uses the token for it, not white', () => {
    for (const sel of ['nav.side .count', '.toast.bad', 'button.danger.solid']) {
      const rule = css.slice(css.indexOf(sel + ' {'))
      expect(rule.slice(0, rule.indexOf('}')), sel).toMatch(/color:\s*var\(--on-bad\)/)
    }
  })
})
