<script setup>
// Detail that belongs to a row of the analysis page: it opens below the row, across the whole width, and goes away
// again - an overview card never grows to hold it. Place it as the last child of the row (`.an-row`).
import Icon from './Icon.vue'

defineProps({ title: { type: String, required: true }, sub: { type: String, default: '' } })
defineEmits(['close'])
</script>

<template>
  <section class="card an-detail" :aria-label="title">
    <div class="card-head">
      <span class="card-title">{{ title }}</span>
      <button class="ghost sm" @click="$emit('close')"><Icon name="chevron_up" />{{ $t('common.collapse') }}</button>
    </div>
    <p v-if="sub" class="card-sub">{{ sub }}</p>
    <slot />
  </section>
</template>
