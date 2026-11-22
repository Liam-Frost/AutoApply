<script setup>
// Lab: the roles of text, and Trunc - text that may be longer than its place - with short, long, CJK and unbroken
// text in boxes of several widths. Every value is made up. (The CJK sample is written as code points: nothing in the
// interface's own code is Chinese text.)
import Trunc from '../../../components/Trunc.vue'

const SHORT = 'Northwind'
const LONG = 'International Consolidated Aerospace and Advanced Manufacturing Systems Holdings (North America) Incorporated'
const CJK = String.fromCodePoint(0x4e0a, 0x6d77, 0x4e91, 0x56fe, 0x667a, 0x80fd, 0x79d1, 0x6280, 0x6709, 0x9650, 0x516c, 0x53f8, 0x534e, 0x4e1c, 0x533a, 0x57df, 0x7814, 0x53d1, 0x4e2d, 0x5fc3, 0x4eba, 0x5de5, 0x667a, 0x80fd, 0x4e0e, 0x5927, 0x6570, 0x636e, 0x5e73, 0x53f0, 0x4e8b, 0x4e1a, 0x90e8)
const URL = 'https://careers.example-enterprise.com/en-CA/jobs/requisition/R-2026-0001847-software-engineer-intern?source=university'
const MAIL = 'university-recruiting.north-america.western-region@careers.example-enterprise.com'
const SAMPLES = [['short', SHORT], ['long', LONG], ['CJK', CJK], ['URL', URL], ['e-mail', MAIL]]
const WIDTHS = [120, 200, 320]
const DESC = 'Sent on Nov 18. The employer asked for a transcript and two references; the transcript was uploaded, the references are still to come.'
const FIGURES = [['Applications', '1,284'], ['Replies', '311'], ['Interviews', '27'], ['Cost', '$4.10']]
</script>

<template>
  <p class="lab-note">Roles</p>
  <div class="lab-box" style="margin-bottom: 12px; display: grid; gap: 4px">
    <div class="t-primary">.t-primary - the line that says what a row is: Northwind Robotics</div>
    <div class="t-secondary">.t-secondary - what goes with it: Software Developer Co-op · Vancouver</div>
    <div class="t-meta">.t-meta - the weakest: updated 14:02 · employer site</div>
    <div><span class="meta">.meta - a plain attribute: Workday</span> · <span class="none">—</span> <span class="t-meta">.none, where there is no value</span></div>
  </div>

  <p class="lab-note">Trunc: one line, cut, the whole text in a tooltip only when it is cut (hover or focus a cut one)</p>
  <div class="lab-trunc" data-trunc="one">
    <span></span><code v-for="w in WIDTHS" :key="w">{{ w }}px</code>
    <template v-for="[name, s] in SAMPLES" :key="name">
      <span class="t-meta">{{ name }}</span>
      <div v-for="w in WIDTHS" :key="w" class="lab-box" :style="{ width: w + 'px' }"><Trunc :text="s" /></div>
    </template>
  </div>

  <p class="lab-note" style="margin-top: 12px">Trunc lines="2": a description in a table</p>
  <div class="lab-row" data-trunc="two">
    <div v-for="w in WIDTHS" :key="w" class="lab-box" :style="{ width: w + 'px' }"><Trunc :text="DESC" :lines="2" as="div" /></div>
    <div class="lab-box" style="width: 200px"><Trunc text="Short enough" :lines="2" as="div" /></div>
  </div>

  <p class="lab-note">Trunc with a slot (a link inside; `text` is what the tooltip says), in a flex row beside something that keeps its size</p>
  <div class="lab-box" style="width: 320px; display: flex; gap: 8px; align-items: center; margin-bottom: 12px">
    <Trunc :text="LONG"><a href="#lab-Text">{{ LONG }}</a></Trunc><span class="tag info" style="flex: none">New</span>
  </div>

  <p class="lab-note">Never broken (.atomic): a date, a time, a figure, a short label. Figures under each other: .num</p>
  <div class="lab-row" style="align-items: flex-start">
    <div class="lab-box" style="width: 96px"><span class="atomic">Nov 18, 14:30</span> <span class="atomic t-meta">in 2 days</span></div>
    <div class="lab-box" style="width: 180px">
      <div v-for="[k, v] in FIGURES" :key="k" style="display: flex; justify-content: space-between"><span class="t-secondary">{{ k }}</span><span class="num">{{ v }}</span></div>
    </div>
    <div class="lab-box" style="width: 260px">A paragraph wraps naturally: it is the only kind of text that does. {{ DESC }}</div>
  </div>
</template>

<style>
.lab-trunc { display: grid; grid-template-columns: 60px repeat(3, max-content); gap: 6px 12px; align-items: center; max-width: 100%; overflow-x: auto; }
</style>
