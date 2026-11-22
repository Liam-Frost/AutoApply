<script setup>
// Lab: the popover - help that is more than a sentence, a small form with a select, every side, the right edge of the
// window, content taller than the window, a menu inside. Every value is made up.
import { reactive, ref } from 'vue'
import Icon from '../../../components/Icon.vue'
import InfoTip from '../../../components/InfoTip.vue'
import Menu from '../../../components/Menu.vue'
import Popover from '../../../components/Popover.vue'

const saved = reactive({ name: 'Chromium', profile: 'own', headless: false })
const form = reactive({ ...saved })
const state = ref('')
const more = ref(false)
function save(close) { Object.assign(saved, form); state.value = 'saved'; close() }
function cancel(close) { Object.assign(form, saved); state.value = 'cancelled'; close() }
</script>

<template>
  <p class="lab-note">The focus goes in; Escape or a press outside closes and the focus returns. Saved: <b data-t="saved">{{ saved.name }} / {{ saved.profile }} / {{ saved.headless ? 'hidden' : 'shown' }}</b> <span data-t="state">{{ state }}</span></p>

  <div class="lab-row" data-t="popovers">
    <Popover label="How the score is worked out" :width="300" data-t="p-help">
      <template #trigger="{ toggle, attrs }"><button class="ghost sm" v-bind="attrs" data-t="p-help-btn" @click="toggle"><Icon name="help" />How is it scored?</button></template>
      <p><b>The score is a guide for sorting.</b></p>
      <p>It compares the posting with your profile:</p>
      <ul style="margin: 0 0 8px; padding-left: 18px"><li>skills that are asked for</li><li>the place and the term</li><li>the kind of work</li></ul>
      <p class="t-meta">Nothing is sent or declined because of it.</p>
    </Popover>

    <Popover label="The browser of this site" :width="320" data-t="p-form" @open="state = 'open'">
      <template #trigger="{ open, toggle, attrs }"><button class="sm" v-bind="attrs" data-t="p-form-btn" @click="toggle"><Icon name="settings" />Browser{{ open ? ' (open)' : '' }}</button></template>
      <template #default="{ close }">
        <div class="field"><label for="lab-pop-name">Name <InfoTip text="A tooltip over the popover." data-t="p-info" /></label><input id="lab-pop-name" v-model="form.name" data-t="p-name" /></div>
        <div class="field"><label>Profile</label>
          <AaSelect v-model="form.profile" data-t="p-select"><option value="own">Its own profile</option><option value="shared">The shared profile</option><option value="none">No profile: a clean window every time</option></AaSelect>
        </div>
        <label style="display: flex; gap: 8px; align-items: center; margin-bottom: 12px"><input v-model="form.headless" type="checkbox" /> Keep the window hidden</label>
        <button class="ghost sm" style="margin-bottom: 8px" @click="more = !more">{{ more ? 'Less' : 'More settings' }}</button>
        <p v-if="more" class="t-secondary">The box grows and stays beside its button. Lorem ipsum is not used here: these are words about a browser that does not exist, long enough to wrap over several lines.</p>
        <div class="actions" style="display: flex; justify-content: flex-end; gap: 8px">
          <button class="sm" data-t="p-cancel" @click="cancel(close)">Cancel</button>
          <button class="primary sm" data-t="p-save" @click="save(close)">Save</button>
        </div>
      </template>
    </Popover>

    <Popover label="Above" placement="top" align="center" :width="220"><template #trigger="{ toggle }"><button class="sm" @click="toggle">top, centred</button></template><p>Opens above when there is room, below when there is not.</p></Popover>
    <Popover label="Beside" placement="right" :width="220"><template #trigger="{ toggle }"><button class="sm" @click="toggle">right</button></template><p>Beside its button, its top in line with the button's.</p></Popover>
    <Popover label="Left" placement="left" :width="220"><template #trigger="{ toggle }"><button class="sm" @click="toggle">left (no room: flips)</button></template><p>There is no room on the left of the first buttons, so it opens on the right.</p></Popover>

    <Popover label="A long text" :width="280" data-t="p-tall">
      <template #trigger="{ toggle }"><button class="sm" data-t="p-tall-btn" @click="toggle">taller than the window</button></template>
      <p v-for="i in 40" :key="i">Line {{ i }} of a text that is longer than the window: the box scrolls inside.</p>
    </Popover>

    <Popover label="With a menu" :width="240" data-t="p-menu">
      <template #trigger="{ toggle }"><button class="sm" data-t="p-menu-btn" @click="toggle">with a menu inside</button></template>
      <div style="display: flex; align-items: center; justify-content: space-between"><span>A saved session</span>
        <Menu label="More" :items="[{ id: 'a', label: 'Check it now', icon: 'refresh' }, { id: 'b', label: 'Forget it', icon: 'trash', danger: true }]" data-t="p-menu-menu" @pick="(id) => (state = 'menu: ' + id)" />
      </div>
    </Popover>
  </div>

  <div class="lab-row" style="justify-content: flex-end">
    <Popover label="At the edge" :width="320" data-t="p-edge">
      <template #trigger="{ toggle }"><button class="sm" data-t="p-edge-btn" @click="toggle">at the right edge</button></template>
      <p>Asked to line up with the start of its button, moved left to stay inside the window.</p>
    </Popover>
  </div>
</template>
