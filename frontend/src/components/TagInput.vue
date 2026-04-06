<script setup>
import { ref } from "vue"

const model = defineModel({
  type: Array,
  default: () => [],
})

const props = defineProps({
  placeholder: {
    type: String,
    default: "Add tag",
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
  <div class="tag-input">
    <div v-if="model.length" class="tag-list">
      <span v-for="(tag, index) in model" :key="`${tag}-${index}`" class="tag-chip">
        <span>{{ tag }}</span>
        <button class="tag-remove" type="button" @click="removeTag(index)" :aria-label="`Remove ${tag}`">
          x
        </button>
      </span>
    </div>

    <input
      v-model="draft"
      class="tag-editor"
      type="text"
      :placeholder="placeholder"
      @keydown="onKeydown"
      @blur="commitDraft"
      @paste="onPaste"
    />
  </div>
</template>

<style scoped>
.tag-input {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 48px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--surface-strong);
}

.tag-input:focus-within {
  border-color: rgba(144, 181, 255, 0.42);
  box-shadow: 0 0 0 4px rgba(144, 181, 255, 0.1);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 0 10px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.05);
  font-size: 12px;
  color: var(--text);
}

.tag-remove {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}

.tag-editor {
  width: 100%;
  min-height: 24px;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--text);
}

.tag-editor:focus {
  outline: none;
}
</style>
