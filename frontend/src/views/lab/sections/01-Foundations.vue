<script setup>
// Lab: the tokens - colours, sizes of text and of controls, weights, space, corners, layers, motion - as they are in
// src/style.css. Nothing here is a component: it is what the components are made of.
const SURFACES = ['--bg', '--surface', '--surface-2', '--neutral-soft', '--border', '--border-strong']
const TEXTS = ['--text', '--text-2', '--text-3', '--primary']
const TONES = ['ok', 'warn', 'bad', 'info']
const KINDS = ['deadline', 'interview', 'assessment', 'offer', 'follow', 'own', 'system']
const SIZES = [['--fs-2xl', '26', 'page title'], ['--fs-xl', '20', 'drawer title, large figure'], ['--fs-lg', '16', 'section title'], ['--fs-ml', '15', 'card title'],
  ['--fs-md', '14', 'text, primary line'], ['--fs-sm', '13', 'secondary line, small button'], ['--fs-xs', '12', 'meta, badge, table header']]
const WEIGHTS = [['--fw-regular', '400'], ['--fw-medium', '500'], ['--fw-semibold', '600'], ['--fw-bold', '650']]
const HEIGHTS = [['--h-xs', '24', 'small icon button'], ['--h-sm', '28', '.sm, icon button'], ['--h-md', '32', 'button, field, drop-down, segmented'], ['--h-lg', '36', '.lg, table header'], ['--h-xl', '40', 'bulk bar']]
const ROWS = [['--row-compact', '40'], ['--row-standard', '56'], ['--row-comfortable', '64']]
const SPACE = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6']
const RADII = ['--r-sm', '--r-md', '--r-lg', '--r-pill']
const LAYERS = [['--z-sticky', '20', 'sticky bar, bulk bar'], ['--z-overlay', '40', "drawer's veil"], ['--z-drawer', '41', 'drawer'], ['--z-pop', '60', 'menu, popover'], ['--z-tip', '70', 'tooltip'], ['--z-toast', '80', 'toast']]
</script>

<template>
  <p class="lab-note">Surfaces and lines</p>
  <div class="lab-row">
    <div v-for="c in SURFACES" :key="c" class="lab-sw"><i :style="{ background: `var(${c})` }"></i><code>{{ c }}</code></div>
  </div>

  <p class="lab-note">Text on the three surfaces (each at least 4.5:1)</p>
  <div class="lab-row">
    <div v-for="bg in ['--bg', '--surface', '--surface-2']" :key="bg" class="lab-box" :style="{ background: `var(${bg})`, minWidth: '200px' }">
      <div v-for="c in TEXTS" :key="c" :style="{ color: `var(${c})` }">{{ c }} on {{ bg }}</div>
    </div>
    <div class="lab-box" style="background: var(--primary); color: var(--on-primary)">--on-primary on --primary</div>
    <div class="lab-box" style="background: var(--bad); color: var(--on-bad)">--on-bad on --bad</div>
    <div class="lab-box" style="background: var(--tip-bg); color: var(--tip-fg); border-color: transparent">--tip-fg on --tip-bg</div>
  </div>

  <p class="lab-note">Meaning: the colour on its soft ground, and on the surface</p>
  <div class="lab-row">
    <div v-for="t in TONES" :key="t" class="lab-box" :style="{ background: `var(--${t}-soft)`, color: `var(--${t})`, borderColor: 'transparent' }">--{{ t }} on --{{ t }}-soft</div>
    <div class="lab-box" style="background: var(--surface)"><span v-for="t in TONES" :key="t" :style="{ color: `var(--${t})`, marginRight: '12px' }">--{{ t }}</span></div>
  </div>

  <p class="lab-note">Kinds of business item (--ev-*): the same colour wherever the kind appears - calendar, tables, detail</p>
  <div class="lab-row">
    <span v-for="k in KINDS" :key="k" class="ev-kind" :class="'ev-' + k">{{ k }}</span>
  </div>

  <p class="lab-note">Text sizes</p>
  <div class="lab-box" style="margin-bottom: 12px">
    <div v-for="[tok, px, use] in SIZES" :key="tok" class="lab-type"><span :style="{ fontSize: `var(${tok})` }">Applications 1,284</span><code>{{ tok }} · {{ px }}px</code><span class="t-meta">{{ use }}</span></div>
  </div>

  <p class="lab-note">Weights (a dense area uses medium for its primary line; bold is for a page's title and large figures)</p>
  <div class="lab-row">
    <span v-for="[tok, n] in WEIGHTS" :key="tok" :style="{ fontWeight: `var(${tok})` }">Northwind Robotics {{ n }} <code>{{ tok }}</code></span>
  </div>

  <p class="lab-note">Heights of controls</p>
  <div class="lab-row" style="align-items: flex-end">
    <div v-for="[tok, px, use] in HEIGHTS" :key="tok" class="lab-h" data-lab-h><i :style="{ height: `var(${tok})` }"></i><code>{{ tok }} · {{ px }}</code><span class="t-meta">{{ use }}</span></div>
  </div>
  <p class="lab-note">Heights of table rows</p>
  <div class="lab-row" style="align-items: flex-end">
    <div v-for="[tok, px] in ROWS" :key="tok" class="lab-h"><i :style="{ height: `var(${tok})` }"></i><code>{{ tok }} · {{ px }}</code></div>
  </div>

  <p class="lab-note">Space (4-pt grid) and corners</p>
  <div class="lab-row" style="align-items: flex-end">
    <div v-for="s in SPACE" :key="s" class="lab-h"><i :style="{ width: `var(${s})`, height: `var(${s})`, minWidth: 0 }"></i><code>{{ s }}</code></div>
    <div v-for="r in RADII" :key="r" class="lab-h"><i :style="{ width: '56px', height: '32px', borderRadius: `var(${r})` }"></i><code>{{ r }}</code></div>
  </div>

  <p class="lab-note">Layers (what lies over what) and motion</p>
  <div class="lab-row">
    <span v-for="[tok, n, use] in LAYERS" :key="tok" class="meta"><code>{{ tok }}</code> {{ n }} · {{ use }}</span>
  </div>
  <div class="lab-row">
    <span class="meta"><code>--dur-fast</code> 120ms · hover, press</span><span class="meta"><code>--dur</code> 160ms · something that opens</span><span class="meta"><code>--ease</code></span>
    <span class="meta">none of it under prefers-reduced-motion</span>
  </div>

  <p class="lab-note">Focus: one ring. Press Tab through these.</p>
  <div class="lab-row">
    <button>Button</button><a href="#lab-Foundations">A link</a><input placeholder="A field" style="width: 140px" /><label><input type="checkbox" /> A checkbox</label>
    <AaSelect model-value="a" aria-label="A drop-down"><option value="a">A drop-down</option><option value="b">Another</option></AaSelect>
  </div>
</template>

<style>
.lab-sw { display: grid; gap: 4px; justify-items: start; }
.lab-sw i { display: block; width: 96px; height: 40px; border: 1px solid var(--border-strong); border-radius: var(--r-sm); }
.lab-type { display: grid; grid-template-columns: minmax(0, 1fr) 150px 220px; gap: var(--s3); align-items: baseline; }
.lab-h { display: grid; gap: 4px; justify-items: start; }
.lab-h i { display: block; min-width: 72px; background: var(--primary-soft); border: 1px solid var(--primary); border-radius: var(--r-sm); }
</style>
