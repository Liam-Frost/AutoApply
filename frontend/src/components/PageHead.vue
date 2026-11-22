<script setup>
// The head of a page: its title, and its actions on one line at the right (secondary first, the main one last).
// `help` is what the page is for, behind an (i) beside the title; `sub` is a line under the title - only what the
// reader has to know to decide something here: most pages have none. (After a change of page the keyboard is put on
// `.page-head h2`: main.js.)
import InfoTip from './InfoTip.vue'

defineProps({ title: { type: String, required: true }, help: { type: String, default: '' }, sub: { type: String, default: '' } })
</script>

<template>
  <header class="page-head">
    <div>
      <div class="page-title"><h2>{{ title }}</h2><InfoTip v-if="help" :text="help" /></div>
      <div v-if="sub || $slots.sub" class="sub"><slot name="sub">{{ sub }}</slot></div>
    </div>
    <div v-if="$slots.default" class="actions"><slot /></div>
  </header>
</template>
