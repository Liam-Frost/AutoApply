<script setup>
import { computed } from "vue"
import {
  SelectContent,
  SelectGroup,
  SelectIcon,
  SelectItem,
  SelectItemIndicator,
  SelectItemText,
  SelectPortal,
  SelectRoot,
  SelectScrollDownButton,
  SelectScrollUpButton,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from "reka-ui"
import { Check, ChevronDown, ChevronUp } from "lucide-vue-next"
import { cn } from "@/lib/utils"

// reka-ui's SelectItem rejects an empty string value (it is reserved for the
// "no selection" placeholder). Some call-sites use { value: "" } for an
// explicit "Any" / "Disabled" / "All" choice — we need to map between the
// app's "" sentinel and an internal non-empty token transparently.
const EMPTY_TOKEN = "__app-select-empty__"

const model = defineModel()

const props = defineProps({
  options: { type: Array, required: true },
  placeholder: { type: String, default: "Select" },
  disabled: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
  ariaLabel: { type: String, default: "Select option" },
})

function toInternal(value) {
  if (value === undefined || value === null) {
    return undefined
  }
  if (value === "") {
    return EMPTY_TOKEN
  }
  return String(value)
}

function fromInternal(value) {
  if (value === EMPTY_TOKEN) {
    return ""
  }
  // Try to preserve the original option's value type (number vs string)
  const matched = props.options.find((option) => toInternal(option.value) === value)
  return matched ? matched.value : value
}

const internal = computed({
  get() {
    return toInternal(model.value)
  },
  set(next) {
    model.value = fromInternal(next)
  },
})

const triggerHeight = computed(() => (props.compact ? "h-8 text-sm" : "h-10 text-sm"))
</script>

<template>
  <SelectRoot v-model="internal" :disabled="disabled">
    <SelectTrigger
      :aria-label="ariaLabel"
      :class="cn(
        'flex w-full items-center justify-between gap-2 rounded-md border border-input bg-background px-3 py-1.5 ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 data-[placeholder]:text-muted-foreground',
        triggerHeight,
      )"
    >
      <SelectValue :placeholder="placeholder" />
      <SelectIcon as-child>
        <ChevronDown class="h-4 w-4 opacity-60" />
      </SelectIcon>
    </SelectTrigger>

    <SelectPortal>
      <SelectContent
        position="popper"
        :side-offset="4"
        class="relative z-50 max-h-72 min-w-[var(--reka-select-trigger-width)] overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
      >
        <SelectScrollUpButton class="flex h-6 cursor-default items-center justify-center bg-popover">
          <ChevronUp class="h-4 w-4" />
        </SelectScrollUpButton>
        <SelectViewport class="p-1">
          <SelectGroup>
            <SelectItem
              v-for="option in options"
              :key="toInternal(option.value)"
              :value="toInternal(option.value)"
              :disabled="option.disabled"
              class="relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-8 pr-2 text-sm outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
            >
              <span class="absolute left-2 flex h-3.5 w-3.5 items-center justify-center">
                <SelectItemIndicator>
                  <Check class="h-4 w-4" />
                </SelectItemIndicator>
              </span>
              <SelectItemText>{{ option.label }}</SelectItemText>
            </SelectItem>
          </SelectGroup>
        </SelectViewport>
        <SelectScrollDownButton class="flex h-6 cursor-default items-center justify-center bg-popover">
          <ChevronDown class="h-4 w-4" />
        </SelectScrollDownButton>
      </SelectContent>
    </SelectPortal>
  </SelectRoot>
</template>
