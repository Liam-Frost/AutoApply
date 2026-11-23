<script setup>
// Lab: the switch - off and on, its words beside it (they name it and flip it), without words (an aria-label), disabled.
import { ref } from 'vue'
import ToggleSwitch from '../../../components/ToggleSwitch.vue'

const quiet = ref(false)
const held = ref(true)
const bare = ref(true)
</script>

<template>
  <p class="lab-note">Space or Enter flips it; so does a press on its words. State: <b data-t="tsw-quiet">{{ quiet ? 'on' : 'off' }}</b> / <b data-t="tsw-held">{{ held ? 'on' : 'off' }}</b></p>
  <div class="lab-row" data-t="tsw-row">
    <ToggleSwitch v-model="quiet" label="Use quiet hours" data-t="tsw-quiet-btn" />
    <ToggleSwitch v-model="held" label="Hold reminders too" />
    <ToggleSwitch v-model="bare" aria-label="Lab: a switch without words" />
  </div>
  <div class="lab-row">
    <ToggleSwitch :model-value="false" label="Disabled, off" disabled />
    <ToggleSwitch :model-value="true" label="Disabled, on" disabled />
  </div>
</template>
