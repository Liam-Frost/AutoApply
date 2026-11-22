<script setup>
// Lab: every kind and size of button, the controls of one level side by side (one height), a group of actions, and
// IconButton in each of its states. Nothing here does anything but show itself.
import { ref } from 'vue'
import Icon from '../../../components/Icon.vue'
import IconButton from '../../../components/IconButton.vue'

const KINDS = [['', 'Secondary'], ['primary', 'Primary'], ['ghost', 'Ghost'], ['danger', 'Danger'], ['danger solid', 'Danger, solid']]
const seg = ref('week')
const pick = ref('all')
const shown = ref(false)
const starred = ref(true)
const loading = ref(false)
const presses = ref(0)
function work() { loading.value = true; setTimeout(() => { loading.value = false }, 1800) }
</script>

<template>
  <p class="lab-note">Kinds, at the three sizes: .sm 28 · default 32 · .lg 36</p>
  <div v-for="size in ['sm', '', 'lg']" :key="size" class="lab-row" :data-btn-size="size || 'md'">
    <button v-for="[k, name] in KINDS" :key="k" :class="[k, size]">{{ name }}</button>
    <button :class="['primary', size]"><Icon name="plus" />With an icon</button>
    <a href="#lab-Buttons" class="btn" :class="size">A link as a button</a>
  </div>

  <p class="lab-note">States: disabled, under way (what ui.run does to the button that was pressed), a long label (never wraps)</p>
  <div class="lab-row">
    <button disabled>Disabled</button><button class="primary" disabled>Disabled</button><button class="ghost" disabled>Disabled</button>
    <button data-busy aria-busy="true">Saving</button><button class="primary" data-busy aria-busy="true">Saving</button>
  </div>
  <div class="lab-box" style="width: 240px; margin-bottom: 12px; overflow: hidden">
    <button>A label that is longer than the box it stands in</button>
  </div>

  <p class="lab-note">One level, one height: a button, a field, a drop-down and a segmented control beside each other</p>
  <div class="lab-row" data-level="md">
    <button>Button</button>
    <input placeholder="Search" style="width: 160px" />
    <input type="number" value="8" style="width: 72px" aria-label="A number" />
    <input type="date" value="2026-11-24" aria-label="A date" />
    <AaSelect v-model="pick" aria-label="A drop-down"><option value="all">All terms</option><option value="s">Summer 2027</option></AaSelect>
    <div class="seg"><button v-for="v in ['day', 'week', 'month']" :key="v" :class="{ on: seg === v }" @click="seg = v">{{ v }}</button></div>
    <button class="primary">Primary</button>
  </div>
  <div class="lab-row" data-level="sm">
    <button class="sm">Button</button>
    <input class="sm" placeholder="Search" style="width: 160px" />
    <AaSelect v-model="pick" small aria-label="A small drop-down"><option value="all">All terms</option><option value="s">Summer 2027</option></AaSelect>
    <button class="sm primary">Primary</button>
    <IconButton icon="refresh" label="Refresh" />
  </div>
  <p class="lab-note">A textarea is as tall as what it holds; a checkbox and a radio are 17px</p>
  <div class="lab-row">
    <textarea rows="2" style="width: 260px; min-height: 0" aria-label="A note">Two lines
of text</textarea>
    <label><input type="checkbox" checked /> Ticked</label><label><input type="checkbox" /> Not ticked</label>
    <label><input type="radio" name="lab-radio" checked /> This</label><label><input type="radio" name="lab-radio" /> That</label>
    <label><input type="checkbox" disabled /> Disabled</label>
  </div>

  <p class="lab-note">A group of actions (.actions): one line, 8px apart, secondary first and the main one last</p>
  <div class="lab-box" style="margin-bottom: 12px">
    <div class="actions"><button class="ghost"><Icon name="edit" />Add by hand</button><button><Icon name="refresh" />Scan</button><button class="primary"><Icon name="search" />Sources</button></div>
  </div>

  <p class="lab-note">IconButton: default (hover and focus it), pressed (a toggle), under way, disabled, danger - at md 28 and sm 24</p>
  <div v-for="size in ['md', 'sm']" :key="size" class="lab-row" :data-icon-size="size">
    <IconButton icon="copy" label="Copy" :size="size" @click="presses++" />
    <IconButton :icon="shown ? 'eye_off' : 'eye'" :label="shown ? 'Hide the password' : 'Show the password'" :size="size" :pressed="shown" @click="shown = !shown" />
    <IconButton icon="star" :label="starred ? 'Priority employer: on' : 'Priority employer: off'" :size="size" :pressed="starred" @click="starred = !starred" />
    <IconButton icon="refresh" label="Check again" :size="size" :loading="loading" @click="work(); presses++" />
    <IconButton icon="refresh" label="Checking" :size="size" loading />
    <IconButton icon="edit" label="Edit (not now)" :size="size" disabled />
    <IconButton icon="trash" label="Delete" :size="size" tone="danger" />
    <IconButton icon="more" label="More" :size="size" />
    <span class="t-meta num">pressed {{ presses }}</span>
  </div>
  <p class="lab-note">In a row of text, and in a line with a small button</p>
  <div class="lab-row">
    <span class="t-secondary">p.wong.demo{{ '@' }}example.com</span><IconButton icon="copy" label="Copy the address" size="sm" />
    <button class="ghost sm">Open</button><IconButton icon="external" label="Open the site" />
  </div>
</template>
