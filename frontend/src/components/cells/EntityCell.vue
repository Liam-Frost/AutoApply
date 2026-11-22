<script setup>
// Who or what a row is: a main line and, under it, what tells it from the next - company + title, site + host,
// name + e-mail, file + kind. Each line is cut on its own (the whole of it in a tooltip when it is cut); without a
// second line the first stands in the middle. Slot `after`: a small mark right after the main line's words.
import Trunc from '../Trunc.vue'

defineProps({
  primary: { type: String, default: '' },
  secondary: { type: String, default: '' },
  to: { type: [String, Object], default: null },      // the main line as a link to the row's own page
})
</script>

<template>
  <div class="entity">
    <div class="entity-1">
      <!-- (the link itself is the element that is cut: its focus ring is around the words, not cut with them) -->
      <RouterLink v-if="to" v-slot="{ href, navigate }" :to="to" custom>
        <Trunc as="a" class="t-primary entity-link" :href="href" :text="primary" @click="navigate" />
      </RouterLink>
      <Trunc v-else class="t-primary" :text="primary" />
      <span v-if="$slots.after" class="entity-after"><slot name="after" /></span>
    </div>
    <Trunc v-if="secondary" as="div" class="t-secondary entity-2" :text="secondary" />
  </div>
</template>
