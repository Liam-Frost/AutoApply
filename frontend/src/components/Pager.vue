<script setup>
// Paging for a list that can be long: where you are, back, forward. `page` is zero-based (v-model:page).
import { computed } from 'vue'

const props = defineProps({ page: { type: Number, default: 0 }, size: { type: Number, default: 15 }, total: { type: Number, required: true } })
const emit = defineEmits(['update:page'])
const pages = computed(() => Math.max(1, Math.ceil(props.total / props.size)))
const from = computed(() => (props.total ? props.page * props.size + 1 : 0))
const to = computed(() => Math.min(props.total, (props.page + 1) * props.size))
</script>

<template>
  <div v-if="total > size" class="pager">
    <span class="where">{{ $t('common.pager.range', { from, to, total }) }}</span>
    <button class="sm" :disabled="page <= 0" @click="emit('update:page', page - 1)">{{ $t('common.pager.prev') }}</button>
    <span class="small muted">{{ page + 1 }} / {{ pages }}</span>
    <button class="sm" :disabled="page >= pages - 1" @click="emit('update:page', page + 1)">{{ $t('common.pager.next') }}</button>
  </div>
</template>
