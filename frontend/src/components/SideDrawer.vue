<script setup>
// A detail view beside the page (the product's drawer): long lists and single records open here instead of growing
// the page. `back` shows a way back to the list the record was opened from; Escape and the backdrop close it.
// It holds the keyboard while it is open (focus.js): the focus goes into it and comes back to where it was.
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { hold, onTop } from '../focus'
import Icon from './Icon.vue'

const props = defineProps({ title: { type: String, required: true }, sub: { type: String, default: '' }, back: { type: String, default: '' }, wide: { type: Boolean, default: true } })
const emit = defineEmits(['close', 'back'])
const box = ref(null)
let release = null
// (only when the drawer is what is on top: with a question open over it, Escape answers the question)
const onKey = (e) => { if (e.key === 'Escape' && box.value && onTop(box.value)) emit(props.back ? 'back' : 'close') }
onMounted(() => { window.addEventListener('keydown', onKey); release = hold(box.value) })
onBeforeUnmount(() => { window.removeEventListener('keydown', onKey); if (release) release() })
</script>

<template>
  <Teleport to="body">
    <div class="overlay" @click="emit('close')"></div>
    <aside ref="box" class="drawer" :class="{ wide }" role="dialog" aria-modal="true" :aria-label="title">
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
