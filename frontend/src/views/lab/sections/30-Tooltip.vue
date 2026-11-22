<script setup>
// Lab: the tooltip (v-tip, InfoTip) - every side, the edges of the window, boxes that cut their content, text that
// is and is not cut, the keyboard. Every value is made up.
import { onBeforeUnmount, ref } from 'vue'
import IconButton from '../../../components/IconButton.vue'
import InfoTip from '../../../components/InfoTip.vue'
import Menu from '../../../components/Menu.vue'
import Trunc from '../../../components/Trunc.vue'

const LONG = 'International Consolidated Aerospace, Defence and Advanced Manufacturing Systems Holdings (North America) Incorporated'
const URL = 'https://careers.example-enterprise-solutions.com/en-CA/jobs/requisition/R-2026-0001847-senior-staff-software-engineer?source=university-portal'
const SENTENCE = 'The score compares the posting with your profile: skills, location, term and the kind of work. It is a guide for sorting, not a decision.'

const corners = ref(false)      // four targets at the corners of the window, to see the tooltip stay inside it
const wide = ref(false)         // the "cut" box made wide enough: the same element then has no tooltip
const n = ref(0)
const timer = setInterval(() => { n.value++ }, 1000)
const gone = ref(false)
function removeSoon() { setTimeout(() => { gone.value = true }, 1500); setTimeout(() => { gone.value = false }, 5000) }
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <p class="lab-note">Hover (350ms) or Tab to an element. Escape, a press, a scroll or leaving hides it; the pointer can move into the tooltip.</p>

  <div class="lab-row" data-t="sides">
    <button v-tip="'Above (the default)'" data-t="top">top</button>
    <button v-tip="{ text: 'Below the button', placement: 'bottom' }" data-t="bottom">bottom</button>
    <button v-tip="{ text: 'To the left', placement: 'left' }" data-t="left">left</button>
    <button v-tip="{ text: 'To the right', placement: 'right' }" data-t="right">right</button>
    <button v-tip="SENTENCE" data-t="sentence">a sentence (wraps at 320px)</button>
    <button v-tip="{ text: SENTENCE, max: 200 }">max: 200</button>
    <button v-tip="URL" data-t="url">a long word (URL)</button>
    <button v-tip="'First line\nSecond line'">two lines</button>
    <button v-tip="''" data-t="empty">empty text: nothing</button>
    <button v-tip="'Seconds on this page: ' + n" data-t="live">text that changes ({{ n }})</button>
    <button class="sm" data-t="vanish-go" @click="removeSoon">remove the next one in 1.5s</button>
    <button v-if="!gone" v-tip="'It goes away with its element'" data-t="vanish">hover me meanwhile</button>
    <button disabled v-tip="'Why it cannot be pressed'">disabled</button>
    <input v-tip="'A field: on keyboard focus, not on a click'" data-t="field" placeholder="a field" style="width: 140px" />
  </div>

  <p class="lab-note">Icon buttons (the label is the tooltip and the accessible name) and InfoTip (hover, focus, or a press - the only way on touch).</p>
  <div class="lab-row" data-t="icons">
    <IconButton icon="eye" label="Show the password" data-t="iconbtn" />
    <IconButton icon="copy" label="Copy" />
    <IconButton icon="refresh" label="Read again" />
    <IconButton icon="trash" label="Delete" tone="danger" />
    <span class="t-primary">Match score <InfoTip :text="SENTENCE" data-t="info" /></span>
    <span class="t-secondary">Below <InfoTip text="Opens below when asked to." placement="bottom" label="About this" /></span>
  </div>

  <p class="lab-note">v-tip.overflow: only when the text is actually cut. The first three are cut, the fourth is not; "wider" makes room and the first stops having one.</p>
  <div class="lab-row" style="align-items: flex-start">
    <div class="lab-box" :style="{ width: wide ? '900px' : '200px', maxWidth: '100%' }"><span v-tip.overflow class="cut" data-t="cut">{{ LONG }}</span></div>
    <div class="lab-box" style="width: 200px"><span v-tip.overflow="'A text given to the directive: ' + URL" class="cut" data-t="cut-given">{{ URL }}</span></div>
    <div class="lab-box" style="width: 200px"><Trunc :text="SENTENCE" :lines="2" data-t="cut2" /></div>
    <div class="lab-box" style="width: 200px"><span v-tip.overflow class="cut" data-t="fits">Northwind</span></div>
    <div class="lab-box" style="width: 200px"><Trunc text="Acme Robotics" data-t="trunc-fits" /></div>
    <button class="sm" data-t="wider" @click="wide = !wide">{{ wide ? 'narrow again' : 'wider' }}</button>
  </div>

  <p class="lab-note">Inside a box that cuts its content, and inside one that scrolls: the tooltip is on &lt;body&gt;, so it is whole; scrolling hides it.</p>
  <div class="lab-row" style="align-items: flex-start">
    <div class="lab-box" style="width: 220px; height: 44px; overflow: hidden" data-t="clip">
      <button v-tip="SENTENCE" class="sm" data-t="in-clip">in overflow: hidden</button>
    </div>
    <div class="lab-box" style="width: 240px; height: 96px; overflow: auto" data-t="scroller">
      <div v-for="i in 12" :key="i" style="display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 6px">
        <span v-tip.overflow class="cut" style="max-width: 120px">Row {{ i }}: {{ LONG }}</span>
        <IconButton icon="more" :label="'Actions of row ' + i" size="sm" />
      </div>
    </div>
  </div>

  <p class="lab-note">In something that lies higher than a tooltip's or a menu's own level (a question is at 81, a select's list at 90): they go over it.</p>
  <div class="lab-row">
    <div class="lab-box" style="position: relative; z-index: 95; display: inline-flex; align-items: center; gap: 12px; background: var(--surface)">
      <button v-tip="{ text: 'Over a box at level 95', placement: 'bottom' }" class="sm" data-t="high-tip">in a box at level 95</button>
      <Menu label="More" :items="[{ id: 'a', label: 'Over it too' }]" align="start" data-t="high-menu" />
    </div>
  </div>

  <p class="lab-note">The right edge of the page, and the corners of the window.</p>
  <div class="lab-row" style="justify-content: space-between">
    <button v-tip="SENTENCE" data-t="edge-left">at the left</button>
    <button class="sm" data-t="corners" @click="corners = !corners">{{ corners ? 'hide' : 'show' }} corner targets</button>
    <button v-tip="{ text: SENTENCE, placement: 'right' }" data-t="edge-right">at the right (asked: right)</button>
  </div>
  <template v-if="corners">
    <button v-tip="SENTENCE" class="sm" data-t="c-tl" style="position: fixed; left: 0; top: 0; z-index: 30">TL</button>
    <button v-tip="SENTENCE" class="sm" data-t="c-tr" style="position: fixed; right: 0; top: 0; z-index: 30">TR</button>
    <button v-tip="{ text: SENTENCE, placement: 'bottom' }" class="sm" data-t="c-bl" style="position: fixed; left: 0; bottom: 0; z-index: 30">BL</button>
    <button v-tip="{ text: SENTENCE, placement: 'right' }" class="sm" data-t="c-br" style="position: fixed; right: 0; bottom: 0; z-index: 30">BR</button>
  </template>
</template>
