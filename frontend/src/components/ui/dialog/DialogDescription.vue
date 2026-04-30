<script setup>
import { DialogDescription } from "reka-ui"
import { cn } from "@/lib/utils"
const props = defineProps({ class: { type: [String, Array, Object], default: "" } })
</script>

<template>
  <DialogDescription :class="cn('text-sm text-muted-foreground', props.class)">
    <slot />
  </DialogDescription>
</template>
