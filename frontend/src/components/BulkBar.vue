<script setup>
// What can be done with the rows that are ticked: how many, the actions (the slot), and "clear". It lies over the
// bottom of the page's own area and moves nothing when it comes or goes. Put it at the top level of a page - not inside
// a box that is a container for queries or is transformed: there "fixed" would mean that box.
defineProps({ count: { type: Number, required: true } })
defineEmits(['clear'])
</script>

<template>
  <div v-if="count > 0" class="bulk-frame">
    <div class="bulkbar" role="toolbar" :aria-label="$t('common.selected', { n: count }, count)">
      <span class="bulk-count" role="status">{{ $t('common.selected', { n: count }, count) }}</span>
      <div class="actions"><slot /></div>
      <button type="button" class="sm ghost bulk-clear" @click="$emit('clear')">{{ $t('common.clearSelection') }}</button>
    </div>
  </div>
</template>
