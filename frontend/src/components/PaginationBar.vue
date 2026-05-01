<script setup>
import { computed } from "vue"
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-vue-next"

import AppSelect from "./AppSelect.vue"
import { Button } from "./ui/button"

const props = defineProps({
  currentPage: { type: Number, required: true },
  totalPages: { type: Number, required: true },
  pageSize: { type: Number, required: true },
  pageSizeOptions: { type: Array, required: true },
  pageJump: { type: [String, Number], default: "" },
  extraClass: { type: String, default: "" },
})

const emit = defineEmits(["update:currentPage", "update:pageSize", "update:pageJump"])

const pageButtons = computed(() => {
  const total = props.totalPages
  const current = props.currentPage

  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => index + 1)
  }

  const buttons = [1]
  const windowStart = Math.max(2, current - 1)
  const windowEnd = Math.min(total - 1, current + 1)

  if (windowStart > 2) {
    buttons.push("ellipsis-left")
  }

  for (let page = windowStart; page <= windowEnd; page += 1) {
    buttons.push(page)
  }

  if (windowEnd < total - 1) {
    buttons.push("ellipsis-right")
  }

  buttons.push(total)
  return buttons
})

function goToPage(page) {
  emit("update:currentPage", Math.min(Math.max(page, 1), props.totalPages))
  emit("update:pageJump", "")
}

function jumpToPage() {
  const page = Number(props.pageJump)
  if (Number.isFinite(page) && page >= 1) {
    goToPage(page)
  }
}
</script>

<template>
  <div class="jobs-pagination-bar" :class="extraClass">
    <div class="jobs-pagination-controls">
      <div class="jobs-page-numbers">
        <Button variant="ghost" size="icon" type="button" aria-label="First page" title="First page" :disabled="currentPage <= 1" @click="goToPage(1)">
          <ChevronsLeft class="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" type="button" aria-label="Previous page" title="Previous page" :disabled="currentPage <= 1" @click="goToPage(currentPage - 1)">
          <ChevronLeft class="h-4 w-4" />
        </Button>
        <button
          v-for="page in pageButtons"
          :key="`${page}`"
          class="jobs-page-button"
          :class="{ 'is-active': page === currentPage, 'is-ellipsis': String(page).startsWith('ellipsis') }"
          type="button"
          :disabled="String(page).startsWith('ellipsis')"
          @click="typeof page === 'number' ? goToPage(page) : null"
        >
          {{ String(page).startsWith('ellipsis') ? '…' : page }}
        </button>
        <input :value="pageJump" class="input jobs-page-jump" type="number" min="1" :max="totalPages" placeholder="#" @input="emit('update:pageJump', $event.target.value)" @keydown.enter.prevent="jumpToPage" />
        <Button variant="ghost" size="icon" type="button" aria-label="Next page" title="Next page" :disabled="currentPage >= totalPages" @click="goToPage(currentPage + 1)">
          <ChevronRight class="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" type="button" aria-label="Last page" title="Last page" :disabled="currentPage >= totalPages" @click="goToPage(totalPages)">
          <ChevronsRight class="h-4 w-4" />
        </Button>
      </div>

      <div class="jobs-page-size">
        <AppSelect :modelValue="pageSize" :options="pageSizeOptions" compact aria-label="Results per page" @update:modelValue="emit('update:pageSize', $event)" />
      </div>
    </div>
  </div>
</template>
