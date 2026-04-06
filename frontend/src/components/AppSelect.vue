<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from "vue"

import AppIcon from "./AppIcon.vue"

const model = defineModel()

const props = defineProps({
  options: {
    type: Array,
    required: true,
  },
  placeholder: {
    type: String,
    default: "Select",
  },
  disabled: {
    type: Boolean,
    default: false,
  },
  compact: {
    type: Boolean,
    default: false,
  },
  ariaLabel: {
    type: String,
    default: "Select option",
  },
})

const rootRef = ref(null)
const open = ref(false)

const selectedOption = computed(() => props.options.find((option) => option.value === model.value) || null)
const displayLabel = computed(() => selectedOption.value?.label || props.placeholder)

function toggleOpen() {
  if (props.disabled) {
    return
  }

  open.value = !open.value
}

function selectOption(value) {
  model.value = value
  open.value = false
}

function onDocumentClick(event) {
  if (!rootRef.value?.contains(event.target)) {
    open.value = false
  }
}

onMounted(() => {
  document.addEventListener("click", onDocumentClick)
})

onBeforeUnmount(() => {
  document.removeEventListener("click", onDocumentClick)
})
</script>

<template>
  <div ref="rootRef" class="app-select" :class="{ 'is-open': open, 'is-compact': compact, 'is-disabled': disabled }">
    <button
      class="app-select-trigger"
      :class="{ 'is-placeholder': !selectedOption }"
      type="button"
      :disabled="disabled"
      :aria-label="ariaLabel"
      @click="toggleOpen"
    >
      <span class="app-select-label">{{ displayLabel }}</span>
      <AppIcon :name="open ? 'chevron-down' : 'chevron-right'" />
    </button>

    <div v-if="open" class="app-select-menu">
      <button
        v-for="option in options"
        :key="`${option.value}`"
        class="app-select-option"
        :class="{ 'is-selected': option.value === model }"
        type="button"
        @click="selectOption(option.value)"
      >
        <span>{{ option.label }}</span>
        <AppIcon v-if="option.value === model" name="check" />
      </button>
    </div>
  </div>
</template>
