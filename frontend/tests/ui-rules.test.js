// Rules of the interface that can be read off the source, without a browser (docs/ui-quality-assurance.md):
// no browser tooltip, no colours or pixel font sizes of a component's own, no hand-made table for a list of records,
// no icon button without a name. What is drawn is measured elsewhere (tests/test_ui_layout.py).
//
// Each rule has a list of files that do not follow it YET, with how many places are left in each. A file may never
// have more than its number, a file that is not listed may have none, and a listed file that has become clean must
// be taken off the list (so that it stays clean). The lists only ever get shorter:
//
//   UI_RULES_REPORT=1 npx vitest run tests/ui-rules.test.js      prints every list as it would be written today
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = new URL('../src/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')
const GUIDE = 'docs/component-guidelines.md'

function walk(d) {
  return readdirSync(d).flatMap((f) => { const p = join(d, f); return statSync(p).isDirectory() ? walk(p) : f.endsWith('.vue') ? [p] : [] })
}
const FILES = walk(SRC).map((p) => ({ name: p.slice(SRC.length).replace(/\\/g, '/'), text: readFileSync(p, 'utf-8') })).sort((a, b) => a.name.localeCompare(b.name))
const isLab = (f) => f.name.startsWith('views/lab/')

// ── reading a single-file component ─────────────────────────────────────────────────────────────────────────────────
// (Everything that is taken out is replaced by spaces of the same length: a place keeps its line number.)
const blank = (s) => s.replace(/[^\n]/g, ' ')
const lineOf = (text, at) => text.slice(0, at).split('\n').length

