<script setup>
import { ref } from "vue"
import { X } from "lucide-vue-next"

const model = defineModel({
  type: Array,
  default: () => [],
})

const props = defineProps({
  placeholder: {
    type: String,
    default: "Add tag",
  },
  disabled: {
    type: Boolean,
    default: false,
  },
})

const draft = ref("")

function commitDraft() {
  appendTags(splitTags(draft.value))
  draft.value = ""
}

function appendTags(values) {
  if (!values.length) {
    return
  }

  const seen = new Set(model.value.map((item) => String(item).trim().toLowerCase()))
  const next = [...model.value]

  values.forEach((value) => {
    const normalized = value.trim()
    const lookup = normalized.toLowerCase()
    if (!normalized || seen.has(lookup)) {
      return
    }
    seen.add(lookup)
    next.push(normalized)
  })

  model.value = next
}

function removeTag(index) {
  model.value = model.value.filter((_, currentIndex) => currentIndex !== index)
}

function onKeydown(event) {
  if (["Enter", ","].includes(event.key)) {
    event.preventDefault()
    commitDraft()
    return
  }

  if (event.key === "Tab") {
    if (draft.value.trim()) {
      commitDraft()
    }
    return
  }

  if (event.key === "Backspace" && !draft.value && model.value.length) {
    removeTag(model.value.length - 1)
  }
}

function onPaste(event) {
  const pasted = event.clipboardData?.getData("text") || ""
  if (!/[\n,;]/.test(pasted)) {
    return
  }

  event.preventDefault()
  appendTags(splitTags(`${draft.value}${pasted}`))
  draft.value = ""
}

function splitTags(value) {
  return String(value || "")
    .split(/[\r\n,;]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}
</script>

<template>
  <div
    class="flex min-h-10 flex-wrap items-center gap-1.5 rounded-md border border-input bg-background px-3 py-1.5 text-sm ring-offset-background focus-within:outline-none focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2"
    :class="{ 'cursor-not-allowed opacity-50': disabled }"
  >
    <span
      v-for="(tag, index) in model"
      :key="`${tag}-${index}`"
      class="inline-flex items-center gap-1 rounded-full border border-transparent bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground"
    >
      <span>{{ tag }}</span>
      <button
        class="rounded-sm opacity-60 transition-opacity hover:opacity-100 focus:outline-none focus:ring-1 focus:ring-ring"
        type="button"
        :disabled="disabled"
        :aria-label="`Remove ${tag}`"
        @click="removeTag(index)"
      >
        <X class="h-3 w-3" />
      </button>
    </span>

    <input
      v-model="draft"
      class="min-w-[8rem] flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed"
      type="text"
      :placeholder="placeholder"
      :disabled="disabled"
      @keydown="onKeydown"
      @blur="commitDraft"
      @paste="onPaste"
    />
  </div>
</template>
