<script setup>
// Lab: the time zone picker against the server's list - nothing chosen (this computer), a zone, an old spelling, a saved
// value that is not a zone, disabled. Nothing here is saved.
import { ref } from 'vue'
import TimeZonePicker from '../../../components/TimeZonePicker.vue'

const follow = ref('')
const zone = ref('America/Vancouver')
const old = ref('US/Pacific')
const bad = ref('Mars/Olympus')
</script>

<template>
  <p class="lab-note">Search by city (English or the interface language), country, IANA id or offset ("+08", "UTC-7"). What would be saved: <b data-t="tz-follow">{{ follow === '' ? '(empty: this computer)' : follow }}</b> · <b data-t="tz-zone">{{ zone }}</b></p>
  <div class="lab-row" data-t="tz-row">
    <TimeZonePicker id="lab-tz-follow" v-model="follow" label="Lab: time zone, nothing chosen" />
    <TimeZonePicker id="lab-tz-zone" v-model="zone" label="Lab: time zone" />
  </div>
  <p class="lab-note">An old spelling that is still valid (shown as written, with what it stands for); a saved value that is not a zone (shown as it is, marked); disabled.</p>
  <div class="lab-row">
    <TimeZonePicker v-model="old" label="Lab: an old spelling" />
    <TimeZonePicker v-model="bad" label="Lab: not a zone" data-t="tz-bad" />
    <TimeZonePicker v-model="zone" label="Lab: disabled" disabled />
  </div>
</template>