// The template: from the first <template> to the last </template>, without comments.
function templateOf(text) {
  const a = text.indexOf('<template'), b = text.lastIndexOf('</template>')
  if (a < 0 || b < 0) return ''
  return (blank(text.slice(0, a)) + text.slice(a, b)).replace(/<!--[\s\S]*?-->/g, blank)
}
// Every opening tag of a template: { tag, attrs: { name: value }, at, end } (`end` is where its content starts).
const TAG = /<([A-Za-z][\w.-]*)((?:\s+[^\s"'<>/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'))?)*)\s*(\/?)>/g
const ATTR = /([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'))?/g
function tagsOf(template) {
  const out = []
  for (const m of template.matchAll(TAG)) {
    const attrs = {}
    for (const a of m[2].matchAll(ATTR)) attrs[a[1]] = a[2] ?? a[3] ?? ''
    out.push({ tag: m[1], attrs, at: m.index, end: m.index + m[0].length, closed: m[3] === '/' })
  }
  return out
}
// An attribute however it is written: name="…", :name="…", v-bind:name="…".
const has = (t, name) => name in t.attrs || ':' + name in t.attrs || 'v-bind:' + name in t.attrs
const isComponent = (tag) => /^[A-Z]/.test(tag)

// The <style> blocks, without comments.
function stylesOf(text) {
  let out = blank(text)
  for (const m of text.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/g)) {
    const at = m.index + m[0].indexOf('>') + 1
    out = out.slice(0, at) + m[1].replace(/\/\*[\s\S]*?\*\//g, blank) + out.slice(at + m[1].length)
  }
  return out
}

// ── the lists ───────────────────────────────────────────────────────────────────────────────────────────────────────
// Files that do not follow a rule yet: how many places each still has. NOT MIGRATED YET - every line here is work that
// is still to be done, and goes when the file is migrated. (Shared components are not allowed here: the one that is,
// is marked.)
const PENDING = {
  // title="…" on an element: the browser's own tooltip. Use v-tip / <Trunc> / <InfoTip> / <IconButton label>.
  title: {
    'App.vue': 3,
    'components/AiPanel.vue': 2,
    'components/EmployersPanel.vue': 3,
    'components/ModelPick.vue': 1,
    'components/RecordPanel.vue': 2,
    // SHARED, reported to the lead: AaSelect hands a caller's `title` on to its button as the browser's tooltip
    // (`:title="attrs.title"`). It should say it with v-tip and keep `attrs.title` only as the accessible name.
    'components/Select.vue': 1,
    'components/SplitBar.vue': 1,
    'components/StackChart.vue': 1,
    'views/ApplicationDetail.vue': 1,
    'views/ApplicationsView.vue': 1,
    'views/CalendarView.vue': 12,
    'views/FilesView.vue': 5,
    'views/HomeView.vue': 2,
    'views/JobsView.vue': 7,
    'views/ProfileView.vue': 1,
    'views/RemoteView.vue': 2,
    'views/RunsView.vue': 1,
    'views/SettingsView.vue': 1,
    'views/TodosView.vue': 1,
    'views/analytics/AppsPanel.vue': 7,
    'views/analytics/AutoPanel.vue': 9,
    'views/analytics/CostPanel.vue': 20,
    'views/analytics/RunDetail.vue': 1,
    'views/calendar/AgendaRow.vue': 1,
    'views/calendar/EventChip.vue': 1,
    'views/calendar/FilterMenu.vue': 1,
    'views/calendar/MonthView.vue': 1,
    'views/calendar/WeekView.vue': 2,
  },
  // a hex colour or `font-size: NNpx` in a <style> block or a style attribute. Use the tokens (var(--text-2),
  // var(--fs-sm)) or the text classes (.t-primary / .t-secondary / .t-meta).
  tokens: {
    'components/MailboxPanel.vue': 1,
    'components/RecordPanel.vue': 1,
    'views/ApplicationDetail.vue': 3,
    'views/JobsView.vue': 2,
    'views/ProfileView.vue': 1,
  },
  // a <table> for a list of records. Use <DataTable>.
  table: {
    'components/EmployersPanel.vue': 1,
    'components/RecordPanel.vue': 1,
    'views/AccountsView.vue': 1,
    'views/ApplicationsView.vue': 1,
    'views/ContactsView.vue': 1,
    'views/JobsView.vue': 1,
    'views/RunsView.vue': 1,
    'views/SourcesView.vue': 1,
    'views/analytics/SitesPanel.vue': 1,
    'views/lab/sections/04-Status.vue': 1,      // the lab's "three weights in one table": to be shown in a DataTable like every other list
  },
  // a button or link that holds an icon alone and has no name. Use <IconButton icon label>, or give it an aria-label.
  name: {
    'views/RemoteView.vue': 2,
  },
}

// Where a <table> is the right thing: figures set out in rows and columns, not a list of records to work through.
const TABLES = new Set([
  'components/DataTable.vue',            // the table itself
  'components/SeriesTable.vue',          // the figures behind a chart
  'components/ColumnChart.vue',          // "as a table" under a chart
  'components/NetworkPanel.vue',         // the three results of a connection test
  'views/AboutView.vue',                 // the components the program is built from: name, version, licence
  'views/SettingsView.vue',              // a grid of tick boxes: which notice goes to which channel
  'views/analytics/AppsPanel.vue',       // analytics figures
  'views/analytics/AutoPanel.vue',       // analytics figures
  'views/analytics/CostPanel.vue',       // analytics figures
  'views/analytics/RunDetail.vue',       // the model requests of one run, with their figures
])

// Elements on which `title` is not a tooltip but the only name the element can carry.
const TITLE_IS_A_NAME = new Set(['iframe'])
// Components that are registered under another name than their file's (main.js).
const FILE_OF = { AaSelect: 'Select' }

// ── the rules ───────────────────────────────────────────────────────────────────────────────────────────────────────
// Does this component declare a prop called `title`? (Then title="…" on it is its own business. Without one, the
// attribute falls through to the component's root element and becomes the browser's tooltip.)
const takesTitle = (() => {
  const known = new Map()
  return (tag) => {
    const base = FILE_OF[tag] || tag
    if (!known.has(base)) {
      const f = FILES.find((x) => x.name.endsWith('/' + base + '.vue'))
      // (not one of ours - RouterLink, Teleport, Transition, component: nothing to say about it)
      known.set(base, !f || /defineProps\(\s*(\{[\s\S]*?\btitle\s*:|\[[^\]]*['"]title['"])/.test(f.text))
    }
    return known.get(base)
  }
})()

const RULES = {
  title(f) {
    return tagsOf(templateOf(f.text)).filter((t) => has(t, 'title') && !TITLE_IS_A_NAME.has(t.tag) && !(isComponent(t.tag) && takesTitle(t.tag)))
      .map((t) => ({ at: t.at, what: `<${t.tag} title>` }))
  },
  tokens(f) {
    if (isLab(f)) return []      // the lab draws swatches and boxes of exact sizes on purpose
    const found = []
    const HEX = /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g
    const PX = /font-size\s*:\s*[\d.]+px|fontSize\s*:\s*['"`]?[\d.]+(?:px)?/g
    const css = stylesOf(f.text)
    // in a style sheet a hex colour stands in a declaration's value (`#id` in a selector is not one)
    for (const m of css.matchAll(/:[^;{}]*/g)) {
      const before = css.slice(0, m.index)
      if (before.lastIndexOf('{') <= before.lastIndexOf('}')) continue      // not inside a block: a selector
      for (const h of m[0].matchAll(HEX)) found.push({ at: m.index + h.index, what: h[0] + ' in <style>' })
    }
    for (const m of css.matchAll(PX)) found.push({ at: m.index, what: m[0].replace(/\s+/g, ' ') + ' in <style>' })
    for (const t of tagsOf(templateOf(f.text))) {
      for (const k of ['style', ':style', 'v-bind:style']) {
        const v = t.attrs[k]
        if (!v) continue
        for (const h of v.matchAll(HEX)) found.push({ at: t.at, what: `${h[0]} in <${t.tag} style>` })
        for (const p of v.matchAll(PX)) found.push({ at: t.at, what: `${p[0].replace(/\s+/g, ' ')} in <${t.tag} style>` })
      }
    }
    return found
  },
  table(f) {
    if (TABLES.has(f.name)) return []
    return tagsOf(templateOf(f.text)).filter((t) => t.tag === 'table').map((t) => ({ at: t.at, what: '<table>' }))
  },
  name(f) {
    const template = templateOf(f.text)
    const found = []
    const named = (t) => has(t, 'aria-label') || has(t, 'aria-labelledby')
    for (const t of tagsOf(template)) {
      if (t.tag === 'IconButton' && !has(t, 'label')) found.push({ at: t.at, what: '<IconButton> without label' })
      if (!['button', 'a', 'RouterLink', 'router-link'].includes(t.tag) || t.closed || named(t)) continue
      const close = template.indexOf('</' + t.tag + '>', t.end)
      if (close < 0) continue
      const inside = template.slice(t.end, close)
      // an icon (or several) and nothing a person or a screen reader could read
      if (/<Icon\b/.test(inside) && !inside.replace(/<Icon\b[^>]*\/?>(?:\s*<\/Icon>)?/g, '').trim()) found.push({ at: t.at, what: `<${t.tag}> with an icon alone and no aria-label` })
    }
    return found
  },
}

const ADVICE = {
  title: `The browser's own tooltip (title="…") is not used: it never shows for the keyboard or on touch and looks different everywhere.\n`
    + `Use v-tip="…" for what an icon does, <Trunc :text> / v-tip.overflow for text that may be cut, <InfoTip :text> for help, <IconButton icon label> for an icon button\n`
    + `(${GUIDE}, "Tooltip"). On a component without a "title" prop the attribute lands on its root element and is a browser tooltip too.`,
  tokens: `Colours and font sizes come from the tokens in src/style.css, not from a component: var(--text) / var(--text-2) / var(--ok) … and var(--fs-xs … --fs-2xl),\n`
    + `or the text classes .t-primary / .t-secondary / .t-meta (${GUIDE}, "Text"; docs/DESIGN_SYSTEM.md section 3).`,
  table: `A list of records is a <DataTable :columns :rows> (fixed columns, one row height, cut text with a tooltip), not a hand-made <table>\n`
    + `(${GUIDE}, "DataTable"). If this really is a small grid of figures, add the file to TABLES in this test and say why.`,
  name: `An icon alone says nothing to a screen reader. Use <IconButton icon="…" :label="$t('…')" /> (the label is the accessible name and the tooltip),\n`
    + `or give the button an aria-label (${GUIDE}, "IconButton").`,
}

const found = Object.fromEntries(Object.keys(RULES).map((rule) => [rule, new Map(FILES.map((f) => [f.name, RULES[rule](f).map((v) => ({ ...v, line: lineOf(f.text, v.at) }))]).filter(([, v]) => v.length))]))

if (process.env.UI_RULES_REPORT) {
  for (const rule of Object.keys(RULES)) {
    console.log(`  ${rule}: {\n` + [...found[rule]].map(([name, v]) => `    '${name}': ${v.length},`).join('\n') + '\n  },')
  }
}

// What a rule finds beyond what its list allows, as lines a person can go to.
function over(rule) {
  const out = []
  for (const [name, v] of found[rule]) {
    const allowed = PENDING[rule][name] || 0
    if (v.length > allowed) out.push(`src/${name}: ${v.length} found` + (allowed ? ` (${allowed} were there before the migration - a new one was added)` : '') + '\n' + v.map((x) => `    line ${x.line}: ${x.what}`).join('\n'))
  }
  return out
}
// Files on a rule's list that follow the rule now (or are gone): their line is to be deleted, so that they stay that way.
const done = (rule) => Object.keys(PENDING[rule]).filter((name) => !found[rule].has(name))

describe('the source of the interface follows the rules a browser is not needed for', () => {
  it('reads the components (the checks below are not passing on nothing)', () => {
    expect(FILES.length).toBeGreaterThan(40)
    const sample = tagsOf(templateOf('<script setup>\nconst a = 1\n</script>\n<template>\n  <!-- <b title="x"> -->\n  <button :title="a > 1 ? \'x\' : \'y\'" @click="go"><Icon name="x" /></button>\n</template>'))
    expect(sample.map((t) => t.tag)).toEqual(['template', 'button', 'Icon'])
    expect(has(sample[1], 'title')).toBe(true)
    const probe = (rule, text) => RULES[rule]({ name: 'views/Probe.vue', text }).map((v) => v.what)
    expect(probe('title', '<template><span title="x">a</span><PageHead title="x" /><iframe title="x" /><Icon title="x" /><AaSelect :title="x" /></template>')).toEqual(['<span title>', '<Icon title>', '<AaSelect title>'])
    expect(probe('tokens', '<template><i style="color: #fff">a</i><b :style="{ fontSize: \'12px\' }">b</b></template>\n<style>\n#app a:hover { color: #1f4fd8; font-size: 13px; }\n.x { color: var(--text); font-size: var(--fs-sm); }\n</style>'))
      .toEqual(['#1f4fd8 in <style>', 'font-size: 13px in <style>', '#fff in <i style>', "fontSize: '12px in <b style>"])
    expect(probe('table', '<template><table><tr><td>1</td></tr></table></template>')).toEqual(['<table>'])
    expect(probe('name', '<template><IconButton icon="x" /><IconButton icon="x" :label="a" /><button><Icon name="x" /></button><button aria-label="x"><Icon name="x" /></button><button><Icon name="x" />Save</button></template>'))
      .toEqual(['<IconButton> without label', '<button> with an icon alone and no aria-label'])
  })

  for (const rule of Object.keys(RULES)) {
    it(`${rule}: nothing new`, () => {
      const lines = over(rule)
      expect(lines, lines.length ? `\n${ADVICE[rule]}\n\n${lines.join('\n')}\n` : '').toEqual([])
    })
    it(`${rule}: a file that follows the rule now is taken off the list of those that do not`, () => {
      const clean = done(rule)
      expect(clean, clean.length ? `\nThese follow the "${rule}" rule now: delete their lines from PENDING.${rule} in frontend/tests/ui-rules.test.js, so that they stay clean.\n` : '').toEqual([])
    })
  }

  it('no shared component is on a list (they are the example the pages follow)', () => {
    const SHARED = ['DataTable', 'Trunc', 'Status', 'IconButton', 'Menu', 'Popover', 'InfoTip', 'TipLayer', 'PageHead', 'SectionHead', 'BulkBar', 'ProviderCard', 'CredentialCell']
      .map((n) => 'components/' + n + '.vue').concat(FILES.filter((f) => f.name.startsWith('components/cells/')).map((f) => f.name))
    const listed = Object.entries(PENDING).flatMap(([rule, list]) => Object.keys(list).filter((name) => SHARED.includes(name)).map((name) => rule + ': ' + name))
    expect(listed).toEqual([])
  })
})
