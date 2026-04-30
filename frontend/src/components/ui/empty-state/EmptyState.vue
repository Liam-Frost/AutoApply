<script setup>
import { cn } from "@/lib/utils"

const props = defineProps({
  title: { type: String, required: true },
  description: { type: String, default: "" },
  class: { type: [String, Array, Object], default: "" },
})
</script>

<template>
  <div :class="cn('flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-muted/40 px-6 py-12 text-center', props.class)">
    <div v-if="$slots.icon" class="text-muted-foreground [&_svg]:size-10">
      <slot name="icon" />
    </div>
    <h3 class="text-base font-semibold text-foreground">{{ title }}</h3>
    <p v-if="description" class="max-w-sm text-sm text-muted-foreground">{{ description }}</p>
    <div v-if="$slots.action" class="mt-2">
      <slot name="action" />
    </div>
  </div>
</template>
