<script setup>
// The UI lab: every shared component in its states, with made-up data (never real accounts, mail or postings). For
// development and for the layout tests (tests/test_ui_layout.py); it is not in the navigation. A section is one file
// in ./sections (NN-Name.vue): it is picked up by its name. ?only=Name shows one section; ?narrow=480 sets the width.
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const found = import.meta.glob('./sections/*.vue', { eager: true })
const sections = Object.entries(found).map(([path, m]) => ({ name: path.replace(/^.*\/\d*-?|\.vue$/g, ''), comp: m.default })).sort((a, b) => a.name.localeCompare(b.name))
const route = useRoute()
const shown = computed(() => (route.query.only ? sections.filter((s) => String(route.query.only).split(',').includes(s.name)) : sections))
const width = computed(() => (Number(route.query.narrow) ? Number(route.query.narrow) + 'px' : ''))
</script>

<template>
  <div class="lab" :style="width ? { maxWidth: width } : null">
    <header class="page-head"><div><h2>UI lab</h2></div></header>
    <nav v-if="!route.query.only" class="lab-nav"><a v-for="s in sections" :key="s.name" :href="'#lab-' + s.name">{{ s.name }}</a></nav>
    <section v-for="s in shown" :id="'lab-' + s.name" :key="s.name" class="lab-section" :data-lab="s.name">
      <h3>{{ s.name }}</h3>
      <component :is="s.comp" />
    </section>
  </div>
</template>

<style>
.lab-nav { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-bottom: var(--s4); font-size: var(--fs-sm); }
.lab-section { margin-bottom: var(--s6); }
.lab-section > h3 { margin: 0 0 var(--s3); padding-bottom: 6px; border-bottom: 1px solid var(--border); font-size: var(--fs-lg); }
.lab-row { display: flex; flex-wrap: wrap; gap: var(--s3); align-items: center; margin-bottom: var(--s3); }
.lab-note { color: var(--text-3); font-size: var(--fs-xs); margin: 0 0 6px; }
.lab-box { border: 1px dashed var(--border-strong); padding: var(--s3); border-radius: var(--r-sm); }
</style>
