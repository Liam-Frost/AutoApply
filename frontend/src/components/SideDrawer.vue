<script setup>
// A detail view beside the page (the product's drawer): long lists and single records open here instead of growing
// the page. `back` shows a way back to the list the record was opened from; Escape and the backdrop close it.
import { onBeforeUnmount, onMounted } from 'vue'
import Icon from './Icon.vue'

const props = defineProps({ title: { type: String, required: true }, sub: { type: String, default: '' }, back: { type: String, default: '' } })
const emit = defineEmits(['close', 'back'])
const onKey = (e) => { if (e.key === 'Escape') emit(props.back ? 'back' : 'close') }
onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div class="overlay" @click="emit('close')"></div>
    <aside class="drawer wide" role="dialog" aria-modal="true" :aria-label="title">
      <div class="drawer-head">
        <div class="grow">
          <button v-if="back" class="ghost sm" style="margin: 0 0 6px -8px" @click="emit('back')"><Icon name="back" />{{ back }}</button>
          <h3>{{ title }}</h3>
          <div v-if="sub" class="muted small" style="margin-top: 2px">{{ sub }}</div>
        </div>
        <button class="ghost" aria-label="关闭" @click="emit('close')"><Icon name="x" /></button>
      </div>
      <slot />
    </aside>
  </Teleport>
</template>
