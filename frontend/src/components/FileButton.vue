<script setup>
// "Choose a file" as a button. It was a <label> around a hidden file input: a mouse could press it, the keyboard
// could not reach it (a label does not take the focus, and the input was not there for it either).
import { ref } from 'vue'

defineOptions({ inheritAttrs: false })
defineProps({ accept: { type: String, default: '' }, multiple: Boolean, disabled: Boolean })
const emit = defineEmits(['change'])
const input = ref(null)
</script>

<template>
  <button type="button" v-bind="$attrs" :disabled="disabled" @click="input.click()"><slot /></button>
  <input ref="input" type="file" hidden :accept="accept || undefined" :multiple="multiple" :disabled="disabled" tabindex="-1" aria-hidden="true" @change="emit('change', $event)" />
</template>
