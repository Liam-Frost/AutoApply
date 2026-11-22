<script setup>
// One section of the settings: a heading that can be linked to (/settings/<group>/<id>), and a word on how what is
// in it gets saved when that is not the usual way: by a button of its own, or at once (a plain attribute: .meta). The
// usual way - the page's Save at the top right - is not repeated on every section.
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const props = defineProps({ id: { type: String, required: true }, title: { type: String, required: true }, how: { type: String, default: 'top' } })
const route = useRoute()
const here = computed(() => route.params.section === props.id)
const HOW = { own: 'common.set.own', now: 'common.set.now' }
</script>

<template>
  <section :id="'set-' + id" class="set-sec" :class="{ here }" :aria-labelledby="'set-h-' + id">
    <div class="set-head">
      <h3 :id="'set-h-' + id">{{ title }}</h3>
      <span v-if="HOW[how]" class="meta small">{{ $t(HOW[how]) }}</span>
      <span class="grow"></span>
      <slot name="actions" />
    </div>
    <slot />
  </section>
</template>
