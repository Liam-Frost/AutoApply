<script setup>
import { Label as RekaLabel } from "reka-ui"
import { cn } from "@/lib/utils"

const props = defineProps({
  for: { type: String, default: undefined },
  class: { type: [String, Array, Object], default: "" },
})
</script>

<template>
  <RekaLabel
    :for="props.for"
    :class="cn('text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70', props.class)"
  >
    <slot />
  </RekaLabel>
</template>
