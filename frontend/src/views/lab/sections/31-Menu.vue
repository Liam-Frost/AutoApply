<script setup>
// Lab: the menu - icons, a hint, danger, disabled, dividers; at the edges of the window; in a row that opens on a
// click; in a drawer (with a popover and a tooltip over it); a long one. Every value is made up.
import { ref } from 'vue'
import InfoTip from '../../../components/InfoTip.vue'
import Menu from '../../../components/Menu.vue'
import Popover from '../../../components/Popover.vue'
import SideDrawer from '../../../components/SideDrawer.vue'
import { ask } from '../../../ui'

const ITEMS = [
  { id: 'open', label: 'Open the posting', icon: 'external' },
  { id: 'copy', label: 'Copy the link', icon: 'copy' },
  { id: 'signin', label: 'Sign in again', icon: 'login', hint: 'The saved session ended on Nov 18' },
  { id: 'export', label: 'Export', icon: 'download', disabled: true, hint: 'Nothing to export yet' },
  { divider: true },
  { id: 'clear', label: 'Clear the session', icon: 'x' },
  { id: 'delete', label: 'Delete the account', icon: 'trash', danger: true },
]
const PLAIN = [{ id: 'name', label: 'By name' }, { id: 'date', label: 'By date' }, { id: 'state', label: 'By state' }]
const MIXED = [{ id: 'edit', label: 'Edit', icon: 'edit' }, { id: 'duplicate', label: 'Duplicate' }, { divider: true }, { id: 'archive', label: 'Archive', hint: 'It can be brought back from the archive' }]
const MANY = Array.from({ length: 40 }, (_, i) => ({ id: 'n' + (i + 1), label: 'Employer ' + (i + 1) }))

const picked = ref('')
const rowOpened = ref(0)
const drawer = ref(false)
const level = ref('standard')
async function onPick(id) {
  if (id === 'delete' && !(await ask('Delete this made-up account?', { danger: true }))) { picked.value = 'delete: cancelled'; return }
  picked.value = id
}
</script>

<template>
  <p class="lab-note">Arrow keys, Home / End, a letter, Enter, Escape; Tab closes. The focus returns to the button. Picked: <b data-t="picked">{{ picked || '—' }}</b></p>

  <div class="lab-row" data-t="menus">
    <Menu label="More" :items="ITEMS" data-t="m-default" @pick="onPick" />
    <Menu label="More, from the start edge" :items="ITEMS" align="start" data-t="m-start" @pick="onPick" />
    <Menu label="Small button" :items="MIXED" size="sm" data-t="m-mixed" @pick="onPick" />
    <Menu label="Sort" :items="PLAIN" align="start" data-t="m-slot" @pick="onPick">
      <template #trigger="{ open, toggle, attrs }">
        <button class="sm" v-bind="attrs" data-t="m-slot-btn" @click="toggle">Sort{{ open ? ' (open)' : '' }}</button>
      </template>
    </Menu>
    <Menu label="A long menu" :items="MANY" align="start" data-t="m-many" @pick="onPick" />
    <Menu label="Cannot be opened" :items="PLAIN" disabled />
    <button class="sm" data-t="open-drawer" @click="drawer = true">Open a drawer with a menu in it</button>
  </div>

  <p class="lab-note">At the right edge (the menu stays inside the window), and in a row that opens on a click: the menu's button does not open the row. Row opened: <b data-t="row-opened">{{ rowOpened }}</b></p>
  <div class="lab-box" style="display: flex; align-items: center; gap: 12px; cursor: pointer" data-t="row" tabindex="0" @click="rowOpened++" @keydown.enter="rowOpened++">
    <span class="grow">A row that opens on a click</span>
    <InfoTip text="Neither does the (i)." data-t="row-info" />
    <Menu label="More" :items="ITEMS" data-t="m-row" @pick="onPick" />
  </div>
  <div class="lab-row" style="justify-content: flex-end; margin-top: 12px">
    <Menu label="More, from the start edge at the right" :items="ITEMS" align="start" data-t="m-edge" @pick="onPick" />
  </div>

  <SideDrawer v-if="drawer" title="A drawer" sub="Escape closes the menu first, then the drawer" :wide="false" @close="drawer = false">
    <div class="lab-row" data-t="in-drawer">
      <span>An account <InfoTip text="A tooltip over the drawer." data-t="d-info" /></span>
      <Menu label="More" :items="ITEMS" data-t="m-drawer" @pick="onPick" />
      <Popover label="How often" :width="260">
        <template #trigger="{ toggle, attrs }"><button class="sm" v-bind="attrs" data-t="d-pop-btn" @click="toggle">A popover</button></template>
        <div class="field"><label>Check every</label>
          <AaSelect v-model="level" data-t="d-select"><option value="often">hour</option><option value="standard">day</option><option value="rare">week</option></AaSelect>
        </div>
      </Popover>
    </div>
    <p class="lab-note">Picked: {{ picked || '—' }}</p>
  </SideDrawer>
</template>
