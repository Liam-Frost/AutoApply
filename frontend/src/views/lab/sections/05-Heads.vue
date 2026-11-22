<script setup>
// Lab: the head of a page, the head of a section, and the bar of what can be done with ticked rows. The bar here is
// the real one: tick rows and it lies over the bottom of the page.
import { ref } from 'vue'
import BulkBar from '../../../components/BulkBar.vue'
import Icon from '../../../components/Icon.vue'
import IconButton from '../../../components/IconButton.vue'
import PageHead from '../../../components/PageHead.vue'
import SectionHead from '../../../components/SectionHead.vue'

const ROWS = ['Northwind Robotics', 'Fjord Energy', 'Juniper Logistics', 'Larkspur AI']
const picked = ref(new Set())
function tick(r) { const next = new Set(picked.value); next.has(r) ? next.delete(r) : next.add(r); picked.value = next }
const did = ref('')
</script>

<template>
  <p class="lab-note">PageHead: a title alone</p>
  <div class="lab-box" data-head="plain"><PageHead title="Applications" /></div>

  <p class="lab-note" style="margin-top: 12px">PageHead: help behind an (i), and the actions - secondary first, the main one last</p>
  <div class="lab-box" data-head="actions">
    <PageHead title="Postings" help="The postings the program found or you added. Decide here which to apply to.">
      <button class="ghost"><Icon name="edit" />Add by hand</button><button><Icon name="refresh" />Scan</button><button class="primary"><Icon name="search" />Sources</button>
    </PageHead>
  </div>

  <p class="lab-note" style="margin-top: 12px">PageHead: a line under the title (only what is needed to decide something here), in a box of 520px - the actions go under the title as a whole</p>
  <div class="lab-box" style="width: 520px; max-width: 100%" data-head="narrow">
    <PageHead title="Northwind Robotics · Software Developer Co-op" sub="Workday · Vancouver · closes in 2 days">
      <button>Run again</button><button class="primary">Approve and submit</button>
    </PageHead>
  </div>

  <p class="lab-note" style="margin-top: 12px">SectionHead: a title; with a count; with help and actions</p>
  <div class="lab-box" data-head="section">
    <SectionHead title="Waiting for you" />
    <div class="card" style="margin: 0">A card of the section.</div>
    <SectionHead title="Sign-in providers" :count="3" />
    <div class="card" style="margin: 0"><div class="card-title">A card's title</div>A card of the section: its title is one step smaller than the section's.</div>
    <SectionHead title="Site accounts" :count="12" help="One row for each site the program has an account on.">
      <button class="ghost sm"><Icon name="refresh" />Check all</button><button class="sm">Add an account</button><IconButton icon="more" label="More" />
    </SectionHead>
    <div class="card" style="margin: 0">A card of the section.</div>
  </div>

  <p class="lab-note" style="margin-top: 12px">BulkBar: tick rows - the bar comes over the bottom of the page and nothing moves</p>
  <div class="lab-box" data-head="bulk">
    <label v-for="r in ROWS" :key="r" style="display: flex; align-items: center; gap: 8px; height: 32px"><input type="checkbox" :checked="picked.has(r)" :aria-label="'Select ' + r" @change="tick(r)" />{{ r }}</label>
    <span class="t-meta">{{ did || 'Nothing done yet.' }}</span>
  </div>
  <BulkBar :count="picked.size" @clear="picked = new Set()">
    <button class="sm primary" @click="did = 'Started ' + picked.size">Start applications</button>
    <button class="sm" @click="did = 'Scored ' + picked.size">Score again</button>
    <button class="sm" @click="did = 'Archived ' + picked.size">Archive</button>
  </BulkBar>
</template>
